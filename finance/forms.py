from decimal import Decimal

from django import forms

from django.utils import timezone

from .models import Account, Budget, Category, Transaction, RecurringTemplate


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
        fields = ['account', 'category', 'amount', 'type', 'date', 'description', 'tags', 'receipt']
        widgets = {'date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        if user is not None:
            self.fields['account'].queryset = Account.objects.filter(user=user, is_active=True)
            self.fields['category'].queryset = Category.objects.filter(
                user=user, is_active=True, is_transfer=False,
            )
        self.fields['category'].label_from_instance = lambda c: f'{c.name} ({c.get_type_display()})'
        self.fields['account'].label_from_instance = lambda a: a.name
        self.fields['amount'].widget.attrs.update({'inputmode': 'decimal', 'autofocus': True})

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
        widgets = {'start_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        if user is not None:
            self.fields['category'].queryset = Category.objects.filter(user=user, is_active=True, is_transfer=False)
            self.fields['account'].queryset = Account.objects.filter(user=user, is_active=True)
        self.fields['category'].label_from_instance = lambda c: f'{c.name} ({c.get_type_display()})'
        self.fields['account'].label_from_instance = lambda a: a.name
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


class TransferForm(forms.Form):
    """Перевод между двумя счетами пользователя: создаёт пару связанных операций."""

    from_account = forms.ModelChoiceField(label='Со счёта', queryset=Account.objects.none())
    to_account = forms.ModelChoiceField(label='На счёт', queryset=Account.objects.none())
    amount = forms.DecimalField(label='Сумма', min_value=Decimal('0.01'), max_digits=18, decimal_places=2)
    date = forms.DateField(label='Дата', initial=timezone.localdate,
                           widget=forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'))
    description = forms.CharField(label='Описание', max_length=255, required=False)

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        qs = Account.objects.filter(user=user, is_active=True) if user is not None else Account.objects.none()
        self.fields['from_account'].queryset = qs
        self.fields['to_account'].queryset = qs

    def clean(self):
        cleaned = super().clean()
        a, b = cleaned.get('from_account'), cleaned.get('to_account')
        if a and b and a.pk == b.pk:
            raise forms.ValidationError('Счёт списания и счёт зачисления должны отличаться')
        return cleaned

    def save(self):
        from django.db import transaction as db_tx
        cats = Category.transfer_pair(self.user)
        d = self.cleaned_data
        desc = d.get('description') or f'Перевод: {d["from_account"].name} → {d["to_account"].name}'
        with db_tx.atomic():
            out = Transaction.objects.create(
                user=self.user, account=d['from_account'], category=cats[Category.EXPENSE],
                amount=d['amount'], type=Transaction.EXPENSE, date=d['date'], description=desc,
            )
            inc = Transaction.objects.create(
                user=self.user, account=d['to_account'], category=cats[Category.INCOME],
                amount=d['amount'], type=Transaction.INCOME, date=d['date'], description=desc,
                transfer_pair=out,
            )
            out.transfer_pair = inc
            out.save(update_fields=['transfer_pair', 'updated_at'])
        return out, inc


class BudgetForm(forms.ModelForm):
    class Meta:
        model = Budget
        fields = ['category', 'limit', 'is_active']

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        if user is not None:
            self.fields['category'].queryset = Category.objects.filter(
                user=user, is_active=True, type=Category.EXPENSE, is_transfer=False,
            )
        self.fields['category'].label_from_instance = lambda c: c.name
        self.fields['limit'].widget.attrs.update({'inputmode': 'decimal'})

    def clean_category(self):
        cat = self.cleaned_data['category']
        qs = Budget.objects.filter(user=self.user, category=cat)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError('Для этой категории бюджет уже задан')
        return cat

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.user:
            instance.user = self.user
        if commit:
            instance.save()
        return instance
