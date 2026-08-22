from django import forms

from .models import Security, SecurityValuation


class SecurityForm(forms.ModelForm):
    class Meta:
        model = Security
        fields = ['name', 'acquisition_value', 'quantity_or_share', 'acquisition_date']
        widgets = {
            'acquisition_date': forms.DateInput(attrs={'type': 'date'}),
        }


class SecurityValuationForm(forms.ModelForm):
    class Meta:
        model = SecurityValuation
        fields = ['value', 'date']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
        }
