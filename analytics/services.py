"""
Сервис-слой аналитики: P&L за период и Net Worth на дату.

Все агрегации выполняются через ORM (annotate/aggregate),
без построчных Python-циклов по транзакциям.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple
import calendar

from django.contrib.auth import get_user_model
from django.db.models import Q, Sum, Avg
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


# ---------------------------------------------------------------------------
# Периоды: month-to-date по умолчанию + эквивалентный предыдущий период
# ---------------------------------------------------------------------------

def month_to_date_range(ref: Optional[date] = None) -> Tuple[date, date]:
    """Диапазон «с 1 числа текущего месяца по сегодня» (month-to-date)."""
    today = ref or date.today()
    return date(today.year, today.month, 1), today


def _shift_months(d: date, months: int) -> date:
    """Сдвиг даты на N календарных месяцев с сохранением дня (с клампом в
    конец месяца, если дня не существует — например 31.05 → 30.04)."""
    y, m = d.year, d.month + months
    while m <= 0:
        m += 12
        y -= 1
    while m > 12:
        m -= 12
        y += 1
    last_day = calendar.monthrange(y, m)[1]
    return date(y, m, min(d.day, last_day))


def previous_equivalent_period(date_from: date, date_to: date) -> Tuple[date, date]:
    """Эквивалентный по длине предыдущий период.

    Оба конца сдвигаются на один календарный месяц назад с сохранением номера
    дня — поэтому для month-to-date (01.08–22.08) получается 01.07–22.07,
    т.е. ровно то же число дней и те же номера дней. Для произвольного диапазона
    тоже сохраняется корректность по числу дней.
    """
    return _shift_months(date_from, -1), _shift_months(date_to, -1)


def period_label(date_from: date, date_to: date) -> str:
    """Человекочитаемая подпись периода для текстовых сводок."""
    months_ru = [
        'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
        'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря',
    ]
    # Если период — month-to-date одного месяца (с 1-го числа), показать «август 2026»
    if date_from.day == 1 and date_from.year == date_to.year and date_from.month == date_to.month:
        return f'{months_ru[date_from.month - 1]} {date_from.year}'
    return f'{date_from:%d.%m.%Y}–{date_to:%d.%m.%Y}'


# ---------------------------------------------------------------------------
# Разбивка Net Worth по трём укрупнённым компонентам
# ---------------------------------------------------------------------------

def net_worth_breakdown(user, as_of_date: Optional[date] = None) -> Dict:
    """Возвращает состав Net Worth: 3 компонента с суммой и долей в %."""
    target = as_of_date or date.today()
    accounts = _accounts_balance(user, target)
    deposits = _deposits_balance(user, target)
    securities = _securities_value(user, target)
    total = (accounts + deposits + securities).quantize(Decimal('0.01'))

    def _pct(part: Decimal) -> Decimal:
        if total == 0:
            return Decimal('0')
        return (part / total * Decimal('100')).quantize(Decimal('1'))

    components = [
        {
            'key': 'accounts', 'label': 'Деньги на картах/наличные',
            'value': accounts.quantize(Decimal('0.01')), 'pct': _pct(accounts),
            'url': '/finance/accounts/',
        },
        {
            'key': 'deposits', 'label': 'Вклады (принципал + доход)',
            'value': deposits.quantize(Decimal('0.01')), 'pct': _pct(deposits),
            'url': '/deposits/',
        },
        {
            'key': 'securities', 'label': 'Доля в компании / ценные бумаги',
            'value': securities.quantize(Decimal('0.01')), 'pct': _pct(securities),
            'url': '/securities/',
        },
    ]
    return {
        'total': total,
        'components': [c for c in components if c['value'] > 0] or components,
        'all_components': components,
    }


# ---------------------------------------------------------------------------
# Объяснение изменения P&L (period-over-period)
# ---------------------------------------------------------------------------

def _category_sums(user, date_from: date, date_to: date) -> Dict[str, Dict[str, Decimal]]:
    """Суммы по категориям за период одним агрегирующим запросом.

    Возвращает {category_name: {'income': Decimal, 'expense': Decimal}}.
    """
    qs = (
        Transaction.objects
        .filter(user=user, date__gte=date_from, date__lte=date_to)
        .values('category__name', 'type')
        .annotate(total=Coalesce(Sum('amount'), Decimal('0')))
    )
    out: Dict[str, Dict[str, Decimal]] = {}
    for r in qs:
        name = r['category__name'] or 'Без категории'
        out.setdefault(name, {'income': Decimal('0'), 'expense': Decimal('0')})
        key = 'income' if r['type'] == Transaction.INCOME else 'expense'
        out[name][key] = _ensure_decimal(r['total'])
    return out


def _category_signed_total(sums: Dict[str, Dict[str, Decimal]]) -> Dict[str, Decimal]:
    """Доходы − расходы по каждой категории (знаковый вклад в P&L)."""
    return {
        name: (s['income'] - s['expense'])
        for name, s in sums.items()
    }


def explain_pnl_change(user, date_from: date, date_to: date) -> Dict:
    """Автоматическая сводка-объяснение изменения P&L period-over-period.

    Возвращает:
      summary_text  — человекочитаемый текст (уровень 1);
      top_factors   — список вкладов категорий в изменение (для таблицы);
      anomalies     — список аномальных транзакций текущего периода;
      components     — разбивка P&L по 3 компонентам (операционный/вклады/бумаги)
                       с динамикой относительно предыдущего периода;
      periods       — {current: {from,to,label}, previous: {from,to,label}}.
    """
    prev_from, prev_to = previous_equivalent_period(date_from, date_to)

    # --- P&L текущего и предыдущего периодов ---
    pnl_current = calculate_pnl(user, date_from, date_to)
    pnl_previous = calculate_pnl(user, prev_from, prev_to)

    cur_total = pnl_current['total']
    prev_total = pnl_previous['total']
    delta = cur_total - prev_total

    # --- Вклад категорий в изменение ---
    cur_sums = _category_sums(user, date_from, date_to)
    prev_sums = _category_sums(user, prev_from, prev_to)
    cur_signed = _category_signed_total(cur_sums)
    prev_signed = _category_signed_total(prev_sums)

    all_names = set(cur_signed) | set(prev_signed)
    factors = []
    for name in all_names:
        c = cur_signed.get(name, Decimal('0'))
        p = prev_signed.get(name, Decimal('0'))
        cat_delta = c - p
        factors.append({
            'category': name,
            'current': c.quantize(Decimal('0.01')),
            'previous': p.quantize(Decimal('0.01')),
            'delta': cat_delta.quantize(Decimal('0.01')),
            'pct_of_delta': (abs(cat_delta) / abs(delta) * Decimal('100')).quantize(Decimal('1'))
                            if delta != 0 else Decimal('0'),
        })
    factors.sort(key=lambda f: abs(f['delta']), reverse=True)

    # --- Топ-факторы для текста (топ-1 или топ-2) ---
    top_factors = [f for f in factors if f['delta'] != 0][:2]

    # --- Аномальные транзакции ---
    anomalies = _detect_anomalies(user, date_from, date_to)

    # --- Компоненты P&L с динамикой ---
    components = {
        'operational': {
            'current': pnl_current['transactions'],
            'previous': pnl_previous['transactions'],
            'delta': (pnl_current['transactions'] - pnl_previous['transactions']).quantize(Decimal('0.01')),
        },
        'deposits': {
            'current': pnl_current['deposits'],
            'previous': pnl_previous['deposits'],
            'delta': (pnl_current['deposits'] - pnl_previous['deposits']).quantize(Decimal('0.01')),
        },
        'securities': {
            'current': pnl_current['securities'],
            'previous': pnl_previous['securities'],
            'delta': (pnl_current['securities'] - pnl_previous['securities']).quantize(Decimal('0.01')),
        },
    }

    # --- Текстовая сводка (уровень 1) ---
    summary_text = _build_summary_text(
        cur_total, prev_total, delta, top_factors, components,
        period_label(date_from, date_to), period_label(prev_from, prev_to),
    )

    return {
        'summary_text': summary_text,
        'top_factors': top_factors,
        'factors': factors,
        'anomalies': anomalies,
        'components': components,
        'pnl_current': cur_total,
        'pnl_previous': prev_total,
        'delta': delta.quantize(Decimal('0.01')),
        'periods': {
            'current': {'from': date_from, 'to': date_to, 'label': period_label(date_from, date_to)},
            'previous': {'from': prev_from, 'to': prev_to, 'label': period_label(prev_from, prev_to)},
        },
    }


def _build_summary_text(cur, prev, delta, top_factors, components, cur_label, prev_label) -> str:
    """Шаблонная сборка человекочитаемой сводки (без ML)."""
    if cur == 0 and prev == 0:
        return (f'Ваш P&L за {cur_label} составил 0 UZS (в {prev_label} также было 0 UZS). '
                f'Финансовая активность в обоих периодах отсутствует.')

    direction_word = 'роста' if delta >= 0 else 'падения'
    verb = 'рост' if delta >= 0 else 'падение'

    parts = [
        f'Ваш P&L за {cur_label} составил {cur} UZS '
        f'(в {prev_label} было {prev} UZS).'
    ]

    if top_factors:
        f1 = top_factors[0]
        # Определяем направление влияния топ-фактора
        if f1['delta'] >= 0:
            cat_dir = 'рост'
            reason_word = 'роста'
        else:
            cat_dir = 'снижение'
            reason_word = 'падения'
        sign = '+' if f1['delta'] >= 0 else ''
        parts.append(
            f'Основная причина {reason_word} — {cat_dir} по категории '
            f'«{f1["category"]}» ({sign}{f1["delta"]} UZS по сравнению с {prev_label}).'
        )
        if len(top_factors) > 1:
            f2 = top_factors[1]
            sign2 = '+' if f2['delta'] >= 0 else ''
            parts.append(
                f'Также вклад внесла категория «{f2["category"]}» ({sign2}{f2["delta"]} UZS).'
            )

    # Упоминание вкладов/бумаг при пороге >10% от модуля изменения
    if delta != 0:
        threshold = abs(delta) * Decimal('0.1')
        dep = components['deposits']['delta']
        sec = components['securities']['delta']
        if abs(dep) > threshold:
            sign = '+' if dep >= 0 else ''
            parts.append(
                f'Доход от вкладов изменился на {sign}{dep} UZS по сравнению с {prev_label}.'
            )
        if abs(sec) > threshold:
            sign = '+' if sec >= 0 else ''
            parts.append(
                f'Переоценка долей/ценных бумаг внесла вклад {sign}{sec} UZS.'
            )
    else:
        parts.append('Изменение P&L по сравнению с предыдущим периодом отсутствует.')

    _ = direction_word, verb  # зарезервировано для возможных будущих формулировок
    return ' '.join(parts)


def _detect_anomalies(user, date_from: date, date_to: date, months_back: int = 6) -> List[Dict]:
    """Простое правило: транзакция аномальна, если её сумма > 2 × средней суммы
    по этой категории за последние `months_back` месяцев.

    Средние по категориям считаются одним агрегирующим запросом (Avg).
    """
    hist_from = _shift_months(date_from, -months_back)
    # средняя сумма транзакции по категории за историю
    hist_avg = (
        Transaction.objects
        .filter(user=user, date__gte=hist_from, date__lt=date_from)
        .values('category__name')
        .annotate(avg=Coalesce(Avg('amount'), Decimal('0')))
    )
    avg_by_cat = {
        (r['category__name'] or 'Без категории'): _ensure_decimal(r['avg'])
        for r in hist_avg
    }

    anomalies = []
    cur_tx = (
        Transaction.objects
        .filter(user=user, date__gte=date_from, date__lte=date_to)
        .select_related('category', 'account')
        .order_by('-amount')
    )
    for tx in cur_tx:
        cat_name = tx.category.name if tx.category_id else 'Без категории'
        avg = avg_by_cat.get(cat_name, Decimal('0'))
        if avg > 0 and tx.amount > 2 * avg:
            ratio = (tx.amount / avg).quantize(Decimal('0.1'))
            anomalies.append({
                'category': cat_name,
                'amount': tx.amount,
                'date': tx.date,
                'description': tx.description,
                'avg': avg.quantize(Decimal('0.01')),
                'ratio': ratio,
            })
    return anomalies


# ---------------------------------------------------------------------------
# История P&L по компонентам за N периодов (для stacked bar)
# ---------------------------------------------------------------------------

def pnl_components_history(user, periods: int = 6) -> List[Dict]:
    """P&L по трём компонентам за последние N месяцев (для stacked bar)."""
    today = date.today()
    result = []
    for i in range(periods - 1, -1, -1):
        mf = _shift_months(date(today.year, today.month, 1), -i)
        next_month = _shift_months(mf, 1)
        last = next_month - timedelta(days=1)
        if last > today:
            last = today
        comp = calculate_pnl(user, mf, last)
        result.append({
            'label': mf.strftime('%Y-%m'),
            'operational': comp['transactions'].quantize(Decimal('0.01')),
            'deposits': comp['deposits'].quantize(Decimal('0.01')),
            'securities': comp['securities'].quantize(Decimal('0.01')),
        })
    return result

