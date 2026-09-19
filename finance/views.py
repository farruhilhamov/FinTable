from datetime import date
from decimal import Decimal

from django.contrib import messages
from django.db.models import Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import timezone
from django.views.generic import CreateView, DeleteView, ListView, UpdateView, View

from .forms import (
    AccountForm, BudgetForm, CategoryForm, RecurringTemplateForm, TransactionForm, TransferForm,
)
from .mixins import OwnerQuerySetMixin
from .services import run_recurring_templates
from .models import Account, Budget, Category, RecurringTemplate, Transaction


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
        q = (get.get('q') or '').strip()
        if q:
            qs = qs.filter(Q(description__icontains=q) | Q(tags__icontains=q) | Q(category__name__icontains=q))
        if ttype == 'transfer':
            qs = qs.filter(category__is_transfer=True)
            ttype = ''
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
        ctx['categories'] = Category.objects.filter(user=self.request.user, is_active=True, is_transfer=False)
        ctx['type_choices'] = Transaction.TYPE_CHOICES
        ctx['filters'] = {
            'date_from': self.request.GET.get('date_from', default_from),
            'date_to': self.request.GET.get('date_to', default_to),
            'category': self.request.GET.get('category', ''),
            'account': self.request.GET.get('account', ''),
            'type': self.request.GET.get('type', ''),
            'q': self.request.GET.get('q', ''),
        }
        agg = self.object_list.exclude(category__is_transfer=True).aggregate(
            income=Sum('amount', filter=Q(type=Transaction.INCOME), default=Decimal('0')),
            expense=Sum('amount', filter=Q(type=Transaction.EXPENSE), default=Decimal('0')),
        )
        ctx['totals'] = {
            'income': agg['income'] or Decimal('0'),
            'expense': agg['expense'] or Decimal('0'),
            'net': (agg['income'] or Decimal('0')) - (agg['expense'] or Decimal('0')),
        }
        return ctx


class TransactionCreateView(OwnerQuerySetMixin, CreateView):
    model = Transaction
    form_class = TransactionForm
    template_name = 'finance/transaction_form.html'

    def get_template_names(self):
        if 'HX-Request' in self.request.headers or self.request.GET.get('modal'):
            return ['finance/_transaction_modal.html']
        return [self.template_name]

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw['user'] = self.request.user
        return kw

    def get_initial(self):
        """Быстрый ввод: подставляем последние использованные счёт/категорию/тип,
        либо копируем существующую операцию (?copy=<id>)."""
        initial = super().get_initial()
        initial['date'] = timezone.localdate()
        copy_id = self.request.GET.get('copy')
        if copy_id:
            src = Transaction.objects.filter(user=self.request.user, pk=copy_id).first()
            if src is not None:
                initial.update({
                    'account': src.account_id, 'category': src.category_id,
                    'amount': src.amount, 'type': src.type,
                    'description': src.description, 'tags': src.tags,
                })
                return initial
        last = self.request.session.get('last_tx') or {}
        for k in ('account', 'category', 'type'):
            if last.get(k):
                initial[k] = last[k]
        return initial

    def form_valid(self, form):
        tx = form.save()
        self.request.session['last_tx'] = {
            'account': tx.account_id, 'category': tx.category_id, 'type': tx.type,
        }
        messages.success(self.request, 'Транзакция добавлена.')
        if 'HX-Request' in self.request.headers:
            back = self.request.headers.get('HX-Current-URL') or '/finance/transactions/'
            return HttpResponse('', status=204, headers={'HX-Redirect': back})
        return redirect('/finance/transactions/')


class TransferCreateView(LoginRequiredMixin, View):
    """Перевод между счетами: две связанные операции, не влияющие на P&L."""
    template_name = 'finance/transfer_form.html'

    def get(self, request):
        form = TransferForm(user=request.user, initial={'from_account': request.GET.get('from')})
        return render(request, self.template_name, {'form': form})

    def post(self, request):
        form = TransferForm(request.POST, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Перевод выполнен.')
            return redirect('/finance/transactions/')
        return render(request, self.template_name, {'form': form})


class TransactionUpdateView(OwnerQuerySetMixin, UpdateView):
    model = Transaction
    form_class = TransactionForm
    template_name = 'finance/transaction_form.html'

    def dispatch(self, request, *args, **kwargs):
        obj = self.get_object() if request.user.is_authenticated else None
        if obj is not None and obj.is_transfer:
            messages.info(request, 'Перевод нельзя редактировать: удалите его и создайте заново.')
            return redirect('/finance/transactions/')
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw['user'] = self.request.user
        return kw

    def get_success_url(self):
        return '/finance/transactions/'


class TransactionDeleteView(OwnerQuerySetMixin, DeleteView):
    model = Transaction
    template_name = 'finance/confirm_delete.html'

    def form_valid(self, form):
        # Перевод удаляется целиком: обе парные операции.
        pair = self.object.transfer_pair
        if pair is None:
            pair = getattr(self.object, 'transfer_counterpart', None)
        if pair is not None:
            pair.delete()
        return super().form_valid(form)

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
        return super().get_queryset().filter(is_transfer=False).order_by('type', 'name')

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


# ---------- Бюджеты ----------

class BudgetListView(OwnerQuerySetMixin, ListView):
    model = Budget
    template_name = 'finance/budgets.html'
    context_object_name = 'budgets'

    def get_context_data(self, **kwargs):
        from analytics.services import budget_status, month_to_date_range
        ctx = super().get_context_data(**kwargs)
        date_from, date_to = month_to_date_range()
        ctx['rows'] = budget_status(self.request.user, date_from, date_to)
        ctx['inactive'] = Budget.objects.filter(user=self.request.user, is_active=False).select_related('category')
        ctx['date_from'], ctx['date_to'] = date_from, date_to
        return ctx


class BudgetCreateView(OwnerQuerySetMixin, CreateView):
    model = Budget
    form_class = BudgetForm
    template_name = 'finance/budget_form.html'

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw['user'] = self.request.user
        return kw

    def form_valid(self, form):
        messages.success(self.request, 'Бюджет создан.')
        return super().form_valid(form)

    def get_success_url(self):
        return '/finance/budgets/'


class BudgetUpdateView(OwnerQuerySetMixin, UpdateView):
    model = Budget
    form_class = BudgetForm
    template_name = 'finance/budget_form.html'

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw['user'] = self.request.user
        return kw

    def get_success_url(self):
        return '/finance/budgets/'


class BudgetDeleteView(OwnerQuerySetMixin, DeleteView):
    model = Budget
    template_name = 'finance/confirm_delete.html'

    def get_success_url(self):
        return '/finance/budgets/'
