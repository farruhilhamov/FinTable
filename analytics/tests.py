from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from deposits.models import Deposit
from finance.models import Account, Category, Transaction
from securities.models import Security, SecurityValuation
from analytics.services import calculate_pnl, calculate_net_worth

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
