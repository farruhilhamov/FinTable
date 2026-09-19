from datetime import date
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from analytics.services import calculate_net_worth
from finance.models import Account, Transaction
from .models import Deposit
from .services import close_matured_deposits

User = get_user_model()


class DepositMaturityTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('dep@x.com', password='pass1234')
        self.acc = Account.objects.create(user=self.user, name='Карта')
        self.client.force_login(self.user)

    def _dep(self, **kw):
        d = dict(user=self.user, name='Вклад 12%', account=self.acc, principal_amount=Decimal('1000000'),
                 annual_rate=Decimal('12'), start_date=date(2025, 9, 1), end_date=date(2026, 9, 1),
                 capitalization_type=Deposit.SIMPLE)
        d.update(kw)
        return Deposit.objects.create(**d)

    def test_matured_deposit_closes_and_pays_out(self):
        dep = self._dep()
        nw_before = calculate_net_worth(self.user, date(2026, 8, 31))
        report = close_matured_deposits(today=date(2026, 9, 5))
        self.assertEqual(report['closed'], 1)
        dep.refresh_from_db()
        self.assertEqual(dep.status, Deposit.CLOSED)
        self.assertEqual(dep.closed_date, date(2026, 9, 1))
        txs = Transaction.objects.filter(user=self.user).order_by('id')
        self.assertEqual(txs.count(), 2)
        self.assertEqual(txs[0].amount, Decimal('1000000'))
        self.assertEqual(txs[0].category.name, 'Пополнение')
        self.assertEqual(txs[1].category.name, 'Доход от вклада')
        self.assertGreater(txs[1].amount, Decimal('119000'))  # ≈ 12% за год
        # Net Worth не обрушился: деньги переехали на счёт
        nw_after = calculate_net_worth(self.user, date(2026, 9, 5))
        self.assertGreater(nw_after, nw_before)

    def test_not_matured_untouched(self):
        self._dep(end_date=date(2027, 1, 1))
        report = close_matured_deposits(today=date(2026, 9, 5))
        self.assertEqual(report['closed'], 0)

    def test_auto_close_off(self):
        self._dep(auto_close=False)
        report = close_matured_deposits(today=date(2026, 9, 5))
        self.assertEqual(report['closed'], 0)

    def test_no_account_closes_without_transactions(self):
        self._dep(account=None)
        close_matured_deposits(today=date(2026, 9, 5))
        self.assertEqual(Transaction.objects.count(), 0)
        self.assertEqual(Deposit.objects.get().status, Deposit.CLOSED)

    def test_command_runs_maturity(self):
        self._dep()
        out = StringIO()
        call_command('run_recurring', date='2026-09-05', stdout=out)
        self.assertIn('Закрыто вкладов по сроку: 1', out.getvalue())

    def test_manual_close_with_payout(self):
        dep = self._dep(end_date=None)
        r = self.client.post(f'/deposits/{dep.id}/close/', {'payout': '1'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Transaction.objects.count(), 2)

    def test_form_rejects_end_before_start(self):
        r = self.client.post('/deposits/new/', {
            'name': 'x', 'principal_amount': '100', 'annual_rate': '10',
            'start_date': '2026-09-01', 'end_date': '2026-08-01', 'capitalization_type': 'simple', 'auto_close': 'on',
        })
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Deposit.objects.count(), 0)
