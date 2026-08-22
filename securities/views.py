from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from finance.mixins import OwnerQuerySetMixin
from .forms import SecurityForm, SecurityValuationForm
from .models import Security, SecurityValuation


class SecurityListView(OwnerQuerySetMixin, ListView):
    model = Security
    template_name = 'securities/list.html'
    context_object_name = 'securities'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        for s in ctx['securities']:
            s.cur_value = s.current_value()
            s.cur_pnl = s.pnl()
        return ctx


class SecurityCreateView(OwnerQuerySetMixin, CreateView):
    model = Security
    form_class = SecurityForm
    template_name = 'securities/form.html'

    def form_valid(self, form):
        form.instance.user = self.request.user
        messages.success(self.request, 'Бумага/доля добавлена.')
        return super().form_valid(form)

    def get_success_url(self):
        return '/securities/'


class SecurityUpdateView(OwnerQuerySetMixin, UpdateView):
    model = Security
    form_class = SecurityForm
    template_name = 'securities/form.html'

    def get_success_url(self):
        return '/securities/'


class SecurityDeleteView(OwnerQuerySetMixin, DeleteView):
    model = Security
    template_name = 'finance/confirm_delete.html'

    def get_success_url(self):
        return '/securities/'


class SecurityValuationCreateView(OwnerQuerySetMixin, CreateView):
    model = SecurityValuation
    form_class = SecurityValuationForm
    template_name = 'securities/valuation_form.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['security'] = get_object_or_404(Security, pk=self.kwargs['pk'], user=self.request.user)
        return ctx

    def form_valid(self, form):
        security = get_object_or_404(Security, pk=self.kwargs['pk'], user=self.request.user)
        form.instance.security = security
        messages.success(self.request, 'Переоценка добавлена.')
        return super().form_valid(form)

    def get_success_url(self):
        return f'/securities/{self.kwargs["pk"]}/valuations/'
        # NB: pk берём из kwargs; доступ к self.object может быть ещё не установлен


class SecurityValuationListView(OwnerQuerySetMixin, ListView):
    model = SecurityValuation
    template_name = 'securities/valuations.html'
    context_object_name = 'valuations'

    owner_field = 'security__user'

    def get_queryset(self):
        qs = super().get_queryset().filter(security_id=self.kwargs['pk'])
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['security'] = get_object_or_404(Security, pk=self.kwargs['pk'], user=self.request.user)
        return ctx
