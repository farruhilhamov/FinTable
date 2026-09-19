from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from deposits.models import Deposit
from finance.models import Account, Category, Transaction
from .models import Goal

User = get_user_model()


class GoalTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('goal@x.com', password='pass1234')
        self.acc = Account.objects.create(user=self.user, name='Копилка')
        sal = Category.objects.get(user=self.user, name='Зарплата')
        Transaction.objects.create(user=self.user, account=self.acc, category=sal,
                                   amount=Decimal('2500'), type='income', date=date(2026, 9, 1))
        self.client.force_login(self.user)

    def test_progress_from_account(self):
        g = Goal.objects.create(user=self.user, name='Машина', target_amount=Decimal('10000'),
                                account=self.acc, deadline=date(2026, 12, 15))
        today = date(2026, 9, 19)
        self.assertEqual(g.current_amount(today), Decimal('2500'))
        self.assertEqual(g.progress_pct(today), 25)
        self.assertEqual(g.remaining(today), Decimal('7500'))
        self.assertEqual(g.months_left(today), 3)  # сен (день 15 < 19 → не считается), окт, ноя, дек
        self.assertEqual(g.required_monthly(today), Decimal('2500'))

    def test_progress_from_deposit(self):
        dep = Deposit.objects.create(user=self.user, name='Вклад', principal_amount=Decimal('1000'),
                                     annual_rate=Decimal('0'), start_date=date(2026, 1, 1))
        g = Goal.objects.create(user=self.user, name='Отпуск', target_amount=Decimal('4000'), deposit=dep)
        self.assertEqual(g.current_amount(date(2026, 9, 1)), Decimal('1000'))

    def test_manual_topup_and_done(self):
        g = Goal.objects.create(user=self.user, name='Подушка', target_amount=Decimal('300'))
        r = self.client.post(f'/goals/{g.id}/topup/', {'amount': '200'})
        self.assertEqual(r.status_code, 302)
        g.refresh_from_db()
        self.assertEqual(g.saved_manual, Decimal('200'))
        self.assertEqual(g.status, Goal.ACTIVE)
        self.client.post(f'/goals/{g.id}/topup/', {'amount': '100'})
        g.refresh_from_db()
        self.assertEqual(g.status, Goal.DONE)

    def test_eta(self):
        g = Goal.objects.create(user=self.user, name='x', target_amount=Decimal('1000'), saved_manual=Decimal('400'))
        self.assertEqual(g.eta(Decimal('200'), date(2026, 9, 19)), date(2026, 12, 19))
        self.assertIsNone(g.eta(Decimal('0'), date(2026, 9, 19)))

    def test_form_rejects_both_account_and_deposit(self):
        dep = Deposit.objects.create(user=self.user, name='Вклад', principal_amount=Decimal('1000'),
                                     annual_rate=Decimal('0'), start_date=date(2026, 1, 1))
        r = self.client.post('/goals/new/', {
            'name': 'x', 'target_amount': '100', 'account': self.acc.id, 'deposit': dep.id, 'saved_manual': '0',
        })
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Goal.objects.count(), 0)

    def test_pages_render(self):
        Goal.objects.create(user=self.user, name='Машина', target_amount=Decimal('10000'), account=self.acc)
        self.assertEqual(self.client.get('/goals/').status_code, 200)
        r = self.client.get('/analytics/dashboard/')
        self.assertContains(r, 'Машина')
