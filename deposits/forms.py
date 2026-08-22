from django import forms

from .models import Deposit


class DepositForm(forms.ModelForm):
    class Meta:
        model = Deposit
        fields = [
            'name', 'account', 'principal_amount', 'annual_rate',
            'start_date', 'capitalization_type',
        ]
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        if user is not None:
            from finance.models import Account
            self.fields['account'].queryset = Account.objects.filter(user=user, is_active=True)
