from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from analytics.services import calculate_net_worth, net_worth_breakdown
from finance.models import Account, Category, RecurringTemplate, Transaction
from finance.services import run_recurring_templates
from .models import Liability

User = get_user_model()


class LiabilityTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('liab@x.com', password='pass1234')
        self.acc = Account.objects.create(user=self.user, name='Карта')
        sal = Category.objects.get(user=self.user, name='Зарплата')
        Transaction.objects.create(user=self.user, account=self.acc, category=sal,
                                   amount=Decimal('5000'), type='income', date=date(2026, 9, 1))
        self.client.force_login(self.user)

    def _loan(self, **kw):
        d = dict(user=self.user, name='Кредит', principal=Decimal('3000'), balance=Decimal('3000'),
                 monthly_payment=Decimal('1000'), payment_day=10, account=self.acc,
                 start_date=date(2026, 9, 1))
        d.update(kw)
        return Liability.objects.create(**d)

    def test_net_worth_subtracts_debt_and_adds_receivable(self):
        self._loan()
        self.assertEqual(calculate_net_worth(self.user), Decimal('2000.00'))
        self._loan(name='Друг должен', direction=Liability.OWED, principal=Decimal('500'), balance=Decimal('500'))
        self.assertEqual(calculate_net_worth(self.user), Decimal('2500.00'))
        br = net_worth_breakdown(self.user)
        self.assertEqual(br['liabilities']['value'], Decimal('-2500.00'))
        self.assertEqual([c['key'] for c in br['all_components']], ['accounts', 'deposits', 'securities'])

    def test_payment_reduces_balance_and_creates_expense(self):
        loan = self._loan()
        loan.apply_payment(Decimal('1000'), date(2026, 9, 10))
        loan.refresh_from_db()
        self.assertEqual(loan.balance, Decimal('2000'))
        tx = Transaction.objects.get(category__name='Погашение долгов')
        self.assertEqual(tx.type, Transaction.EXPENSE)
        self.assertEqual(self.acc.balance(), Decimal('4000'))

    def test_full_payment_closes(self):
        loan = self._loan(balance=Decimal('700'))
        loan.apply_payment(Decimal('1000'), date(2026, 9, 10))
        loan.refresh_from_db()
        self.assertEqual(loan.status, Liability.CLOSED)
        self.assertEqual(loan.balance, Decimal('0'))
        self.assertEqual(calculate_net_worth(self.user), Decimal('4000.00'))

    def test_recurring_autopayment_reduces_balance(self):
        loan = self._loan()
        tmpl = loan.ensure_recurring()
        self.assertIsNotNone(tmpl)
        self.assertEqual(tmpl.amount, Decimal('1000'))
        # шаблон стартует не раньше сегодняшнего дня: прошлые платежи не досоздаются
        self.assertGreaterEqual(tmpl.start_date, date.today())
        target = date(tmpl.start_date.year + 1, 1, 15)
        report = run_recurring_templates(target=target)
        self.assertGreaterEqual(report.created, 1)
        loan.refresh_from_db()
        self.assertEqual(loan.balance, Decimal('3000') - Decimal('1000') * report.created)
        # операции созданы один раз (не дублируются apply_payment)
        self.assertEqual(Transaction.objects.filter(recurring_template=tmpl).count(), report.created)
        self.assertEqual(Transaction.objects.filter(category__name='Погашение долгов').count(), report.created)

    def test_autopayment_deactivates_when_closed(self):
        loan = self._loan(balance=Decimal('800'))
        tmpl = loan.ensure_recurring()
        run_recurring_templates(target=date(tmpl.start_date.year + 1, 1, 15))
        loan.refresh_from_db()
        tmpl.refresh_from_db()
        self.assertEqual(loan.status, Liability.CLOSED)
        self.assertFalse(tmpl.is_active)

    def test_create_via_form_creates_recurring(self):
        r = self.client.post('/liabilities/new/', {
            'name': 'Ипотека', 'kind': 'loan', 'direction': 'owe', 'principal': '100000',
            'balance': '', 'annual_rate': '20', 'monthly_payment': '5000', 'payment_day': '15',
            'account': self.acc.id, 'start_date': '2026-09-01', 'create_recurring': 'on',
        })
        self.assertEqual(r.status_code, 302)
        l = Liability.objects.get(name='Ипотека')
        self.assertEqual(l.balance, Decimal('100000'))
        self.assertIsNotNone(l.recurring_template)
        self.assertTrue(RecurringTemplate.objects.filter(pk=l.recurring_template_id, is_active=True).exists())

    def test_months_left(self):
        l = self._loan(annual_rate=Decimal('0'))
        self.assertEqual(l.months_left(), 3)
        l2 = self._loan(name='x', annual_rate=Decimal('24'), monthly_payment=Decimal('50'))
        self.assertIsNone(l2.months_left())  # платёж не покрывает проценты

    def test_pages_render(self):
        self._loan()
        self.assertEqual(self.client.get('/liabilities/').status_code, 200)
        l = Liability.objects.first()
        self.assertEqual(self.client.get(f'/liabilities/{l.id}/pay/').status_code, 200)
        r = self.client.get('/analytics/dashboard/')
        self.assertContains(r, 'Долги и кредиты')
