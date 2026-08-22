from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from finance.models import TimeStampedModel


class Security(TimeStampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='securities'
    )
    name = models.CharField('Название', max_length=120)
    acquisition_value = models.DecimalField(
        'Стоимость приобретения', max_digits=18, decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
    )
    quantity_or_share = models.DecimalField(
        'Количество / доля', max_digits=18, decimal_places=4,
        null=True, blank=True,
    )
    acquisition_date = models.DateField('Дата приобретения', default=timezone.now)

    class Meta:
        ordering = ['-acquisition_date']

    def __str__(self):
        return f'{self.name} ({self.acquisition_value})'

    def current_valuation(self, as_of_date=None):
        """Последняя переоценка на дату (или None, если переоценок нет)."""
        qs = self.valuations.all()
        if as_of_date is not None:
            qs = qs.filter(date__lte=as_of_date)
        last = qs.order_by('-date', '-created_at').first()
        return last.value if last else Decimal('0')

    def current_value(self, as_of_date=None):
        """Текущая стоимость (последняя оценка либо стоимость приобретения)."""
        val = self.current_valuation(as_of_date)
        if val:
            return val
        return self.acquisition_value

    def pnl(self, as_of_date=None):
        """P&L = текущая оценка − стоимость приобретения."""
        return self.current_value(as_of_date) - self.acquisition_value


class SecurityValuation(TimeStampedModel):
    security = models.ForeignKey(
        Security, on_delete=models.CASCADE, related_name='valuations'
    )
    value = models.DecimalField(
        'Оценка', max_digits=18, decimal_places=2,
        validators=[MinValueValidator(Decimal('0'))],
    )
    date = models.DateField('Дата оценки', default=timezone.now)

    class Meta:
        ordering = ['-date', '-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['security', 'date'], name='unique_valuation_per_security_date',
            ),
        ]

    def __str__(self):
        return f'{self.security.name} @ {self.date}: {self.value}'
