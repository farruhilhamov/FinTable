from decimal import Decimal
from typing import Optional

from django.conf import settings
import calendar
from datetime import date

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
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
    is_transfer = models.BooleanField(
        'Техническая категория переводов', default=False,
        help_text='Операции с этой категорией не учитываются в доходах/расходах и P&L.',
    )

    TRANSFER_NAME = 'Перевод между счетами'

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

    @classmethod
    def get_or_create_system(cls, user, name: str, ctype: str):
        """Категория пользователя по имени/типу; создаётся при отсутствии (для авто-операций)."""
        cat, _ = cls.objects.get_or_create(user=user, name=name, type=ctype, defaults={'is_active': True})
        if not cat.is_active:
            cat.is_active = True
            cat.save(update_fields=['is_active', 'updated_at'])
        return cat

    @classmethod
    def transfer_pair(cls, user):
        """Технические категории «Перевод между счетами» (расход/доход) пользователя."""
        out = {}
        for ctype in (cls.EXPENSE, cls.INCOME):
            cat, _ = cls.objects.get_or_create(
                user=user, name=cls.TRANSFER_NAME, type=ctype,
                defaults={'is_transfer': True, 'is_active': True},
            )
            if not cat.is_transfer:
                cat.is_transfer = True
                cat.save(update_fields=['is_transfer', 'updated_at'])
            out[ctype] = cat
        return out


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
    recurring_template = models.ForeignKey(
        'RecurringTemplate', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='transactions', verbose_name='Регулярный шаблон',
    )
    tags = models.CharField(
        'Теги', max_length=255, blank=True,
        help_text='Через запятую: такси, работа, отпуск',
    )
    receipt = models.ImageField('Чек', upload_to='receipts/%Y/%m/', blank=True, null=True)
    transfer_pair = models.OneToOneField(
        'self', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='transfer_counterpart', verbose_name='Парная операция перевода',
    )

    class Meta:
        ordering = ['-date', '-created_at']
        constraints = [
            # Один шаблон создаёт не более одной операции на дату (защита от дублей).
            models.UniqueConstraint(
                fields=['recurring_template', 'date'],
                condition=Q(recurring_template__isnull=False),
                name='unique_recurring_transaction_per_date',
            ),
        ]

    def __str__(self):
        return f'{self.date} {self.get_type_display()} {self.amount}'

    @property
    def is_transfer(self) -> bool:
        return self.transfer_pair_id is not None or bool(
            self.category_id and self.category.is_transfer
        )

    @property
    def tag_list(self):
        return [t.strip() for t in (self.tags or '').split(',') if t.strip()]

    def clean(self):
        super().clean()
        if self.category_id and self.category.type != self.type:
            raise ValidationError({'type': 'Тип транзакции должен совпадать с типом категории'})
        if self.tags:
            self.tags = ', '.join(dict.fromkeys(self.tag_list))

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
    day_of_month = models.PositiveSmallIntegerField(
        'День месяца', default=1,
        validators=[MinValueValidator(1), MaxValueValidator(31)],
        help_text='1–31. Если в месяце меньше дней — операция создаётся в последний день месяца.',
    )
    start_date = models.DateField(
        'Действует с', default=timezone.localdate,
        help_text='Первая операция будет создана не раньше этой даты.',
    )
    description = models.CharField('Описание', max_length=255, blank=True)
    is_active = models.BooleanField('Активен', default=True)
    last_run = models.DateField('Последний запуск', null=True, blank=True)

    class Meta:
        ordering = ['day_of_month']

    def __str__(self):
        return f'{self.get_type_display()} {self.amount} каждый {self.day_of_month}-й день'

    # ---- валидация ----

    def clean(self):
        super().clean()
        errors = {}
        if self.category_id and self.category.type != self.type:
            errors['type'] = 'Тип операции должен совпадать с типом категории'
        if self.category_id and self.user_id and self.category.user_id != self.user_id:
            errors['category'] = 'Категория принадлежит другому пользователю'
        if self.account_id and self.user_id and self.account.user_id != self.user_id:
            errors['account'] = 'Счёт принадлежит другому пользователю'
        if errors:
            raise ValidationError(errors)

    # ---- расчёт дат ----

    def run_day_in_month(self, year: int, month: int) -> date:
        """Дата срабатывания в указанном месяце: day_of_month или последний день месяца."""
        last = calendar.monthrange(year, month)[1]
        return date(year, month, min(self.day_of_month, last))

    def due_dates(self, date_to: date):
        """Все даты, на которые шаблон должен был сработать, но ещё не сработал, по date_to включительно.

        Точка отсчёта — день после last_run, но не раньше start_date.
        """
        if not self.is_active:
            return []
        anchor = self.start_date or date_to
        if self.last_run is not None:
            anchor = max(anchor, self.last_run + timezone.timedelta(days=1))
        if anchor > date_to:
            return []
        result = []
        y, m = anchor.year, anchor.month
        while True:
            d = self.run_day_in_month(y, m)
            if d > date_to:
                break
            if d >= anchor:
                result.append(d)
            m += 1
            if m > 12:
                m, y = 1, y + 1
        return result

    def next_run_date(self, today: date = None) -> Optional[date]:
        """Ближайшая будущая (или сегодняшняя) дата срабатывания; None если шаблон неактивен."""
        if not self.is_active:
            return None
        today = today or timezone.localdate()
        anchor = max(self.start_date or today, today)
        if self.last_run is not None and self.last_run >= anchor:
            anchor = self.last_run + timezone.timedelta(days=1)
        y, m = anchor.year, anchor.month
        for _ in range(3):
            d = self.run_day_in_month(y, m)
            if d >= anchor:
                return d
            m += 1
            if m > 12:
                m, y = 1, y + 1
        return None

    @property
    def is_overdue(self) -> bool:
        """Есть ли пропущенные (не созданные) операции на сегодня."""
        return bool(self.due_dates(timezone.localdate()))


class Budget(TimeStampedModel):
    """Месячный лимит расходов по категории (действует каждый месяц, пока активен)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='budgets'
    )
    category = models.ForeignKey(
        Category, on_delete=models.PROTECT, related_name='budgets',
        limit_choices_to={'type': Category.EXPENSE},
    )
    limit = models.DecimalField(
        'Лимит в месяц', max_digits=18, decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
    )
    is_active = models.BooleanField('Активен', default=True)

    class Meta:
        ordering = ['category__name']
        constraints = [
            models.UniqueConstraint(fields=['user', 'category'], name='unique_budget_per_category'),
        ]

    def __str__(self):
        return f'{self.category.name}: {self.limit} / мес'

    def clean(self):
        super().clean()
        if self.category_id and self.category.type != Category.EXPENSE:
            raise ValidationError({'category': 'Бюджет задаётся только для категорий расходов'})
        if self.category_id and self.user_id and self.category.user_id != self.user_id:
            raise ValidationError({'category': 'Категория принадлежит другому пользователю'})

    def spent(self, date_from: date, date_to: date) -> Decimal:
        agg = Transaction.objects.filter(
            user_id=self.user_id, category_id=self.category_id, type=Transaction.EXPENSE,
            date__gte=date_from, date__lte=date_to,
        ).aggregate(total=Sum('amount', default=Decimal('0')))
        return agg['total'] or Decimal('0')
