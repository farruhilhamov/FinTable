from django import forms

from .models import Deposit


class DepositForm(forms.ModelForm):
    class Meta:
        model = Deposit
        fields = [
            'name', 'account', 'principal_amount', 'annual_rate',
            'start_date', 'end_date', 'capitalization_type', 'auto_close',
        ]
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'end_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
        }

    def clean(self):
        cleaned = super().clean()
        s, e = cleaned.get('start_date'), cleaned.get('end_date')
        if s and e and e <= s:
            raise forms.ValidationError('Дата окончания должна быть позже даты начала')
        return cleaned

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        if user is not None:
            from finance.models import Account
            self.fields['account'].queryset = Account.objects.filter(user=user, is_active=True)
