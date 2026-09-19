"""Тесты: переводы между счетами, бюджеты, быстрый ввод, поиск/теги, копирование."""
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from analytics.services import budget_status, calculate_pnl, savings_rate, upcoming_recurring
from finance.models import Account, Budget, Category, RecurringTemplate, Transaction

User = get_user_model()


class Base(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('feat@x.com', password='pass1234')
        self.card = Account.objects.create(user=self.user, name='Карта')
        self.cash = Account.objects.create(user=self.user, name='Наличные')
        self.income = Category.objects.get(user=self.user, name='Зарплата')
        self.food = Category.objects.get(user=self.user, name='Еда и продукты')
        self.client.force_login(self.user)

    def _tx(self, cat, amount, ttype, acc=None, dt=date(2026, 9, 5), **kw):
        return Transaction.objects.create(
            user=self.user, account=acc or self.card, category=cat,
            amount=Decimal(str(amount)), type=ttype, date=dt, **kw,
        )


class TransferTest(Base):
    def test_transfer_categories_created_for_new_user(self):
        cats = Category.objects.filter(user=self.user, is_transfer=True)
        self.assertEqual(cats.count(), 2)

    def test_transfer_creates_pair_and_moves_balance(self):
        self._tx(self.income, 1000, Transaction.INCOME)
        r = self.client.post('/finance/transfers/new/', {
            'from_account': self.card.id, 'to_account': self.cash.id,
            'amount': '300', 'date': '2026-09-10',
        })
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.card.balance(), Decimal('700'))
        self.assertEqual(self.cash.balance(), Decimal('300'))
        pair = Transaction.objects.filter(category__is_transfer=True)
        self.assertEqual(pair.count(), 2)
        out = pair.get(type=Transaction.EXPENSE)
        inc = pair.get(type=Transaction.INCOME)
        self.assertEqual(out.transfer_pair_id, inc.id)
        self.assertEqual(inc.transfer_pair_id, out.id)

    def test_transfer_excluded_from_pnl(self):
        self._tx(self.income, 1000, Transaction.INCOME)
        self.client.post('/finance/transfers/new/', {
            'from_account': self.card.id, 'to_account': self.cash.id,
            'amount': '300', 'date': '2026-09-10',
        })
        pnl = calculate_pnl(self.user, date(2026, 9, 1), date(2026, 9, 30))
        self.assertEqual(pnl['transactions'], Decimal('1000.00'))

    def test_same_account_rejected(self):
        r = self.client.post('/finance/transfers/new/', {
            'from_account': self.card.id, 'to_account': self.card.id,
            'amount': '300', 'date': '2026-09-10',
        })
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_delete_one_side_deletes_both(self):
        self.client.post('/finance/transfers/new/', {
            'from_account': self.card.id, 'to_account': self.cash.id,
            'amount': '300', 'date': '2026-09-10',
        })
        out = Transaction.objects.get(type=Transaction.EXPENSE)
        r = self.client.post(f'/finance/transactions/{out.id}/delete/')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_transfer_categories_hidden_in_transaction_form(self):
        r = self.client.get('/finance/transactions/new/')
        self.assertNotContains(r, Category.TRANSFER_NAME)


class BudgetTest(Base):
    def test_budget_status(self):
        Budget.objects.create(user=self.user, category=self.food, limit=Decimal('1000'))
        self._tx(self.food, 850, Transaction.EXPENSE)
        rows = budget_status(self.user, date(2026, 9, 1), date(2026, 9, 30))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['pct'], 85)
        self.assertEqual(rows[0]['status'], 'warning')
        self.assertEqual(rows[0]['left'], Decimal('150.00'))

    def test_budget_over(self):
        Budget.objects.create(user=self.user, category=self.food, limit=Decimal('100'))
        self._tx(self.food, 250, Transaction.EXPENSE)
        rows = budget_status(self.user, date(2026, 9, 1), date(2026, 9, 30))
        self.assertEqual(rows[0]['status'], 'over')
        self.assertEqual(rows[0]['bar_pct'], 100)

    def test_budget_form_rejects_income_category_and_duplicates(self):
        r = self.client.post('/finance/budgets/new/', {'category': self.income.id, 'limit': '10', 'is_active': 'on'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Budget.objects.count(), 0)
        self.client.post('/finance/budgets/new/', {'category': self.food.id, 'limit': '10', 'is_active': 'on'})
        self.assertEqual(Budget.objects.count(), 1)
        r = self.client.post('/finance/budgets/new/', {'category': self.food.id, 'limit': '20', 'is_active': 'on'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Budget.objects.count(), 1)

    def test_budget_page_and_dashboard_render(self):
        Budget.objects.create(user=self.user, category=self.food, limit=Decimal('1000'))
        self.assertEqual(self.client.get('/finance/budgets/').status_code, 200)
        r = self.client.get('/analytics/dashboard/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Бюджеты')


class QuickEntryTest(Base):
    def test_modal_partial_for_htmx(self):
        r = self.client.get('/finance/transactions/new/', HTTP_HX_REQUEST='true')
        self.assertTemplateUsed(r, 'finance/_transaction_modal.html')

    def test_remembers_last_account_and_category(self):
        self.client.post('/finance/transactions/new/', {
            'account': self.cash.id, 'category': self.food.id, 'amount': '10',
            'type': 'expense', 'date': '2026-09-05',
        })
        r = self.client.get('/finance/transactions/new/')
        self.assertEqual(r.context['form'].initial['account'], self.cash.id)
        self.assertEqual(r.context['form'].initial['category'], self.food.id)

    def test_copy_prefills(self):
        t = self._tx(self.food, 123, Transaction.EXPENSE, description='обед', tags='работа')
        r = self.client.get(f'/finance/transactions/new/?copy={t.id}')
        init = r.context['form'].initial
        self.assertEqual(init['amount'], Decimal('123'))
        self.assertEqual(init['description'], 'обед')
        self.assertEqual(init['tags'], 'работа')

    def test_tags_normalized(self):
        t = Transaction(user=self.user, account=self.card, category=self.food,
                        amount=Decimal('1'), type=Transaction.EXPENSE, date=date(2026, 9, 1),
                        tags=' такси , работа,такси ')
        t.full_clean()
        self.assertEqual(t.tags, 'такси, работа')


class SearchTest(Base):
    def test_search_by_description_and_tag(self):
        self._tx(self.food, 10, Transaction.EXPENSE, description='обед в кафе')
        self._tx(self.food, 20, Transaction.EXPENSE, description='рынок', tags='продукты, дом')
        r = self.client.get('/finance/transactions/?q=кафе&date_from=2026-09-01&date_to=2026-09-30')
        self.assertEqual(len(r.context['transactions']), 1)
        r = self.client.get('/finance/transactions/?q=дом&date_from=2026-09-01&date_to=2026-09-30')
        self.assertEqual(len(r.context['transactions']), 1)
        self.assertEqual(r.context['transactions'][0].amount, Decimal('20'))

    def test_totals_exclude_transfers(self):
        self._tx(self.income, 1000, Transaction.INCOME)
        self.client.post('/finance/transfers/new/', {
            'from_account': self.card.id, 'to_account': self.cash.id,
            'amount': '300', 'date': '2026-09-10',
        })
        r = self.client.get('/finance/transactions/?date_from=2026-09-01&date_to=2026-09-30')
        self.assertEqual(r.context['totals']['income'], Decimal('1000'))
        self.assertEqual(r.context['totals']['expense'], Decimal('0'))


class AnalyticsExtrasTest(Base):
    def test_savings_rate(self):
        self._tx(self.income, 1000, Transaction.INCOME)
        self._tx(self.food, 700, Transaction.EXPENSE)
        s = savings_rate(self.user, date(2026, 9, 1), date(2026, 9, 30))
        self.assertEqual(s['rate'], Decimal('30.0'))

    def test_upcoming_recurring(self):
        RecurringTemplate.objects.create(
            user=self.user, category=self.income, account=self.card, amount=Decimal('500'),
            type=Transaction.INCOME, day_of_month=20, start_date=date(2026, 9, 1),
        )
        RecurringTemplate.objects.create(
            user=self.user, category=self.food, account=self.card, amount=Decimal('100'),
            type=Transaction.EXPENSE, day_of_month=1, start_date=date(2026, 9, 1),
        )
        up = upcoming_recurring(self.user, days=7, today=date(2026, 9, 15))
        self.assertEqual(len(up['items']), 1)
        self.assertEqual(up['items'][0]['date'], date(2026, 9, 20))
        self.assertEqual(up['overdue'], 1)
        self.assertEqual(up['net'], Decimal('500'))
