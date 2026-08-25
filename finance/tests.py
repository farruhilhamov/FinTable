from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from finance.models import Account, Category, Transaction

User = get_user_model()


class AccountBalanceAdjustmentTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('acc@x.com', password='pass1234')
        self.acc = Account.objects.create(user=self.user, name='Кошелёк')
        self.income = Category.objects.get(user=self.user, name='Зарплата')
        self.expense = Category.objects.get(user=self.user, name='Кафе и рестораны')
        self.client.force_login(self.user)

    def _tx(self, category, amount, ttype, dt=date(2026, 8, 5)):
        Transaction.objects.create(
            user=self.user, account=self.acc, category=category,
            amount=Decimal(str(amount)), type=ttype, date=dt,
        )

    def test_increase_balance_creates_income_adjustment(self):
        self._tx(self.income, '500000', Transaction.INCOME)
        self.assertEqual(self.acc.balance(), Decimal('500000'))
        r = self.client.post(f'/finance/accounts/{self.acc.id}/balance/', {'balance': '900000'})
        self.assertEqual(r.status_code, 302)
        self.acc.refresh_from_db()
        # баланс стал целевым
        self.assertEqual(self.acc.balance(), Decimal('900000'))
        # создана корректирующая транзакция дохода
        self.assertTrue(
            Transaction.objects.filter(
                user=self.user, account=self.acc,
                description='Корректировка баланса', type=Transaction.INCOME,
            ).exists()
        )

    def test_decrease_balance_creates_expense_adjustment(self):
        self._tx(self.income, '1000000', Transaction.INCOME)
        r = self.client.post(f'/finance/accounts/{self.acc.id}/balance/', {'balance': '400000'})
        self.assertEqual(r.status_code, 302)
        self.acc.refresh_from_db()
        self.assertEqual(self.acc.balance(), Decimal('400000'))
        self.assertTrue(
            Transaction.objects.filter(
                user=self.user, account=self.acc,
                description='Корректировка баланса', type=Transaction.EXPENSE,
            ).exists()
        )

    def test_same_balance_no_adjustment(self):
        self._tx(self.income, '500000', Transaction.INCOME)
        count_before = Transaction.objects.filter(user=self.user).count()
        r = self.client.post(f'/finance/accounts/{self.acc.id}/balance/', {'balance': '500000'})
        self.assertEqual(r.status_code, 302)
        self.acc.refresh_from_db()
        self.assertEqual(self.acc.balance(), Decimal('500000'))
        self.assertEqual(Transaction.objects.filter(user=self.user).count(), count_before)

    def test_cannot_adjust_other_users_account(self):
        other = User.objects.create_user('other@x.com', password='x123456')
        other_acc = Account.objects.create(user=other, name='Чужой')
        r = self.client.post(f'/finance/accounts/{other_acc.id}/balance/', {'balance': '1000'})
        self.assertEqual(r.status_code, 404)


class TransactionsDefaultPeriodTest(TestCase):
    def test_defaults_to_current_month(self):
        u = User.objects.create_user('tx@x.com', password='pass1234')
        self.client.force_login(u)
        r = self.client.get('/finance/transactions/')
        cd = getattr(r, 'context_data', None)
        self.assertIsNotNone(cd)
        today = date.today()
        self.assertEqual(cd['filters']['date_from'], date(today.year, today.month, 1).isoformat())
        self.assertEqual(cd['filters']['date_to'], today.isoformat())


class MoneyFormatTest(TestCase):
    def test_money_filter(self):
        from finance.templatetags.fin_tags import fmt_money
        self.assertEqual(fmt_money(1000000), '1\u00a0000\u00a0000')
        self.assertEqual(fmt_money(24254000), '24\u00a0254\u00a0000')
        self.assertEqual(fmt_money(Decimal('-1234567.89'), 2), '-1\u00a0234\u00a0567.89')
