from django import forms

from deposits.models import Deposit
from finance.models import Account
from .models import Goal


class GoalForm(forms.ModelForm):
    class Meta:
        model = Goal
        fields = ['name', 'target_amount', 'deadline', 'account', 'deposit', 'saved_manual', 'note']
        widgets = {'deadline': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        if user is not None:
            self.fields['account'].queryset = Account.objects.filter(user=user, is_active=True)
            self.fields['deposit'].queryset = Deposit.objects.filter(user=user, status=Deposit.ACTIVE)
        self.fields['target_amount'].widget.attrs.update({'inputmode': 'decimal'})

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.user:
            instance.user = self.user
        if commit:
            instance.save()
            instance.check_done()
        return instance


class GoalTopUpForm(forms.Form):
    amount = forms.DecimalField(label='Добавить к накоплению', max_digits=18, decimal_places=2)
