"""
Сервис-слой аналитики: P&L за период и Net Worth на дату.

Все агрегации выполняются через ORM (annotate/aggregate),
без построчных Python-циклов по транзакциям.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Dict, Optional

from django.contrib.auth import get_user_model
from django.db.models import Q, Sum
from django.db.models.functions import Coalesce

from deposits.models import Deposit
from finance.models import Account, Transaction
from securities.models import Security, SecurityValuation

User = get_user_model()


def _ensure_decimal(v) -> Decimal:
    if v is None:
        return Decimal('0')
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v))


def _accounts_balance(user, as_of_date: Optional[date] = None) -> Decimal:
    """Сумма балансов всех активных счетов пользователя на дату.

    Считается одним агрегирующим запросом:
      баланс = SUM(income) - SUM(expense) с фильтром по дате.
    """
    qs = Transaction.objects.filter(user=user, account__is_active=True)
    if as_of_date is not None:
        qs = qs.filter(date__lte=as_of_date)
    agg = qs.aggregate(
        income=Coalesce(
            Sum('amount', filter=Q(type=Transaction.INCOME)), Decimal('0')
        ),
        expense=Coalesce(
            Sum('amount', filter=Q(type=Transaction.EXPENSE)), Decimal('0')
        ),
    )
    return _ensure_decimal(agg['income']) - _ensure_decimal(agg['expense'])


def _deposits_balance(user, as_of_date: Optional[date] = None) -> Decimal:
    """Сумма текущих балансов всех активных вкладов (principal + accrued_income)."""
    total = Decimal('0')
    active_deposits = Deposit.objects.filter(user=user, status=Deposit.ACTIVE)
    for deposit in active_deposits:
        accrued = deposit.get_accrued_income(as_of_date)
        total += _ensure_decimal(deposit.principal_amount) + _ensure_decimal(accrued)
    return total


def _securities_value(user, as_of_date: Optional[date] = None) -> Decimal:
    """Сумма текущих оценок всех бумаг пользователя на дату.

    Для каждой бумаги берётся последняя переоценка <= as_of_date
    (если её нет — стоимость приобретения). Считается одним запросом
    с подзапросом-агрегацией по SecurityValuation.
    """
    secs = Security.objects.filter(user=user)
    total = Decimal('0')
    for sec in secs:
        total += _ensure_decimal(sec.current_value(as_of_date))
    return total


def calculate_net_worth(user, as_of_date: Optional[date] = None) -> Decimal:
    """Net Worth = счета + вклады + ценные бумаги на дату."""
    target = as_of_date or date.today()
    accounts = _accounts_balance(user, target)
    deposits = _deposits_balance(user, target)
    securities = _securities_value(user, target)
    return (accounts + deposits + securities).quantize(Decimal('0.01'))


def _transactions_pnl(user, date_from: date, date_to: date) -> Decimal:
    """Доходы минус расходы по транзакциям за период (один агрегирующий запрос)."""
    qs = Transaction.objects.filter(user=user, date__gte=date_from, date__lte=date_to)
    agg = qs.aggregate(
        income=Coalesce(
            Sum('amount', filter=Q(type=Transaction.INCOME)), Decimal('0')
        ),
        expense=Coalesce(
            Sum('amount', filter=Q(type=Transaction.EXPENSE)), Decimal('0')
        ),
    )
    return _ensure_decimal(agg['income']) - _ensure_decimal(agg['expense'])


def _deposits_pnl(user, date_from: date, date_to: date) -> Decimal:
    """Прирост накопленного дохода по активным вкладам за период.

    Для каждого вклада: accrued_income(to) - accrued_income(from).
    """
    total = Decimal('0')
    for deposit in Deposit.objects.filter(user=user, status=Deposit.ACTIVE):
        before = deposit.get_accrued_income(date_from - timedelta(days=1))
        after = deposit.get_accrued_income(date_to)
        total += _ensure_decimal(after) - _ensure_decimal(before)
    return total


def _securities_pnl(user, date_from: date, date_to: date) -> Decimal:
    """Изменение стоимости всех бумаг за период.

    Стоимость на конец периода минус стоимость на начало периода
    (по последним переоценкам <= соответствующей даты).
    """
    total = Decimal('0')
    for sec in Security.objects.filter(user=user):
        start_value = _ensure_decimal(sec.current_value(date_from - timedelta(days=1)))
        end_value = _ensure_decimal(sec.current_value(date_to))
        total += end_value - start_value
    return total


def calculate_pnl(user, date_from: date, date_to: date) -> Dict[str, Decimal]:
    """P&L за период = сумма трёх компонентов.

    Возвращает словарь с разрезом по компонентам и итогом.
    """
    tx = _transactions_pnl(user, date_from, date_to)
    dep = _deposits_pnl(user, date_from, date_to)
    sec = _securities_pnl(user, date_from, date_to)
    total = (tx + dep + sec).quantize(Decimal('0.01'))
    return {
        'transactions': tx.quantize(Decimal('0.01')),
        'deposits': dep.quantize(Decimal('0.01')),
        'securities': sec.quantize(Decimal('0.01')),
        'total': total,
    }


def _month_end(year: int, month: int) -> date:
    """Последний день указанного месяца."""
    if month == 12:
        nxt = date(year + 1, 1, 1)
    else:
        nxt = date(year, month + 1, 1)
    return nxt - timedelta(days=1)


def net_worth_dynamics(user, months: int = 12):
    """Динамика Net Worth по месяцам для графика на дашборде.

    Возвращает список (метка месяца 'YYYY-MM', net_worth) от старого к новому.
    """
    today = date.today()
    points = []
    y, m = today.year, today.month
    # отступаем на (months-1) месяцев назад
    total_back = months - 1
    start_year = y - (m - 1 + total_back) // 12
    start_month_offset = (m - 1 + total_back) % 12
    cy, cm = start_year, start_month_offset + 1
    for _ in range(months):
        end = _month_end(cy, cm)
        if end > today:
            end = today
        nw = calculate_net_worth(user, end)
        points.append((f'{cy:04d}-{cm:02d}', nw))
        cm += 1
        if cm > 12:
            cm = 1
            cy += 1
    return points


def monthly_income_expense(user, months: int = 12):
    """Доходы/расходы по месяцам за последние N месяцев (для таблицы статистики)."""
    today = date.today()
    result = []
    for i in range(months - 1, -1, -1):
        first = (date(today.year, today.month, 1) - timedelta(days=30 * i))
        # первый день нужного месяца
        first = first.replace(day=1)
        next_month = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
        last = next_month - timedelta(days=1)
        qs = Transaction.objects.filter(user=user, date__gte=first, date__lte=last)
        agg = qs.aggregate(
            income=Coalesce(
                Sum('amount', filter=Q(type=Transaction.INCOME)), Decimal('0')
            ),
            expense=Coalesce(
                Sum('amount', filter=Q(type=Transaction.EXPENSE)), Decimal('0')
            ),
        )
        result.append({
            'month': first.strftime('%Y-%m'),
            'income': _ensure_decimal(agg['income']).quantize(Decimal('0.01')),
            'expense': _ensure_decimal(agg['expense']).quantize(Decimal('0.01')),
        })
    return result


def category_breakdown(user, date_from: date, date_to: date, tx_type: str):
    """Суммы по категориям за период (для pie/bar диаграмм)."""
    qs = (
        Transaction.objects
        .filter(user=user, type=tx_type, date__gte=date_from, date__lte=date_to)
        .values('category__name')
        .annotate(total=Coalesce(Sum('amount'), Decimal('0')))
        .order_by('-total')
    )
    return [
        {'category': r['category__name'], 'total': _ensure_decimal(r['total']).quantize(Decimal('0.01'))}
        for r in qs
    ]
