from datetime import date
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from finance.models import TimeStampedModel


class Deposit(TimeStampedModel):
    SIMPLE = 'simple'
    MONTHLY_COMPOUND = 'monthly_compound'
    CAP_TYPE_CHOICES = [
        (SIMPLE, 'Простой процент'),
        (MONTHLY_COMPOUND, 'Ежемесячная капитализация'),
    ]

    ACTIVE = 'active'
    CLOSED = 'closed'
    STATUS_CHOICES = [
        (ACTIVE, 'Активен'),
        (CLOSED, 'Закрыт'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='deposits'
    )
    name = models.CharField('Название', max_length=120)
    account = models.ForeignKey(
        'finance.Account', on_delete=models.SET_NULL, related_name='deposits',
        null=True, blank=True,
    )
    principal_amount = models.DecimalField(
        'Тело вклада', max_digits=18, decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
    )
    annual_rate = models.DecimalField(
        'Годовая ставка, %', max_digits=6, decimal_places=2,
        validators=[MinValueValidator(Decimal('0'))],
    )
    start_date = models.DateField('Дата начала', default=timezone.now)
    capitalization_type = models.CharField(
        'Тип капитализации', max_length=20, choices=CAP_TYPE_CHOICES, default=SIMPLE
    )
    status = models.CharField('Статус', max_length=10, choices=STATUS_CHOICES, default=ACTIVE)
    closed_date = models.DateField('Дата закрытия', null=True, blank=True)

    class Meta:
        ordering = ['-start_date']

    def __str__(self):
        return f'{self.name} ({self.principal_amount} @ {self.annual_rate}%)'

    def _days_elapsed(self, as_of_date=None):
        end = as_of_date or date.today()
        start = self.start_date
        if self.closed_date and (as_of_date is None or self.closed_date < end):
            end = self.closed_date
        return max((end - start).days, 0)

    def _months_elapsed(self, as_of_date=None):
        end = as_of_date or date.today()
        if self.closed_date and (as_of_date is None or self.closed_date < end):
            end = self.closed_date
        months = (end.year - self.start_date.year) * 12 + (end.month - self.start_date.month)
        if end.day < self.start_date.day:
            months -= 1
        return max(months, 0)

    def get_accrued_income(self, as_of_date=None):
        """Накопленный доход по вкладу на указанную дату."""
        if self.status == self.CLOSED and as_of_date is None:
            end = self.closed_date or date.today()
        else:
            end = as_of_date or date.today()

        if self.start_date > end:
            return Decimal('0')

        if self.capitalization_type == self.SIMPLE:
            days = max((end - self.start_date).days, 0)
            return (
                self.principal_amount
                * (self.annual_rate / Decimal('100'))
                * Decimal(days)
                / Decimal('365')
            ).quantize(Decimal('0.01'))

        months = (end.year - self.start_date.year) * 12 + (end.month - self.start_date.month)
        if end.day < self.start_date.day:
            months -= 1
        months = max(months, 0)
        factor = (Decimal('1') + self.annual_rate / Decimal('100') / Decimal('12')) ** months
        return (self.principal_amount * factor - self.principal_amount).quantize(Decimal('0.01'))

    @property
    def current_balance(self):
        return self.principal_amount + self.get_accrued_income()

    def close(self, closed_date=None):
        self.status = self.CLOSED
        self.closed_date = closed_date or timezone.now().date()
        self.save(update_fields=['status', 'closed_date', 'updated_at'])
