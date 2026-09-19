from decimal import Decimal

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.generic import CreateView, DeleteView, ListView, UpdateView, View

from finance.mixins import OwnerQuerySetMixin
from .forms import GoalForm, GoalTopUpForm
from .models import Goal


def goal_rows(user, today=None, only_active=True):
    """Готовые строки для шаблонов/дашборда."""
    from analytics.services import month_to_date_range, savings_rate
    today = today or timezone.localdate()
    qs = Goal.objects.filter(user=user).select_related('account', 'deposit')
    if only_active:
        qs = qs.filter(status=Goal.ACTIVE)
    # средний темп накопления — по норме сбережений последних 3 месяцев
    df, dt = month_to_date_range(today)
    rows = []
    for g in qs:
        cur = g.current_amount(today)
        rows.append({
            'goal': g,
            'current': cur,
            'pct': g.progress_pct(today),
            'remaining': g.remaining(today),
            'months_left': g.months_left(today),
            'required_monthly': g.required_monthly(today),
        })
    return rows


class GoalListView(OwnerQuerySetMixin, ListView):
    model = Goal
    template_name = 'goals/list.html'
    context_object_name = 'goals'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        today = timezone.localdate()
        ctx['rows'] = goal_rows(self.request.user, today)
        ctx['done'] = Goal.objects.filter(user=self.request.user, status=Goal.DONE)
        ctx['topup_form'] = GoalTopUpForm()
        return ctx


class GoalCreateView(OwnerQuerySetMixin, CreateView):
    model = Goal
    form_class = GoalForm
    template_name = 'goals/form.html'

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw['user'] = self.request.user
        return kw

    def form_valid(self, form):
        form.save()
        messages.success(self.request, 'Цель добавлена.')
        return redirect('/goals/')


class GoalUpdateView(OwnerQuerySetMixin, UpdateView):
    model = Goal
    form_class = GoalForm
    template_name = 'goals/form.html'

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw['user'] = self.request.user
        return kw

    def form_valid(self, form):
        form.save()
        return redirect('/goals/')


class GoalDeleteView(OwnerQuerySetMixin, DeleteView):
    model = Goal
    template_name = 'finance/confirm_delete.html'

    def get_success_url(self):
        return '/goals/'


class GoalTopUpView(OwnerQuerySetMixin, View):
    """Ручное пополнение накопления (для целей без привязки к счёту/вкладу)."""

    def post(self, request, pk):
        goal = get_object_or_404(Goal, pk=pk, user=request.user)
        form = GoalTopUpForm(request.POST)
        if form.is_valid() and not goal.account_id and not goal.deposit_id:
            goal.saved_manual = max((goal.saved_manual or Decimal('0')) + form.cleaned_data['amount'], Decimal('0'))
            goal.save(update_fields=['saved_manual', 'updated_at'])
            if goal.check_done():
                messages.success(request, f'Цель «{goal.name}» достигнута 🎉')
            else:
                messages.success(request, 'Накопление обновлено.')
        else:
            messages.error(request, 'Для целей, привязанных к счёту или вкладу, сумма берётся автоматически.')
        return redirect('/goals/')
