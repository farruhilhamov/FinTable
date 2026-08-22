from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from deposits.models import Deposit
from finance.models import Account, Category, Transaction
from securities.models import Security, SecurityValuation
from analytics.services import (
    calculate_pnl, calculate_net_worth,
    month_to_date_range, previous_equivalent_period, period_label,
    net_worth_breakdown, explain_pnl_change, pnl_components_history,
)

User = get_user_model()


def _user(email, password='pass1234'):
    return User.objects.create_user(email=email, password=password)


def _make_account(user, name='Кошелёк'):
    return Account.objects.create(user=user, name=name)


def _make_category(user, name='Зарплата', ctype=Category.INCOME):
    cat, _ = Category.objects.get_or_create(user=user, name=name, type=ctype,
                                             defaults={'is_default': False})
    return cat


def _make_transaction(user, account, category, amount, ttype, dt):
    return Transaction.objects.create(
        user=user, account=account, category=category,
        amount=Decimal(str(amount)), type=ttype, date=dt,
    )


class PnLTest(TestCase):
    def setUp(self):
        self.user = _user('pnl@x.com')
        self.acc = _make_account(self.user)
        self.income_cat = _make_category(self.user, 'Зарплата', Category.INCOME)
        self.expense_cat = _make_category(self.user, 'Еда', Category.EXPENSE)
        self.dep = Deposit.objects.create(
            user=self.user, name='Вклад',
            principal_amount=Decimal('1000000'), annual_rate=Decimal('12'),
            start_date=date(2024, 1, 1),
        )
        self.sec = Security.objects.create(
            user=self.user, name='Доля',
            acquisition_value=Decimal('500000'),
            acquisition_date=date(2024, 1, 1),
        )

    def test_pnl_components(self):
        _make_transaction(self.user, self.acc, self.income_cat, '3000', Transaction.INCOME, date(2024, 1, 15))
        _make_transaction(self.user, self.acc, self.expense_cat, '1000', Transaction.EXPENSE, date(2024, 1, 20))
        SecurityValuation.objects.create(security=self.sec, value=Decimal('600000'), date=date(2024, 6, 30))

        pnl = calculate_pnl(self.user, date(2024, 1, 1), date(2024, 6, 30))
        # транзакции: 3000 - 1000 = 2000
        self.assertEqual(pnl['transactions'], Decimal('2000.00'))
        # вклад: accrued на 30.06 - accrued на 31.12 пред. = 60000 - 0
        self.assertEqual(pnl['deposits'], self.dep.get_accrued_income(date(2024, 6, 30)) -
                         self.dep.get_accrued_income(date(2023, 12, 31)))
        # бумаги: 600000 - 500000 = 100000
        self.assertEqual(pnl['securities'], Decimal('100000.00'))
        # total = сумма трёх
        self.assertEqual(pnl['total'], pnl['transactions'] + pnl['deposits'] + pnl['securities'])

    def test_net_worth(self):
        _make_transaction(self.user, self.acc, self.income_cat, '500000', Transaction.INCOME, date(2024, 1, 5))
        nw = calculate_net_worth(self.user, date(2024, 6, 30))
        # счета: 500000
        # вклад: 1_000_000 + accrued
        # бумаги: acquisition (нет переоценок) = 500000
        expected = Decimal('500000') + Decimal('1000000') + \
            self.dep.get_accrued_income(date(2024, 6, 30)) + Decimal('500000')
        self.assertEqual(nw, expected.quantize(Decimal('0.01')))


class DataIsolationTest(TestCase):
    """Тест: пользователь A не может получить данные пользователя B."""

    def setUp(self):
        self.user_a = _user('a@x.com')
        self.user_b = _user('b@x.com')
        self.acc_a = _make_account(self.user_a, 'A-счёт')
        self.acc_b = _make_account(self.user_b, 'B-счёт')

    def test_account_queryset_isolated(self):
        a_accounts = Account.objects.filter(user=self.user_a)
        b_accounts = Account.objects.filter(user=self.user_b)
        self.assertIn(self.acc_a, a_accounts)
        self.assertNotIn(self.acc_a, b_accounts)
        self.assertIn(self.acc_b, b_accounts)
        self.assertNotIn(self.acc_b, a_accounts)

    def test_transaction_not_accessible(self):
        income_cat_a = _make_category(self.user_a, 'Зарплата')
        tx = _make_transaction(
            self.user_a, self.acc_a, income_cat_a, '1000', Transaction.INCOME, date(2024, 1, 1)
        )
        # Запрос пользователя B не вернёт транзакцию пользователя A
        self.assertFalse(Transaction.objects.filter(user=self.user_b, pk=tx.pk).exists())
        # а пользователь A — вернёт
        self.assertTrue(Transaction.objects.filter(user=self.user_a, pk=tx.pk).exists())

    def test_pnl_isolated(self):
        income_cat_a = _make_category(self.user_a, 'Зарплата')
        _make_transaction(self.user_a, self.acc_a, income_cat_a, '1000', Transaction.INCOME, date(2024, 1, 1))
        pnl_a = calculate_pnl(self.user_a, date(2024, 1, 1), date(2024, 1, 31))
        pnl_b = calculate_pnl(self.user_b, date(2024, 1, 1), date(2024, 1, 31))
        self.assertEqual(pnl_a['transactions'], Decimal('1000.00'))
        self.assertEqual(pnl_b['transactions'], Decimal('0.00'))

    def test_net_worth_isolated(self):
        income_cat_a = _make_category(self.user_a, 'Зарплата')
        _make_transaction(self.user_a, self.acc_a, income_cat_a, '1000', Transaction.INCOME, date(2024, 1, 1))
        nw_a = calculate_net_worth(self.user_a, date(2024, 1, 31))
        nw_b = calculate_net_worth(self.user_b, date(2024, 1, 31))
        self.assertGreater(nw_a, Decimal('0'))
        self.assertEqual(nw_b, Decimal('0.00'))


class DefaultCategoriesTest(TestCase):
    def test_default_created_on_signup(self):
        u = _user('cats@x.com')
        cats = Category.objects.filter(user=u)
        self.assertEqual(cats.count(), 18)  # 12 расход + 6 доход
        self.assertTrue(cats.filter(name='Еда и продукты', type=Category.EXPENSE).exists())
        self.assertTrue(cats.filter(name='Зарплата', type=Category.INCOME).exists())

    def test_global_templates_created_once(self):
        _user('u1@x.com')
        _user('u2@x.com')
        globals_qs = Category.objects.filter(user__isnull=True, is_default=True)
        self.assertEqual(globals_qs.count(), 18)


# ---------------------------------------------------------------------------
# ТЗ «Объяснение P&L, разбивка Net Worth, структура капитала»
# ---------------------------------------------------------------------------

def _make_transaction(user, account, category, amount, ttype, dt):
    return Transaction.objects.create(
        user=user, account=account, category=category,
        amount=Decimal(str(amount)), type=ttype, date=dt,
    )


class PeriodHelpersTest(TestCase):
    def test_month_to_date_default(self):
        df, dt = month_to_date_range(date(2026, 8, 22))
        self.assertEqual(df, date(2026, 8, 1))
        self.assertEqual(dt, date(2026, 8, 22))

    def test_previous_equivalent_period_same_length(self):
        df, dt = date(2026, 8, 1), date(2026, 8, 22)
        pf, pt = previous_equivalent_period(df, dt)
        # ТЗ: для 01.08–22.08 предыдущий — 01.07–22.07 (эквивалент по числу дней)
        self.assertEqual(pf, date(2026, 7, 1))
        self.assertEqual(pt, date(2026, 7, 22))
        self.assertEqual((dt - df).days, (pt - pf).days)

    def test_previous_period_arbitrary_range_same_length(self):
        df, dt = date(2026, 8, 10), date(2026, 8, 20)
        pf, pt = previous_equivalent_period(df, dt)
        self.assertEqual((dt - df).days, (pt - pf).days)

    def test_period_label_month_to_date(self):
        self.assertEqual(period_label(date(2026, 8, 1), date(2026, 8, 22)), 'августа 2026')

    def test_period_label_custom_range(self):
        self.assertEqual(
            period_label(date(2026, 8, 10), date(2026, 8, 20)),
            '10.08.2026–20.08.2026',
        )

    def test_shift_months_clamps_end_of_month(self):
        from analytics.services import _shift_months
        # 31.03 −1 месяц → 28.02 (невысокосный 2026)
        self.assertEqual(_shift_months(date(2026, 3, 31), -1), date(2026, 2, 28))


class NetWorthBreakdownTest(TestCase):
    def setUp(self):
        self.user = _user('nw@x.com')
        self.acc = _make_account(self.user)
        self.income_cat = _make_category(self.user, 'Пополнение')
        _make_transaction(self.user, self.acc, self.income_cat, '300000',
                          Transaction.INCOME, date(2026, 8, 5))
        self.dep = Deposit.objects.create(
            user=self.user, name='Вклад',
            principal_amount=Decimal('1000000'), annual_rate=Decimal('12'),
            start_date=date(2026, 1, 1),
        )
        self.sec = Security.objects.create(
            user=self.user, name='Доля',
            acquisition_value=Decimal('500000'),
            acquisition_date=date(2026, 1, 1),
        )

    def test_breakdown_sums_equal_net_worth(self):
        as_of = date(2026, 8, 22)
        nw = calculate_net_worth(self.user, as_of)
        br = net_worth_breakdown(self.user, as_of)
        components_sum = sum(c['value'] for c in br['components'])
        self.assertEqual(components_sum.quantize(Decimal('0.01')), nw)
        self.assertEqual(br['total'], nw)

    def test_breakdown_percentages_sum_to_100(self):
        br = net_worth_breakdown(self.user, date(2026, 8, 22))
        self.assertGreater(br['total'], 0)
        self.assertEqual(sum(c['pct'] for c in br['all_components']), Decimal('100'))

    def test_breakdown_has_three_components(self):
        br = net_worth_breakdown(self.user, date(2026, 8, 22))
        labels = [c['key'] for c in br['all_components']]
        self.assertEqual(labels, ['accounts', 'deposits', 'securities'])

    def test_empty_component_excluded_from_active(self):
        # пользователь без бумаг: securities нет в активной разбивке
        sec_user = _user('nosec@x.com')
        acc = _make_account(sec_user, 'К')
        inc = _make_category(sec_user, 'Пополнение')
        _make_transaction(sec_user, acc, inc, '100000', Transaction.INCOME, date(2026, 8, 1))
        br = net_worth_breakdown(sec_user, date(2026, 8, 22))
        keys = [c['key'] for c in br['components']]
        self.assertNotIn('securities', keys)


class ExplainPnLTest(TestCase):
    def setUp(self):
        self.user = _user('expl@x.com')
        self.acc = _make_account(self.user)
        self.expense_cat = _make_category(self.user, 'Кафе и рестораны', Category.EXPENSE)
        self.expense_cat2 = _make_category(self.user, 'Транспорт', Category.EXPENSE)
        self.income_cat = _make_category(self.user, 'Зарплата')

    def test_summary_text_names_top_factor(self):
        # Зарплата стабильно в обоих периодах (вклад в изменение = 0)
        _make_transaction(self.user, self.acc, self.income_cat, '500000',
                          Transaction.INCOME, date(2026, 7, 5))
        _make_transaction(self.user, self.acc, self.income_cat, '500000',
                          Transaction.INCOME, date(2026, 8, 5))
        # Предыдущий период (июль): 100 000 на «Кафе»
        _make_transaction(self.user, self.acc, self.expense_cat, '100000',
                          Transaction.EXPENSE, date(2026, 7, 10))
        # Текущий (август): 420 000 на «Кафе» — резкий рост, это топ-фактор падения
        _make_transaction(self.user, self.acc, self.expense_cat, '420000',
                          Transaction.EXPENSE, date(2026, 8, 15))

        res = explain_pnl_change(self.user, date(2026, 8, 1), date(2026, 8, 22))
        # сводка упоминает топ-категорию
        self.assertIn('Кафе и рестораны', res['summary_text'])
        # топ-фактор — именно рост расходов по «Кафе»
        top = res['top_factors'][0]
        self.assertEqual(top['category'], 'Кафе и рестораны')
        # разница = 420000 - 100000 = 320000 (знаковый вклад в P&L: рост расходов → минус)
        self.assertEqual(top['delta'], Decimal('-320000.00'))
        # предыдущий период = 01.07–22.07 (эквивалент по длине)
        self.assertEqual(res['periods']['previous']['from'], date(2026, 7, 1))
        self.assertEqual(res['periods']['previous']['to'], date(2026, 7, 22))

    def test_summary_handles_zero_activity(self):
        res = explain_pnl_change(self.user, date(2026, 8, 1), date(2026, 8, 22))
        self.assertIn('0 UZS', res['summary_text'])

    def test_anomaly_detection(self):
        # История по «Кафе» за 6 месяцев: обычные ~50 000
        for m in range(2, 8):
            _make_transaction(self.user, self.acc, self.expense_cat, '50000',
                              Transaction.EXPENSE, date(2026, m, 10))
        # Текущий период: аномальная операция 500 000 (в 10 раз больше среднего)
        _make_transaction(self.user, self.acc, self.expense_cat, '500000',
                          Transaction.EXPENSE, date(2026, 8, 15))
        res = explain_pnl_change(self.user, date(2026, 8, 1), date(2026, 8, 22))
        self.assertTrue(res['anomalies'])
        a = res['anomalies'][0]
        self.assertEqual(a['category'], 'Кафе и рестораны')
        self.assertGreater(a['ratio'], Decimal('2'))
        self.assertEqual(a['amount'], Decimal('500000.00'))

    def test_components_breakdown_present(self):
        _make_transaction(self.user, self.acc, self.income_cat, '100000',
                          Transaction.INCOME, date(2026, 8, 5))
        res = explain_pnl_change(self.user, date(2026, 8, 1), date(2026, 8, 22))
        self.assertIn('operational', res['components'])
        self.assertIn('deposits', res['components'])
        self.assertIn('securities', res['components'])
        self.assertEqual(res['components']['operational']['current'], Decimal('100000.00'))

    def test_components_history_returns_six_periods(self):
        _make_transaction(self.user, self.acc, self.income_cat, '100000',
                          Transaction.INCOME, date(2026, 8, 5))
        hist = pnl_components_history(self.user, periods=6)
        self.assertEqual(len(hist), 6)
        self.assertEqual(set(hist[0].keys()),
                         {'label', 'operational', 'deposits', 'securities'})


class DashboardDefaultPeriodTest(TestCase):
    def test_dashboard_defaults_to_month_to_date(self):
        u = _user('dash@x.com')
        acc = _make_account(u)
        inc = _make_category(u, 'Зарплата')
        _make_transaction(u, acc, inc, '100000', Transaction.INCOME, date.today())
        self.client.force_login(u)
        r = self.client.get('/analytics/dashboard/')
        self.assertEqual(r.status_code, 200)
        # в контексте период = 1-е число текущего месяца .. сегодня
        from datetime import date as _d
        ctx = r.context
        self.assertEqual(ctx['date_from'], _d(_d.today().year, _d.today().month, 1).isoformat())
        self.assertEqual(ctx['date_to'], _d.today().isoformat())

    def test_dashboard_respects_query_period(self):
        u = _user('dash2@x.com')
        self.client.force_login(u)
        r = self.client.get('/analytics/dashboard/?date_from=2026-07-01&date_to=2026-07-31')
        ctx = r.context
        self.assertEqual(ctx['date_from'], '2026-07-01')
        self.assertEqual(ctx['date_to'], '2026-07-31')
