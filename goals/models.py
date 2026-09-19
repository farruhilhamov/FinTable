"""Цели накопления: «накопить X к дате».

Прогресс берётся из привязанного счёта или вклада (баланс на сегодня),
либо из вручную вносимой суммы `saved_manual`.
"""
import calendar
from datetime import date
from decimal import Decimal
from typing import Optional

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from finance.models import TimeStampedModel


class Goal(TimeStampedModel):
    ACTIVE = 'active'
    DONE = 'done'
    CANCELLED = 'cancelled'
    STATUS_CHOICES = [(ACTIVE, 'Активна'), (DONE, 'Достигнута'), (CANCELLED, 'Отменена')]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='goals'
    )
    name = models.CharField('Цель', max_length=120)
    target_amount = models.DecimalField(
        'Нужно накопить', max_digits=18, decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
    )
    deadline = models.DateField('Срок', null=True, blank=True)
    account = models.ForeignKey(
        'finance.Account', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='goals', verbose_name='Копить на счёте',
    )
    deposit = models.ForeignKey(
        'deposits.Deposit', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='goals', verbose_name='Копить на вкладе',
    )
    saved_manual = models.DecimalField(
        'Уже накоплено (вручную)', max_digits=18, decimal_places=2, default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
        help_text='Используется, если не выбран счёт или вклад.',
    )
    status = models.CharField('Статус', max_length=10, choices=STATUS_CHOICES, default=ACTIVE)
    note = models.CharField('Заметка', max_length=255, blank=True)

    class Meta:
        ordering = ['status', 'deadline', 'name']

    def __str__(self):
        return f'{self.name}: {self.target_amount}'

    def clean(self):
        super().clean()
        if self.account_id and self.deposit_id:
            raise ValidationError('Выберите либо счёт, либо вклад — не оба сразу')
        if self.account_id and self.user_id and self.account.user_id != self.user_id:
            raise ValidationError({'account': 'Счёт принадлежит другому пользователю'})
        if self.deposit_id and self.user_id and self.deposit.user_id != self.user_id:
            raise ValidationError({'deposit': 'Вклад принадлежит другому пользователю'})

    # ---- прогресс ----

    def current_amount(self, today: Optional[date] = None) -> Decimal:
        if self.account_id:
            return max(self.account.balance(today), Decimal('0'))
        if self.deposit_id:
            d = self.deposit
            return d.principal_amount + d.get_accrued_income(today)
        return self.saved_manual or Decimal('0')

    def progress_pct(self, today: Optional[date] = None) -> int:
        if not self.target_amount:
            return 0
        return int(min(self.current_amount(today) / self.target_amount * 100, Decimal('100')))

    def remaining(self, today: Optional[date] = None) -> Decimal:
        return max(self.target_amount - self.current_amount(today), Decimal('0'))

    def months_left(self, today: Optional[date] = None) -> Optional[int]:
        if not self.deadline:
            return None
        today = today or timezone.localdate()
        months = (self.deadline.year - today.year) * 12 + (self.deadline.month - today.month)
        if self.deadline.day >= today.day:
            months += 1
        return max(months, 0)

    def required_monthly(self, today: Optional[date] = None) -> Optional[Decimal]:
        """Сколько откладывать в месяц, чтобы успеть к сроку."""
        m = self.months_left(today)
        rem = self.remaining(today)
        if m is None:
            return None
        if rem <= 0:
            return Decimal('0')
        if m == 0:
            return rem
        return (rem / m).quantize(Decimal('1'))

    def eta(self, monthly_saving: Decimal, today: Optional[date] = None) -> Optional[date]:
        """Прогноз даты достижения при заданном темпе накопления."""
        rem = self.remaining(today)
        if rem <= 0:
            return today or timezone.localdate()
        if not monthly_saving or monthly_saving <= 0:
            return None
        months = int((rem / monthly_saving).to_integral_value(rounding='ROUND_CEILING'))
        today = today or timezone.localdate()
        y, m = today.year, today.month + months
        while m > 12:
            m -= 12
            y += 1
        return date(y, m, min(today.day, calendar.monthrange(y, m)[1]))

    def check_done(self, today: Optional[date] = None) -> bool:
        if self.status == self.ACTIVE and self.current_amount(today) >= self.target_amount:
            self.status = self.DONE
            self.save(update_fields=['status', 'updated_at'])
            return True
        return False
