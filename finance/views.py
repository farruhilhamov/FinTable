from datetime import date
from decimal import Decimal

from django.contrib import messages
from django.db.models import Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import timezone
from django.views.generic import CreateView, DeleteView, ListView, UpdateView, View

from .forms import AccountForm, CategoryForm, RecurringTemplateForm, TransactionForm
from .mixins import OwnerQuerySetMixin
from .services import run_recurring_templates
from .models import Account, Category, RecurringTemplate, Transaction


# ---------- Транзакции ----------

class TransactionListView(OwnerQuerySetMixin, ListView):
    model = Transaction
    template_name = 'finance/transactions.html'
    context_object_name = 'transactions'
    paginate_by = 25

    def get_queryset(self):
        qs = super().get_queryset().select_related('account', 'category')
        get = self.request.GET
        # По умолчанию — текущий месяц (с 1-го числа по сегодня).
        today = date.today()
        default_from = date(today.year, today.month, 1)
        default_to = today
        date_from = get.get('date_from') or default_from.isoformat()
        date_to = get.get('date_to') or default_to.isoformat()
        category = get.get('category')
        account = get.get('account')
        ttype = get.get('type')
        if date_from:
            qs = qs.filter(date__gte=date_from)
        if date_to:
            qs = qs.filter(date__lte=date_to)
        if category:
            qs = qs.filter(category_id=category)
        if account:
            qs = qs.filter(account_id=account)
        if ttype:
            qs = qs.filter(type=ttype)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        today = date.today()
        default_from = date(today.year, today.month, 1).isoformat()
        default_to = today.isoformat()
        ctx['accounts'] = Account.objects.filter(user=self.request.user, is_active=True)
        ctx['categories'] = Category.objects.filter(user=self.request.user, is_active=True)
        ctx['type_choices'] = Transaction.TYPE_CHOICES
        ctx['filters'] = {
            'date_from': self.request.GET.get('date_from', default_from),
            'date_to': self.request.GET.get('date_to', default_to),
            'category': self.request.GET.get('category', ''),
            'account': self.request.GET.get('account', ''),
            'type': self.request.GET.get('type', ''),
        }
        return ctx


class TransactionCreateView(OwnerQuerySetMixin, CreateView):
    model = Transaction
    form_class = TransactionForm
    template_name = 'finance/transaction_form.html'

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw['user'] = self.request.user
        return kw

    def form_valid(self, form):
        form.save()
        messages.success(self.request, 'Транзакция добавлена.')
        if 'HX-Request' in self.request.headers:
            return HttpResponse('', status=204, headers={'HX-Redirect': '/finance/transactions/'})
        return redirect('/finance/transactions/')


class TransactionUpdateView(OwnerQuerySetMixin, UpdateView):
    model = Transaction
    form_class = TransactionForm
    template_name = 'finance/transaction_form.html'

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw['user'] = self.request.user
        return kw

    def get_success_url(self):
        return '/finance/transactions/'


class TransactionDeleteView(OwnerQuerySetMixin, DeleteView):
    model = Transaction
    template_name = 'finance/confirm_delete.html'

    def get_success_url(self):
        return '/finance/transactions/'


# ---------- Счета ----------

class AccountListView(OwnerQuerySetMixin, ListView):
    model = Account
    template_name = 'finance/accounts.html'
    context_object_name = 'accounts'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        for a in ctx['accounts']:
            a.calculated_balance = a.balance()
        return ctx


class AccountCreateView(OwnerQuerySetMixin, CreateView):
    model = Account
    form_class = AccountForm
    template_name = 'finance/account_form.html'

    def form_valid(self, form):
        form.instance.user = self.request.user
        messages.success(self.request, 'Счёт создан.')
        return super().form_valid(form)

    def get_success_url(self):
        return '/finance/accounts/'


class AccountUpdateView(OwnerQuerySetMixin, UpdateView):
    model = Account
    form_class = AccountForm
    template_name = 'finance/account_form.html'

    def get_success_url(self):
        return '/finance/accounts/'


class AccountBalanceView(OwnerQuerySetMixin, View):
    """Прямое изменение текущего баланса счёта.

    Баланс счёта считается из транзакций, поэтому для установки нужной суммы
    создаётся корректирующая транзакция (разница между целевым и текущим
    балансом) с категорией «Пополнение» (при увеличении) или «Прочие расходы»
    (при уменьшении).
    """

    def post(self, request, pk):
        account = get_object_or_404(Account, pk=pk, user=request.user)
        new_balance = Decimal(request.POST.get('balance', ''))
        current = account.balance()
        delta = new_balance - current
        if delta != 0:
            if delta > 0:
                category = Category.objects.filter(
                    user=request.user, name='Пополнение', type=Category.INCOME
                ).first()
                if category is None:
                    category = Category.objects.filter(
                        user=request.user, type=Category.INCOME
                    ).first()
                ttype = Transaction.INCOME
                amount = delta
            else:
                category = Category.objects.filter(
                    user=request.user, name='Прочие расходы', type=Category.EXPENSE
                ).first()
                if category is None:
                    category = Category.objects.filter(
                        user=request.user, type=Category.EXPENSE
                    ).first()
                ttype = Transaction.EXPENSE
                amount = -delta
            if category is not None:
                Transaction.objects.create(
                    user=request.user, account=account, category=category,
                    amount=amount, type=ttype, date=date.today(),
                    description='Корректировка баланса',
                )
                messages.success(
                    request,
                    f'Баланс счёта «{account.name}» установлен: {new_balance:,.0f} UZS '
                    f'(корректировка {"+%s" % delta if delta > 0 else "%s" % delta}).',
                )
            else:
                messages.error(request, 'Не найдена подходящая категория для корректировки.')
        else:
            messages.info(request, 'Баланс не изменился.')
        return redirect('/finance/accounts/')


# ---------- Категории ----------

class CategoryListView(OwnerQuerySetMixin, ListView):
    model = Category
    template_name = 'finance/categories.html'
    context_object_name = 'categories'

    def get_queryset(self):
        return super().get_queryset().order_by('type', 'name')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        cats = list(ctx['categories'])
        ctx['income_categories'] = [c for c in cats if c.type == Category.INCOME]
        ctx['expense_categories'] = [c for c in cats if c.type == Category.EXPENSE]
        ctx['form'] = CategoryForm()
        return ctx


class CategoryCreateView(OwnerQuerySetMixin, CreateView):
    model = Category
    form_class = CategoryForm
    template_name = 'finance/category_form.html'

    def form_valid(self, form):
        form.instance.user = self.request.user
        messages.success(self.request, 'Категория создана.')
        return super().form_valid(form)

    def get_success_url(self):
        return '/finance/categories/'


class CategoryUpdateView(OwnerQuerySetMixin, UpdateView):
    model = Category
    form_class = CategoryForm
    template_name = 'finance/category_form.html'

    def get_success_url(self):
        return '/finance/categories/'


class CategoryArchiveView(OwnerQuerySetMixin, View):
    def post(self, request, pk):
        cat = get_object_or_404(Category, pk=pk, user=request.user)
        cat.archive()
        messages.success(request, f'Категория «{cat.name}» архивирована.')
        return redirect('/finance/categories/')


# ---------- Регулярные шаблоны ----------

class RecurringListView(OwnerQuerySetMixin, ListView):
    model = RecurringTemplate
    template_name = 'finance/recurring.html'
    context_object_name = 'templates'

    def get_queryset(self):
        return super().get_queryset().select_related('account', 'category')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        today = timezone.localdate()
        rows = []
        overdue = 0
        for t in ctx['templates']:
            due = t.due_dates(today)
            if due:
                overdue += 1
            rows.append({'obj': t, 'next_run': t.next_run_date(today), 'due_count': len(due)})
        ctx['rows'] = rows
        ctx['overdue_count'] = overdue
        ctx['today'] = today
        return ctx


class RecurringRunNowView(LoginRequiredMixin, View):
    """POST: выполнить один шаблон (pk) или все шаблоны пользователя (без pk) за сегодня."""

    def post(self, request, pk=None):
        ids = None
        if pk is not None:
            get_object_or_404(RecurringTemplate, pk=pk, user=request.user)
            ids = [pk]
        report = run_recurring_templates(user=request.user, template_ids=ids)
        if report.created:
            messages.success(request, report.summary())
        else:
            messages.info(request, 'Новых операций нет: всё уже создано.')
        for err in report.errors:
            messages.warning(request, err)
        return redirect('/finance/recurring/')


class RecurringCreateView(OwnerQuerySetMixin, CreateView):
    model = RecurringTemplate
    form_class = RecurringTemplateForm
    template_name = 'finance/recurring_form.html'

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw['user'] = self.request.user
        return kw

    def get_success_url(self):
        return '/finance/recurring/'


class RecurringUpdateView(OwnerQuerySetMixin, UpdateView):
    model = RecurringTemplate
    form_class = RecurringTemplateForm
    template_name = 'finance/recurring_form.html'

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw['user'] = self.request.user
        return kw

    def get_success_url(self):
        return '/finance/recurring/'


class RecurringDeleteView(OwnerQuerySetMixin, DeleteView):
    model = RecurringTemplate
    template_name = 'finance/confirm_delete.html'

    def get_success_url(self):
        return '/finance/recurring/'
