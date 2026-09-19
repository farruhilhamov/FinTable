"""Обязательства: кредиты, рассрочки, займы у людей и долги вам.

Учитываются в Net Worth со знаком минус (direction=owe) или плюс (direction=owed).
Платёж уменьшает остаток и создаёт транзакцию расхода (для owe) / дохода (для owed).
"""
from datetime import date
from decimal import Decimal
from typing import Optional

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from finance.models import TimeStampedModel


class Liability(TimeStampedModel):
    LOAN = 'loan'
    INSTALLMENT = 'installment'
    CREDIT_CARD = 'credit_card'
    PERSONAL = 'personal'
    OTHER = 'other'
    KIND_CHOICES = [
        (LOAN, 'Кредит'),
        (INSTALLMENT, 'Рассрочка'),
        (CREDIT_CARD, 'Кредитная карта'),
        (PERSONAL, 'Займ у человека / человеку'),
        (OTHER, 'Другое'),
    ]

    OWE = 'owe'      # я должен
    OWED = 'owed'    # мне должны
    DIRECTION_CHOICES = [
        (OWE, 'Я должен'),
        (OWED, 'Мне должны'),
    ]

    ACTIVE = 'active'
    CLOSED = 'closed'
    STATUS_CHOICES = [(ACTIVE, 'Активен'), (CLOSED, 'Погашен')]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='liabilities'
    )
    name = models.CharField('Название', max_length=120)
    kind = models.CharField('Тип', max_length=20, choices=KIND_CHOICES, default=LOAN)
    direction = models.CharField('Направление', max_length=5, choices=DIRECTION_CHOICES, default=OWE)
    counterparty = models.CharField('Контрагент (банк / человек)', max_length=120, blank=True)
    principal = models.DecimalField(
        'Начальная сумма', max_digits=18, decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
    )
    balance = models.DecimalField(
        'Текущий остаток', max_digits=18, decimal_places=2,
        validators=[MinValueValidator(Decimal('0'))],
    )
    annual_rate = models.DecimalField(
        'Ставка, % годовых', max_digits=6, decimal_places=2, default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0'))],
    )
    monthly_payment = models.DecimalField(
        'Ежемесячный платёж', max_digits=18, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal('0.01'))],
    )
    payment_day = models.PositiveSmallIntegerField(
        'День платежа', null=True, blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(31)],
    )
    account = models.ForeignKey(
        'finance.Account', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='liabilities', verbose_name='Счёт для платежей',
    )
    start_date = models.DateField('Дата открытия', default=timezone.localdate)
    due_date = models.DateField('Срок погашения', null=True, blank=True)
    status = models.CharField('Статус', max_length=10, choices=STATUS_CHOICES, default=ACTIVE)
    closed_date = models.DateField('Дата погашения', null=True, blank=True)
    recurring_template = models.OneToOneField(
        'finance.RecurringTemplate', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='liability', verbose_name='Регулярный платёж',
    )
    note = models.CharField('Заметка', max_length=255, blank=True)

    class Meta:
        ordering = ['status', '-balance']
        verbose_name = 'Обязательство'
        verbose_name_plural = 'Обязательства'

    def __str__(self):
        return f'{self.name} ({self.get_direction_display()}, остаток {self.balance})'

    def clean(self):
        super().clean()
        if self.balance is not None and self.principal is not None and self.balance > self.principal:
            raise ValidationError({'balance': 'Остаток не может превышать начальную сумму'})
        if self.due_date and self.start_date and self.due_date < self.start_date:
            raise ValidationError({'due_date': 'Срок погашения раньше даты открытия'})
        if self.account_id and self.user_id and self.account.user_id != self.user_id:
            raise ValidationError({'account': 'Счёт принадлежит другому пользователю'})

    # ---- расчёты ----

    @property
    def paid(self) -> Decimal:
        return (self.principal or Decimal('0')) - (self.balance or Decimal('0'))

    @property
    def progress_pct(self) -> int:
        if not self.principal:
            return 0
        return int(min(self.paid / self.principal * 100, Decimal('100')))

    @property
    def signed_balance(self) -> Decimal:
        """Вклад в Net Worth: долг — минус, дебиторка — плюс."""
        if self.status != self.ACTIVE:
            return Decimal('0')
        return -self.balance if self.direction == self.OWE else self.balance

    def months_left(self, today: date = None) -> Optional[int]:
        """Сколько месяцев осталось при текущем ежемесячном платеже (без учёта процентов
        если ставка 0, иначе — аннуитетная оценка)."""
        if not self.monthly_payment or self.balance <= 0:
            return None
        pay = Decimal(self.monthly_payment)
        r = Decimal(self.annual_rate) / Decimal('100') / Decimal('12')
        bal = Decimal(self.balance)
        if r == 0:
            return int((bal / pay).to_integral_value(rounding='ROUND_CEILING'))
        if pay <= bal * r:
            return None  # платёж не покрывает проценты
        import math
        n = -math.log(1 - float(bal * r / pay)) / math.log(1 + float(r))
        return int(math.ceil(n))

    def days_to_due(self, today: date = None) -> Optional[int]:
        if not self.due_date:
            return None
        today = today or timezone.localdate()
        return (self.due_date - today).days

    # ---- операции ----

    def apply_payment(self, amount: Decimal, pay_date: date = None, account=None,
                      description: str = '', create_transaction: bool = True):
        """Погашение: уменьшает остаток, создаёт транзакцию, закрывает при нуле."""
        from django.db import transaction as db_tx
        from finance.models import Category, Transaction

        amount = Decimal(amount)
        if amount <= 0:
            raise ValidationError('Сумма платежа должна быть больше нуля')
        pay_date = pay_date or timezone.localdate()
        account = account or self.account
        with db_tx.atomic():
            applied = min(amount, self.balance)
            self.balance = self.balance - applied
            if self.balance <= 0:
                self.balance = Decimal('0')
                self.status = self.CLOSED
                self.closed_date = pay_date
            self.save(update_fields=['balance', 'status', 'closed_date', 'updated_at'])

            tx = None
            if create_transaction and account is not None:
                if self.direction == self.OWE:
                    ttype = Transaction.EXPENSE
                    cat = Category.get_or_create_system(self.user, 'Погашение долгов', Category.EXPENSE)
                else:
                    ttype = Transaction.INCOME
                    cat = Category.get_or_create_system(self.user, 'Возврат долгов', Category.INCOME)
                tx = Transaction.objects.create(
                    user=self.user, account=account, category=cat, amount=amount, type=ttype,
                    date=pay_date, description=description or f'{self.get_kind_display()}: {self.name}',
                )
            return tx

    def ensure_recurring(self):
        """Создать/обновить регулярный шаблон ежемесячного платежа (если заданы день и сумма)."""
        from finance.models import Category, RecurringTemplate, Transaction

        if self.status != self.ACTIVE or not self.monthly_payment or not self.payment_day or not self.account_id:
            if self.recurring_template_id:
                RecurringTemplate.objects.filter(pk=self.recurring_template_id).update(is_active=False)
            return None
        if self.direction == self.OWE:
            ttype = Transaction.EXPENSE
            cat = Category.get_or_create_system(self.user, 'Погашение долгов', Category.EXPENSE)
        else:
            ttype = Transaction.INCOME
            cat = Category.get_or_create_system(self.user, 'Возврат долгов', Category.INCOME)
        tmpl = self.recurring_template
        if tmpl is None:
            tmpl = RecurringTemplate(user=self.user, start_date=max(self.start_date, timezone.localdate()))
        tmpl.category = cat
        tmpl.account = self.account
        tmpl.amount = self.monthly_payment
        tmpl.type = ttype
        tmpl.day_of_month = self.payment_day
        tmpl.description = f'{self.get_kind_display()}: {self.name}'
        tmpl.is_active = True
        tmpl.save()
        if self.recurring_template_id != tmpl.pk:
            self.recurring_template = tmpl
            self.save(update_fields=['recurring_template', 'updated_at'])
        return tmpl
