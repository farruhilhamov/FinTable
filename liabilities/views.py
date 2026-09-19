from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.generic import CreateView, DeleteView, ListView, UpdateView, View

from finance.mixins import OwnerQuerySetMixin
from .forms import LiabilityForm, PaymentForm
from .models import Liability


class LiabilityListView(OwnerQuerySetMixin, ListView):
    model = Liability
    template_name = 'liabilities/list.html'
    context_object_name = 'liabilities'

    def get_queryset(self):
        return super().get_queryset().select_related('account', 'recurring_template')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        today = timezone.localdate()
        active = [l for l in ctx['liabilities'] if l.status == Liability.ACTIVE]
        ctx['active'] = active
        ctx['closed'] = [l for l in ctx['liabilities'] if l.status != Liability.ACTIVE]
        ctx['total_owe'] = sum((l.balance for l in active if l.direction == Liability.OWE), Decimal('0'))
        ctx['total_owed'] = sum((l.balance for l in active if l.direction == Liability.OWED), Decimal('0'))
        ctx['monthly_total'] = sum(
            (l.monthly_payment for l in active if l.monthly_payment and l.direction == Liability.OWE),
            Decimal('0'),
        )
        for l in active:
            l.months_left_calc = l.months_left(today)
            l.days_to_due_calc = l.days_to_due(today)
        return ctx


class LiabilityCreateView(OwnerQuerySetMixin, CreateView):
    model = Liability
    form_class = LiabilityForm
    template_name = 'liabilities/form.html'

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw['user'] = self.request.user
        return kw

    def form_valid(self, form):
        form.save()
        messages.success(self.request, 'Обязательство добавлено.')
        return redirect('/liabilities/')


class LiabilityUpdateView(OwnerQuerySetMixin, UpdateView):
    model = Liability
    form_class = LiabilityForm
    template_name = 'liabilities/form.html'

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw['user'] = self.request.user
        return kw

    def form_valid(self, form):
        form.save()
        messages.success(self.request, 'Сохранено.')
        return redirect('/liabilities/')


class LiabilityDeleteView(OwnerQuerySetMixin, DeleteView):
    model = Liability
    template_name = 'finance/confirm_delete.html'

    def form_valid(self, form):
        if self.object.recurring_template_id:
            self.object.recurring_template.delete()
        return super().form_valid(form)

    def get_success_url(self):
        return '/liabilities/'


class LiabilityPayView(LoginRequiredMixin, View):
    template_name = 'liabilities/pay.html'

    def get(self, request, pk):
        liab = get_object_or_404(Liability, pk=pk, user=request.user)
        form = PaymentForm(user=request.user, liability=liab)
        return render(request, self.template_name, {'form': form, 'liability': liab})

    def post(self, request, pk):
        liab = get_object_or_404(Liability, pk=pk, user=request.user)
        form = PaymentForm(request.POST, user=request.user, liability=liab)
        if form.is_valid():
            d = form.cleaned_data
            liab.apply_payment(
                d['amount'], d['date'], account=d.get('account') or liab.account,
                description=d.get('description', ''), create_transaction=d.get('create_transaction', True),
            )
            if liab.status == Liability.CLOSED:
                messages.success(request, f'«{liab.name}» полностью погашен 🎉')
            else:
                messages.success(request, f'Платёж учтён. Остаток: {liab.balance:,.0f} UZS'.replace(',', ' '))
            return redirect('/liabilities/')
        return render(request, self.template_name, {'form': form, 'liability': liab})
