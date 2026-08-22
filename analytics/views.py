from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView

from analytics.services import (
    calculate_net_worth, calculate_pnl, net_worth_dynamics,
    monthly_income_expense, category_breakdown,
    month_to_date_range, net_worth_breakdown, explain_pnl_change,
    pnl_components_history, period_label,
)
from finance.models import Transaction


def _parse_period(request):
    """Период по умолчанию — месяц-к-дате (с 1-го числа текущего месяца по сегодня).

    Пользователь может задать диапазон через ?date_from=...&date_to=...
    (значения сохраняются в query-параметрах URL — для обновления/шаринга).
    """
    df = request.GET.get('date_from')
    dt = request.GET.get('date_to')
    default_from, default_to = month_to_date_range()
    date_from = date.fromisoformat(df) if df else default_from
    date_to = date.fromisoformat(dt) if dt else default_to
    return date_from, date_to


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'analytics/dashboard.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        today = date.today()
        date_from, date_to = _parse_period(self.request)

        # --- Net Worth и его разбивка ---
        ctx['net_worth'] = calculate_net_worth(user)
        ctx['nw_breakdown'] = net_worth_breakdown(user)
        ctx['nw_breakdown_labels'] = [c['label'] for c in ctx['nw_breakdown']['components']]
        ctx['nw_breakdown_values'] = [str(c['value']) for c in ctx['nw_breakdown']['components']]
        ctx['nw_breakdown_urls'] = [c['url'] for c in ctx['nw_breakdown']['components']]

        # --- P&L за выбранный период (по умолчанию месяц-к-дате) ---
        ctx['pnl'] = calculate_pnl(user, date_from, date_to)
        ctx['pnl_period_label'] = period_label(date_from, date_to)
        ctx['date_from'] = date_from.isoformat()
        ctx['date_to'] = date_to.isoformat()

        # --- Объяснение изменения P&L (period-over-period) ---
        ctx['explanation'] = explain_pnl_change(user, date_from, date_to)
        ctx['components_history'] = pnl_components_history(user, periods=6)
        ctx['comp_hist_labels'] = [p['label'] for p in ctx['components_history']]
        ctx['comp_hist_operational'] = [str(p['operational']) for p in ctx['components_history']]
        ctx['comp_hist_deposits'] = [str(p['deposits']) for p in ctx['components_history']]
        ctx['comp_hist_securities'] = [str(p['securities']) for p in ctx['components_history']]

        # --- Динамика капитала по месяцам ---
        ctx['dynamics'] = net_worth_dynamics(user, months=12)
        ctx['dynamics_labels'] = [d[0] for d in ctx['dynamics']]
        ctx['dynamics_values'] = [str(d[1]) for d in ctx['dynamics']]

        ctx['recent_transactions'] = (
            Transaction.objects.filter(user=user)
            .select_related('account', 'category')
            .order_by('-date', '-created_at')[:10]
        )
        # Виджет подсказки о незавершённом онбординге
        from onboarding.models import UserProfile
        from finance.models import Account
        profile = getattr(user, 'profile', None)
        ctx['onboarding_incomplete'] = (
            profile is None or not profile.onboarding_completed
        )
        ctx['has_accounts'] = Account.objects.filter(user=user).exists()
        return ctx


class StatsView(LoginRequiredMixin, TemplateView):
    template_name = 'analytics/stats.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        date_from, date_to = _parse_period(self.request)

        ctx['date_from'] = date_from.isoformat()
        ctx['date_to'] = date_to.isoformat()
        ctx['pnl_period_label'] = period_label(date_from, date_to)
        ctx['pnl'] = calculate_pnl(user, date_from, date_to)
        # Текстовая сводка-объяснение P&L
        ctx['explanation'] = explain_pnl_change(user, date_from, date_to)
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
