from django import forms

from .models import Account, Category, Transaction, RecurringTemplate


class AccountForm(forms.ModelForm):
    class Meta:
        model = Account
        fields = ['name', 'type', 'is_active']


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ['name', 'type', 'is_active']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Тип категории нельзя менять для существующих системных категорий
        if self.instance and self.instance.pk:
            self.fields['type'].disabled = True


class TransactionForm(forms.ModelForm):
    class Meta:
        model = Transaction
        fields = ['account', 'category', 'amount', 'type', 'date', 'description']

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        if user is not None:
            self.fields['account'].queryset = Account.objects.filter(user=user, is_active=True)
            self.fields['category'].queryset = Category.objects.filter(
                user=user, is_active=True
            )

    def clean(self):
        cleaned = super().clean()
        cat = cleaned.get('category')
        ttype = cleaned.get('type')
        if cat and ttype and cat.type != ttype:
            raise forms.ValidationError(
                f'Тип транзакции ({ttype}) должен совпадать с типом категории ({cat.type})'
            )
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.user:
            instance.user = self.user
        if commit:
            instance.save()
        return instance


class RecurringTemplateForm(forms.ModelForm):
    class Meta:
        model = RecurringTemplate
        fields = ['category', 'account', 'amount', 'type', 'day_of_month', 'start_date',
                  'description', 'is_active']
        widgets = {'start_date': forms.DateInput(attrs={'type': 'date'})}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        if user is not None:
            self.fields['category'].queryset = Category.objects.filter(user=user, is_active=True)
            self.fields['account'].queryset = Account.objects.filter(user=user, is_active=True)
        if self.instance and self.instance.pk and self.instance.last_run:
            self.fields['start_date'].help_text = (
                f'Последний запуск: {self.instance.last_run:%d.%m.%Y}. '
                'Изменение даты начала не пересоздаёт уже созданные операции.'
            )

    def clean(self):
        cleaned = super().clean()
        cat = cleaned.get('category')
        ttype = cleaned.get('type')
        if cat and ttype and cat.type != ttype:
            raise forms.ValidationError('Тип операции должен совпадать с типом категории')
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.user:
            instance.user = self.user
        if commit:
            instance.save()
        return instance
