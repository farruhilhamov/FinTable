from decimal import Decimal

from django import forms
from django.utils import timezone

from finance.models import Account
from .models import Liability


class LiabilityForm(forms.ModelForm):
    create_recurring = forms.BooleanField(
        label='Создать регулярный платёж', required=False, initial=True,
        help_text='Если заданы ежемесячный платёж, день и счёт — операция будет создаваться автоматически и уменьшать остаток.',
    )

    class Meta:
        model = Liability
        fields = [
            'name', 'kind', 'direction', 'counterparty', 'principal', 'balance', 'annual_rate',
            'monthly_payment', 'payment_day', 'account', 'start_date', 'due_date', 'note',
        ]
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'due_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        if user is not None:
            self.fields['account'].queryset = Account.objects.filter(user=user, is_active=True)
        self.fields['balance'].required = False
        self.fields['balance'].help_text = 'Пусто — равен начальной сумме.'
        if self.instance.pk and self.instance.recurring_template_id:
            self.fields['create_recurring'].initial = self.instance.recurring_template.is_active

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('balance') in (None, ''):
            cleaned['balance'] = cleaned.get('principal')
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.user:
            instance.user = self.user
        if instance.balance is None:
            instance.balance = instance.principal
        if commit:
            instance.save()
            if self.cleaned_data.get('create_recurring'):
                instance.ensure_recurring()
            elif instance.recurring_template_id:
                from finance.models import RecurringTemplate
                RecurringTemplate.objects.filter(pk=instance.recurring_template_id).update(is_active=False)
        return instance


class PaymentForm(forms.Form):
    amount = forms.DecimalField(label='Сумма', min_value=Decimal('0.01'), max_digits=18, decimal_places=2)
    date = forms.DateField(label='Дата', initial=timezone.localdate,
                           widget=forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'))
    account = forms.ModelChoiceField(label='Счёт', queryset=Account.objects.none(), required=False)
    description = forms.CharField(label='Описание', max_length=255, required=False)
    create_transaction = forms.BooleanField(label='Создать операцию по счёту', required=False, initial=True)

    def __init__(self, *args, user=None, liability=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['account'].queryset = Account.objects.filter(user=user, is_active=True)
        if liability is not None:
            self.fields['amount'].initial = liability.monthly_payment or liability.balance
            self.fields['account'].initial = liability.account_id
