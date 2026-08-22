from datetime import date

from django.contrib import messages
from django.db.models import Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.views.generic import CreateView, DeleteView, ListView, UpdateView, View

from .forms import AccountForm, CategoryForm, RecurringTemplateForm, TransactionForm
from .mixins import OwnerQuerySetMixin
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
        date_from = get.get('date_from')
        date_to = get.get('date_to')
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
        ctx['accounts'] = Account.objects.filter(user=self.request.user, is_active=True)
        ctx['categories'] = Category.objects.filter(user=self.request.user, is_active=True)
        ctx['type_choices'] = Transaction.TYPE_CHOICES
        ctx['filters'] = {
            'date_from': self.request.GET.get('date_from', ''),
            'date_to': self.request.GET.get('date_to', ''),
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
