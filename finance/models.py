from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Sum, F, Q
from django.utils import timezone


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Account(TimeStampedModel):
    CARD = 'card'
    CASH = 'cash'
    OTHER = 'other'
    TYPE_CHOICES = [
        (CARD, 'Карта'),
        (CASH, 'Наличные'),
        (OTHER, 'Другое'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='accounts'
    )
    name = models.CharField('Название', max_length=120)
    type = models.CharField('Тип', max_length=10, choices=TYPE_CHOICES, default=CASH)
    is_active = models.BooleanField('Активен', default=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['user', 'name'], name='unique_account_name_per_user'),
        ]

    def __str__(self):
        return f'{self.name} ({self.get_type_display()})'

    def balance(self, as_of_date=None):
        """Расчётный текущий баланс на основе связанных транзакций."""
        qs = self.transactions.all()
        if as_of_date is not None:
            qs = qs.filter(date__lte=as_of_date)
        agg = qs.aggregate(
            income=Sum('amount', filter=Q(type=Transaction.INCOME), default=Decimal('0')),
            expense=Sum('amount', filter=Q(type=Transaction.EXPENSE), default=Decimal('0')),
        )
        return (agg['income'] or Decimal('0')) - (agg['expense'] or Decimal('0'))


class Category(TimeStampedModel):
    INCOME = 'income'
    EXPENSE = 'expense'
    TYPE_CHOICES = [
        (INCOME, 'Доход'),
        (EXPENSE, 'Расход'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='categories',
        null=True,
        blank=True,
    )
    name = models.CharField('Название', max_length=120)
    type = models.CharField('Тип', max_length=10, choices=TYPE_CHOICES)
    is_default = models.BooleanField('Системная по умолчанию', default=False)
    is_active = models.BooleanField('Активна', default=True)

    class Meta:
        ordering = ['type', 'name']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'name', 'type'],
                name='unique_category_name_type_per_user',
            ),
        ]

    def __str__(self):
        owner = self.user.email if self.user else 'система'
        return f'{self.name} ({self.get_type_display()}, {owner})'

    def archive(self):
        self.is_active = False
        self.save(update_fields=['is_active', 'updated_at'])


class Transaction(TimeStampedModel):
    INCOME = 'income'
    EXPENSE = 'expense'
    TYPE_CHOICES = [
        (INCOME, 'Доход'),
        (EXPENSE, 'Расход'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='transactions'
    )
    account = models.ForeignKey(
        Account, on_delete=models.CASCADE, related_name='transactions'
    )
    category = models.ForeignKey(
        Category, on_delete=models.PROTECT, related_name='transactions'
    )
    amount = models.DecimalField(
        'Сумма', max_digits=18, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))]
    )
    type = models.CharField('Тип', max_length=10, choices=TYPE_CHOICES)
    date = models.DateField('Дата', default=timezone.now)
    description = models.CharField('Описание', max_length=255, blank=True)

    class Meta:
        ordering = ['-date', '-created_at']

    def __str__(self):
        return f'{self.date} {self.get_type_display()} {self.amount}'

    def save(self, *args, **kwargs):
        if self.category_id and self.category.type != self.type:
            raise ValueError('Тип транзакции должен совпадать с типом категории')
        super().save(*args, **kwargs)


class RecurringTemplate(TimeStampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='recurring_templates'
    )
    category = models.ForeignKey(
        Category, on_delete=models.PROTECT, related_name='recurring_templates'
    )
    account = models.ForeignKey(
        Account, on_delete=models.CASCADE, related_name='recurring_templates'
    )
    amount = models.DecimalField(
        'Сумма', max_digits=18, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))]
    )
    type = models.CharField('Тип', max_length=10, choices=Transaction.TYPE_CHOICES)
    day_of_month = models.PositiveSmallIntegerField('День месяца', default=1)
    description = models.CharField('Описание', max_length=255, blank=True)
    is_active = models.BooleanField('Активен', default=True)
    last_run = models.DateField('Последний запуск', null=True, blank=True)

    class Meta:
        ordering = ['day_of_month']

    def __str__(self):
        return f'{self.get_type_display()} {self.amount} каждый {self.day_of_month}-й день'
