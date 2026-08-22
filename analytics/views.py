from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import timezone
from django.views.generic import TemplateView

from analytics.services import (
    calculate_net_worth, calculate_pnl, net_worth_dynamics,
    monthly_income_expense, category_breakdown,
)
from finance.models import Transaction


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'analytics/dashboard.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        today = date.today()
        first_of_month = today.replace(day=1)

        ctx['net_worth'] = calculate_net_worth(user)
        ctx['pnl'] = calculate_pnl(user, first_of_month, today)
        ctx['pnl_month_label'] = today.strftime('%Y-%m')
        ctx['dynamics'] = net_worth_dynamics(user, months=12)
        ctx['dynamics_labels'] = [d[0] for d in ctx['dynamics']]
        ctx['dynamics_values'] = [str(d[1]) for d in ctx['dynamics']]
        ctx['recent_transactions'] = (
            Transaction.objects.filter(user=user)
            .select_related('account', 'category')
            .order_by('-date', '-created_at')[:10]
        )
        return ctx


class StatsView(LoginRequiredMixin, TemplateView):
    template_name = 'analytics/stats.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        today = date.today()
        date_from = self.request.GET.get('date_from')
        date_to = self.request.GET.get('date_to')
        if date_from:
            date_from = date.fromisoformat(date_from)
        else:
            date_from = today - timedelta(days=30)
        if date_to:
            date_to = date.fromisoformat(date_to)
        else:
            date_to = today

        ctx['date_from'] = date_from.isoformat()
        ctx['date_to'] = date_to.isoformat()
        ctx['income_by_cat'] = category_breakdown(user, date_from, date_to, Transaction.INCOME)
        ctx['expense_by_cat'] = category_breakdown(user, date_from, date_to, Transaction.EXPENSE)
        ctx['monthly'] = monthly_income_expense(user, months=12)
        ctx['income_labels'] = [m['month'] for m in ctx['monthly']]
        ctx['income_values'] = [str(m['income']) for m in ctx['monthly']]
        ctx['expense_values'] = [str(m['expense']) for m in ctx['monthly']]
        ctx['income_pie_labels'] = [c['category'] for c in ctx['income_by_cat']]
        ctx['income_pie_values'] = [str(c['total']) for c in ctx['income_by_cat']]
        ctx['expense_pie_labels'] = [c['category'] for c in ctx['expense_by_cat']]
        ctx['expense_pie_values'] = [str(c['total']) for c in ctx['expense_by_cat']]
        return ctx
