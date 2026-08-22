from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from deposits.models import Deposit
from finance.models import Account, Category, Transaction

User = get_user_model()


def _user(email, password='pass1234'):
    return User.objects.create_user(email=email, password=password)


class DepositAccruedIncomeTest(TestCase):
    def setUp(self):
        self.user = _user('a@x.com')
        self.dep = Deposit.objects.create(
            user=self.user,
            name='Вклад',
            principal_amount=Decimal('1000000'),
            annual_rate=Decimal('12'),
            start_date=date(2023, 1, 1),
            capitalization_type=Deposit.SIMPLE,
        )

    def test_simple_interest(self):
        # 365 дней → полный (невысокосный) год: 1_000_000 * 12% = 120_000
        as_of = date(2024, 1, 1)
        accrued = self.dep.get_accrued_income(as_of)
        self.assertEqual(accrued, Decimal('120000.00'))

    def test_simple_partial(self):
        # 31 день января (с 2023-01-01 по 2023-02-01)
        accrued = self.dep.get_accrued_income(date(2023, 2, 1))
        expected = (Decimal('1000000') * Decimal('0.12') * Decimal('31') / Decimal('365'))
        self.assertEqual(accrued, expected.quantize(Decimal('0.01')))

    def test_monthly_compound(self):
        self.dep.capitalization_type = Deposit.MONTHLY_COMPOUND
        self.dep.save()
        # 12 месяцев: 1_000_000 * (1 + 0.12/12)^12 - 1_000_000
        accrued = self.dep.get_accrued_income(date(2024, 1, 1))
        expected = (
            Decimal('1000000')
            * (Decimal('1') + Decimal('0.12') / Decimal('12')) ** 12
            - Decimal('1000000')
        ).quantize(Decimal('0.01'))
        self.assertEqual(accrued, expected)

    def test_before_start_returns_zero(self):
        self.assertEqual(self.dep.get_accrued_income(date(2022, 12, 31)), Decimal('0'))

    def test_current_balance(self):
        # баланс = principal + accrued
        bal = self.dep.current_balance
        self.assertEqual(bal, Decimal('1000000') + self.dep.get_accrued_income())
