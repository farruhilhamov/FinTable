from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.views.generic import CreateView, DeleteView, ListView, UpdateView, View

from finance.mixins import OwnerQuerySetMixin
from .forms import DepositForm
from .models import Deposit


class DepositListView(OwnerQuerySetMixin, ListView):
    model = Deposit
    template_name = 'deposits/list.html'
    context_object_name = 'deposits'

    def get_queryset(self):
        return super().get_queryset().select_related('account')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        for d in ctx['deposits']:
            d.accrued = d.get_accrued_income()
            d.balance = d.current_balance
            d.days_left = d.days_to_end()
        return ctx


class DepositCreateView(OwnerQuerySetMixin, CreateView):
    model = Deposit
    form_class = DepositForm
    template_name = 'deposits/form.html'

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw['user'] = self.request.user
        return kw

    def form_valid(self, form):
        form.instance.user = self.request.user
        messages.success(self.request, 'Вклад создан.')
        return super().form_valid(form)

    def get_success_url(self):
        return '/deposits/'


class DepositUpdateView(OwnerQuerySetMixin, UpdateView):
    model = Deposit
    form_class = DepositForm
    template_name = 'deposits/form.html'

    def get_success_url(self):
        return '/deposits/'


class DepositCloseView(OwnerQuerySetMixin, View):
    def post(self, request, pk):
        dep = get_object_or_404(Deposit, pk=pk, user=request.user)
        if request.POST.get('payout') and dep.account_id:
            dep.mature(None)
            messages.success(request, f'Вклад «{dep.name}» закрыт, деньги возвращены на счёт «{dep.account.name}».')
        else:
            dep.close()
            messages.success(request, f'Вклад «{dep.name}» закрыт.')
        return redirect('/deposits/')


class DepositDeleteView(OwnerQuerySetMixin, DeleteView):
    model = Deposit
    template_name = 'finance/confirm_delete.html'

    def get_success_url(self):
        return '/deposits/'
