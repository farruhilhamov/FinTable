from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from deposits.models import Deposit


@login_required
@require_http_methods(["GET"])
def deposit_preview(request):
    """HTMX-эндпоинт: предпросмотр накопленного дохода по вкладу до сохранения.

    Использует ту же модель Deposit (несохранённый экземпляр), чтобы расчёт
    гарантированно совпадал с get_accrued_income().
    """
    def _get(key, default=None):
        v = request.GET.get(key, default)
        return v

    try:
        principal = Decimal(str(request.GET.get('principal_amount', '0') or '0'))
        rate = Decimal(str(request.GET.get('annual_rate', '0') or '0'))
    except (InvalidOperation, ValueError):
        return HttpResponse('—')
    cap = request.GET.get('capitalization_type', Deposit.SIMPLE)
    start_raw = request.GET.get('start_date', '')
    try:
        start = date.fromisoformat(start_raw) if start_raw else date.today()
    except ValueError:
        start = date.today()

    # Несохранённый экземпляр — расчёт идёт по тем же формулам модели.
    tmp = Deposit(
        principal_amount=principal or Decimal('0'),
        annual_rate=rate or Decimal('0'),
        start_date=start,
        capitalization_type=cap if cap in dict(Deposit.CAP_TYPE_CHOICES) else Deposit.SIMPLE,
        status=Deposit.ACTIVE,
    )
    accrued = tmp.get_accrued_income()
    balance = (tmp.principal_amount + accrued).quantize(Decimal('0.01'))
    return render(request, 'onboarding/_deposit_preview.html', {
        'accrued': str(accrued),
        'balance': str(balance),
    })


@login_required
def settings_view(request):
    """Страница «Настройки» с кнопкой повторного запуска мастера."""
    profile = getattr(request.user, 'profile', None)
    return render(request, 'onboarding/settings.html', {'profile': profile})
