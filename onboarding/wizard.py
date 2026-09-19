"""
Wizard первичного заполнения профиля на django-formtools
(NamedUrlSessionWizardView).

5 шагов с сохранением состояния в сессии; запись в БД — только на финальном шаге
в единой атомарной транзакции (или при частичном сохранении через «Отменить и
сохранить, что уже ввёл»).
"""
from datetime import date
from decimal import Decimal

from django.contrib import messages
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from formtools.wizard.views import NamedUrlSessionWizardView

from accounts.models import User
from deposits.models import Deposit
from finance.models import Account, Category, RecurringTemplate, Transaction
from securities.models import Security, SecurityValuation

from .forms import (
    AccountFormSet, DepositFormSet, SecurityFormSet, SalaryForm, WelcomeForm,
)
from .models import UserProfile

WIZARD_STEPS = ['1', '2', '3', '4', '5']
STEP_TITLES = {
    '1': 'Приветствие',
    '2': 'Счета',
    '3': 'Вклады',
    '4': 'Доли / ценные бумаги',
    '5': 'Доход (зарплата)',
}


class OnboardingWizard(NamedUrlSessionWizardView):
    url_name = 'wizard'
    form_list = [
        ('1', WelcomeForm),
        ('2', AccountFormSet),
        ('3', DepositFormSet),
        ('4', SecurityFormSet),
        ('5', SalaryForm),
    ]

    template_name = 'onboarding/wizard.html'

    def get_context_data(self, form, **kwargs):
        ctx = super().get_context_data(form=form, **kwargs)
        ctx['step_titles'] = STEP_TITLES
        ctx['steps'] = self.steps
        ctx['step_index'] = WIZARD_STEPS.index(self.steps.current) + 1
        ctx['total_steps'] = len(WIZARD_STEPS)
        ctx['is_welcome'] = self.steps.current == '1'
        ctx['is_last'] = self.steps.current == self.steps.last
        ctx['progress_pct'] = int(ctx['step_index'] / len(WIZARD_STEPS) * 100)
        return ctx

    # --- перехват кастомных кнопок управления ---

    def post(self, *args, **kwargs):
        action = self.request.POST.get('wizard_action')
        if action == 'skip':
            return self._do_skip()
        if action == 'cancel_delete':
            self.storage.reset()
            messages.info(self.request, 'Мастер отменён. Введённые данные удалены.')
            return redirect('dashboard')
        if action == 'cancel_save':
            return self._do_partial_save()
        return super().post(*args, **kwargs)

    def _do_skip(self):
        profile, _ = UserProfile.objects.get_or_create(user=self.request.user)
        profile.onboarding_completed = True
        profile.onboarding_skipped = True
        profile.save(update_fields=['onboarding_completed', 'onboarding_skipped'])
        self.storage.reset()
        messages.info(self.request, 'Мастер пропущен. Профиль можно заполнить позже.')
        return redirect('dashboard')

    def _do_partial_save(self):
        """Частичная запись по уже пройденным шагам, onboarding_completed=False."""
        created = self._persist_wizard_data(final=False)
        messages.success(
            self.request,
            f'Сохранено записей: {created}. Настройку можно продолжить позже.'
        )
        self.storage.reset()
        return redirect('dashboard')

    # --- финальный шаг ---

    def done(self, form_list, **kwargs):
        created = self._persist_wizard_data(final=True)
        messages.success(
            self.request,
            f'Профиль заполнен. Добавлено записей: {created}.'
        )
        return redirect('dashboard')

    # --- единая точка записи в БД ---

    @transaction.atomic
    def _persist_wizard_data(self, final: bool) -> int:
        """Создаёт реальные записи из данных сессии wizard.

        При final=True выставляет onboarding_completed=True.
        При final=False (частичное сохранение) — оставляет флаг False.
        Возвращает количество созданных записей.
        """
        user = self.request.user
        count = 0

        # Шаг 2 — счета (с остатком через стартовую транзакцию)
        accounts_data = self._step_formset('2', AccountFormSet)
        for item in accounts_data:
            name = item.get('name')
            if not name:
                continue
            account = Account.objects.create(
                user=user, name=name, type=item.get('type', Account.CASH),
            )
            balance = item.get('balance') or Decimal('0')
            if balance > 0:
                # создаём начальную транзакцию-пополнение, чтобы баланс сошёлся
                cat = Category.objects.filter(user=user, name='Пополнение', type=Category.INCOME).first()
                if cat is None:
                    cat = Category.objects.filter(user=user, type=Category.INCOME).first()
                if cat is not None:
                    Transaction.objects.create(
                        user=user, account=account, category=cat,
                        amount=balance, type=Transaction.INCOME,
                        date=date.today(), description='Стартовый остаток (wizard)',
                    )
            count += 1

        # Шаг 3 — вклады
        deposits_data = self._step_formset('3', DepositFormSet)
        for item in deposits_data:
            name = item.get('name')
            if not name:
                continue
            Deposit.objects.create(
                user=user, name=name,
                principal_amount=item['principal_amount'],
                annual_rate=item['annual_rate'],
                start_date=item['start_date'],
                capitalization_type=item.get('capitalization_type', Deposit.SIMPLE),
            )
            count += 1

        # Шаг 4 — бумаги + первая переоценка
        securities_data = self._step_formset('4', SecurityFormSet)
        for item in securities_data:
            name = item.get('name')
            if not name:
                continue
            sec = Security.objects.create(
                user=user, name=name,
                acquisition_value=item['acquisition_value'],
            )
            cv = item.get('current_value')
            if cv is None:
                cv = item['acquisition_value']
            SecurityValuation.objects.create(security=sec, value=cv, date=date.today())
            count += 1

        # Шаг 5 — зарплата (только при финальном завершении и включённом чекбоксе)
        if final:
            salary_data = self._step_form('5', SalaryForm)
            if salary_data.get('create_recurring') and salary_data.get('amount'):
                cat = Category.objects.filter(user=user, name='Зарплата', type=Category.INCOME).first()
                if cat is None:
                    cat = Category.objects.filter(user=user, type=Category.INCOME).first()
                acct = Account.objects.filter(user=user, is_active=True).first()
                if cat is not None and acct is not None:
                    tmpl = RecurringTemplate(
                        user=user, category=cat, account=acct,
                        amount=salary_data['amount'], type=Transaction.INCOME,
                        day_of_month=salary_data.get('day_of_month') or 5,
                        description='Зарплата (wizard)',
                    )
                    tmpl.full_clean()
                    tmpl.save()
                    count += 1

            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.onboarding_completed = True
            profile.onboarding_skipped = False
            profile.save(update_fields=['onboarding_completed', 'onboarding_skipped'])

        return count

    # --- утилиты извлечения данных форм из хранилища wizard ---

    def _step_raw_data(self, step):
        """Возвращает dict-like данных шага или None."""
        return self.storage.get_step_data(step)

    def _step_formset(self, step, formset_class):
        data = self._step_raw_data(step)
        if not data:
            return []
        prefix = self.get_form_prefix(step, formset_class)
        fs = formset_class(data=data, prefix=prefix)
        if not fs.is_valid():
            return []
        cleaned = []
        for f in fs.forms:
            cd = f.cleaned_data or {}
            if cd:
                cleaned.append(cd)
        return cleaned

    def _step_form(self, step, form_class):
        data = self._step_raw_data(step)
        if not data:
            return {}
        prefix = self.get_form_prefix(step, form_class)
        form = form_class(data=data, prefix=prefix)
        if not form.is_valid():
            return {}
        return form.cleaned_data
