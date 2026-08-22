from datetime import date
from decimal import Decimal

from django import forms
from django.forms import formset_factory

from deposits.models import Deposit
from finance.models import Account, Category, RecurringTemplate, Transaction
from securities.models import Security


class WelcomeForm(forms.Form):
    """Пустая форма для шага приветствия (только подтверждение старта)."""
    pass


class AccountItemForm(forms.Form):
    name = forms.CharField(label='Название', max_length=120, required=False)
    type = forms.ChoiceField(label='Тип', choices=Account.TYPE_CHOICES, initial=Account.CASH, required=False)
    balance = forms.DecimalField(
        label='Текущий остаток (UZS)', min_value=Decimal('0'),
        max_digits=18, decimal_places=2, required=False,
    )

    def clean(self):
        cleaned = super().clean()
        # Строка считается пустой, если не заполнено название
        if not cleaned.get('name'):
            return {}
        return cleaned


AccountFormSet = formset_factory(AccountItemForm, extra=2, can_delete=False)


class DepositItemForm(forms.Form):
    name = forms.CharField(label='Название', max_length=120, required=False)
    principal_amount = forms.DecimalField(
        label='Тело вклада (UZS)', min_value=Decimal('0.01'),
        max_digits=18, decimal_places=2, required=False,
    )
    annual_rate = forms.DecimalField(
        label='Годовая ставка, %', min_value=Decimal('0'),
        max_digits=6, decimal_places=2, required=False,
    )
    start_date = forms.DateField(
        label='Дата открытия', widget=forms.DateInput(attrs={'type': 'date'}),
        required=False,
    )
    capitalization_type = forms.ChoiceField(
        label='Капитализация', choices=Deposit.CAP_TYPE_CHOICES,
        initial=Deposit.SIMPLE, required=False,
    )

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get('name'):
            return {}
        # Если указано имя — обязательны сумма, ставка, дата
        for f in ('principal_amount', 'annual_rate', 'start_date'):
            if not cleaned.get(f):
                raise forms.ValidationError(f'Заполните поле «{f}» для вклада «{cleaned.get("name")}»')
        return cleaned


DepositFormSet = formset_factory(DepositItemForm, extra=1, can_delete=False)


class SecurityItemForm(forms.Form):
    name = forms.CharField(label='Название', max_length=120, required=False)
    acquisition_value = forms.DecimalField(
        label='Стоимость приобретения (UZS)', min_value=Decimal('0.01'),
        max_digits=18, decimal_places=2, required=False,
    )
    current_value = forms.DecimalField(
        label='Текущая оценка (UZS)', min_value=Decimal('0'),
        max_digits=18, decimal_places=2, required=False,
    )

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get('name'):
            return {}
        if not cleaned.get('acquisition_value'):
            raise forms.ValidationError('Укажите стоимость приобретения')
        return cleaned


SecurityFormSet = formset_factory(SecurityItemForm, extra=1, can_delete=False)


class SalaryForm(forms.Form):
    amount = forms.DecimalField(
        label='Сумма зарплаты (UZS)', min_value=Decimal('0.01'),
        max_digits=18, decimal_places=2, required=False,
    )
    day_of_month = forms.IntegerField(
        label='День получения', min_value=1, max_value=31, initial=5, required=False,
    )
    create_recurring = forms.BooleanField(
        label='Создавать эту операцию автоматически каждый месяц',
        required=False, initial=True,
    )
