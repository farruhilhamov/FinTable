"""Тесты регулярных шаблонов: расчёт дат, сервис выполнения, команда, UI."""
from datetime import date
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase

from finance.models import Account, Category, RecurringTemplate, Transaction
from finance.services import run_recurring_templates

User = get_user_model()


class RecurringBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('rec@x.com', password='pass1234')
        self.acc = Account.objects.create(user=self.user, name='Карта')
        self.income = Category.objects.get(user=self.user, name='Зарплата')
        self.expense = Category.objects.get(user=self.user, name='Кафе и рестораны')

    def _tmpl(self, day=10, start=date(2026, 1, 1), **kw):
        defaults = dict(
            user=self.user, category=self.income, account=self.acc,
            amount=Decimal('1000'), type=Transaction.INCOME,
            day_of_month=day, start_date=start,
        )
        defaults.update(kw)
        return RecurringTemplate.objects.create(**defaults)


class DueDatesTest(RecurringBase):
    def test_normal_day(self):
        t = self._tmpl(day=10, start=date(2026, 3, 1))
        self.assertEqual(t.due_dates(date(2026, 3, 10)), [date(2026, 3, 10)])
        self.assertEqual(t.due_dates(date(2026, 3, 9)), [])

    def test_31st_in_30_day_month(self):
        t = self._tmpl(day=31, start=date(2026, 4, 1))
        self.assertEqual(t.due_dates(date(2026, 4, 30)), [date(2026, 4, 30)])

    def test_31st_in_february_leap_and_non_leap(self):
        t = self._tmpl(day=31, start=date(2024, 2, 1))
        self.assertEqual(t.due_dates(date(2024, 2, 29)), [date(2024, 2, 29)])
        t2 = self._tmpl(day=30, start=date(2026, 2, 1))
        self.assertEqual(t2.due_dates(date(2026, 2, 28)), [date(2026, 2, 28)])

    def test_backfill_multiple_months(self):
        t = self._tmpl(day=5, start=date(2026, 1, 1))
        self.assertEqual(
            t.due_dates(date(2026, 3, 20)),
            [date(2026, 1, 5), date(2026, 2, 5), date(2026, 3, 5)],
        )

    def test_last_run_moves_anchor(self):
        t = self._tmpl(day=5, start=date(2026, 1, 1), last_run=date(2026, 2, 5))
        self.assertEqual(t.due_dates(date(2026, 3, 20)), [date(2026, 3, 5)])

    def test_start_date_in_future(self):
        t = self._tmpl(day=5, start=date(2027, 1, 1))
        self.assertEqual(t.due_dates(date(2026, 12, 31)), [])

    def test_next_run_date(self):
        t = self._tmpl(day=5, start=date(2026, 1, 1))
        self.assertEqual(t.next_run_date(date(2026, 3, 6)), date(2026, 4, 5))
        self.assertEqual(t.next_run_date(date(2026, 3, 5)), date(2026, 3, 5))
        t.is_active = False
        self.assertIsNone(t.next_run_date(date(2026, 3, 5)))


class ValidationTest(RecurringBase):
    def test_day_of_month_range(self):
        for bad in (0, 32):
            t = RecurringTemplate(
                user=self.user, category=self.income, account=self.acc,
                amount=Decimal('1'), type=Transaction.INCOME, day_of_month=bad,
            )
            with self.assertRaises(ValidationError):
                t.full_clean()

    def test_type_must_match_category(self):
        t = RecurringTemplate(
            user=self.user, category=self.expense, account=self.acc,
            amount=Decimal('1'), type=Transaction.INCOME, day_of_month=1,
        )
        with self.assertRaises(ValidationError) as cm:
            t.full_clean()
        self.assertIn('type', cm.exception.message_dict)

    def test_form_rejects_bad_day(self):
        self.client.force_login(self.user)
        r = self.client.post('/finance/recurring/new/', {
            'category': self.income.id, 'account': self.acc.id, 'amount': '100',
            'type': 'income', 'day_of_month': '40', 'start_date': '2026-01-01', 'is_active': 'on',
        })
        self.assertEqual(r.status_code, 200)
        self.assertEqual(RecurringTemplate.objects.count(), 0)


class RunServiceTest(RecurringBase):
    def test_creates_backfilled_transactions_and_sets_last_run(self):
        t = self._tmpl(day=5, start=date(2026, 1, 1))
        report = run_recurring_templates(target=date(2026, 3, 20))
        self.assertEqual(report.created, 3)
        self.assertEqual(Transaction.objects.filter(recurring_template=t).count(), 3)
        t.refresh_from_db()
        self.assertEqual(t.last_run, date(2026, 3, 5))

    def test_idempotent(self):
        self._tmpl(day=5, start=date(2026, 1, 1))
        run_recurring_templates(target=date(2026, 3, 20))
        report = run_recurring_templates(target=date(2026, 3, 20))
        self.assertEqual(report.created, 0)
        self.assertEqual(Transaction.objects.count(), 3)

    def test_duplicate_guarded_by_constraint(self):
        t = self._tmpl(day=5, start=date(2026, 1, 1))
        # Операция уже есть (например, создана вручную с привязкой к шаблону)
        Transaction.objects.create(
            user=self.user, account=self.acc, category=self.income,
            amount=Decimal('1000'), type=Transaction.INCOME, date=date(2026, 1, 5),
            recurring_template=t,
        )
        report = run_recurring_templates(target=date(2026, 1, 31))
        self.assertEqual(report.created, 0)
        self.assertEqual(report.skipped, 1)
        self.assertEqual(Transaction.objects.count(), 1)

    def test_bad_template_does_not_break_others(self):
        good = self._tmpl(day=1, start=date(2026, 1, 1))
        bad = self._tmpl(day=1, start=date(2026, 1, 1))
        # Ломаем тип в обход валидации
        RecurringTemplate.objects.filter(pk=bad.pk).update(type=Transaction.EXPENSE)
        report = run_recurring_templates(target=date(2026, 1, 1))
        self.assertEqual(report.created, 1)
        self.assertEqual(len(report.errors), 1)
        self.assertTrue(Transaction.objects.filter(recurring_template=good).exists())
        self.assertFalse(Transaction.objects.filter(recurring_template=bad).exists())

    def test_inactive_account_or_category_skipped(self):
        self.acc.is_active = False
        self.acc.save()
        self._tmpl(day=1, start=date(2026, 1, 1))
        report = run_recurring_templates(target=date(2026, 1, 1))
        self.assertEqual(report.created, 0)
        self.assertEqual(len(report.errors), 1)

    def test_inactive_template_ignored(self):
        self._tmpl(day=1, start=date(2026, 1, 1), is_active=False)
        report = run_recurring_templates(target=date(2026, 1, 1))
        self.assertEqual(report.created, 0)

    def test_user_scoping(self):
        other = User.objects.create_user('other@x.com', password='pass1234')
        other_acc = Account.objects.create(user=other, name='Другой')
        other_cat = Category.objects.get(user=other, name='Зарплата')
        RecurringTemplate.objects.create(
            user=other, category=other_cat, account=other_acc, amount=Decimal('5'),
            type=Transaction.INCOME, day_of_month=1, start_date=date(2026, 1, 1),
        )
        self._tmpl(day=1, start=date(2026, 1, 1))
        report = run_recurring_templates(target=date(2026, 1, 1), user=self.user)
        self.assertEqual(report.created, 1)
        self.assertEqual(Transaction.objects.filter(user=other).count(), 0)

    def test_dry_run_creates_nothing(self):
        self._tmpl(day=1, start=date(2026, 1, 1))
        report = run_recurring_templates(target=date(2026, 2, 1), dry_run=True)
        self.assertEqual(report.created, 2)
        self.assertEqual(Transaction.objects.count(), 0)


class CommandTest(RecurringBase):
    def test_command_runs(self):
        self._tmpl(day=5, start=date(2026, 1, 1))
        out = StringIO()
        call_command('run_recurring', date='2026-02-10', stdout=out)
        self.assertIn('Создано операций: 2', out.getvalue())
        self.assertEqual(Transaction.objects.count(), 2)


class RunNowViewTest(RecurringBase):
    def test_run_now_button(self):
        t = self._tmpl(day=1, start=date(2026, 1, 1))
        self.client.force_login(self.user)
        r = self.client.post(f'/finance/recurring/{t.id}/run/')
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Transaction.objects.filter(recurring_template=t).exists())

    def test_run_now_other_users_template_404(self):
        other = User.objects.create_user('o2@x.com', password='pass1234')
        acc = Account.objects.create(user=other, name='X')
        cat = Category.objects.get(user=other, name='Зарплата')
        t = RecurringTemplate.objects.create(
            user=other, category=cat, account=acc, amount=Decimal('5'),
            type=Transaction.INCOME, day_of_month=1, start_date=date(2026, 1, 1),
        )
        self.client.force_login(self.user)
        r = self.client.post(f'/finance/recurring/{t.id}/run/')
        self.assertEqual(r.status_code, 404)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_list_shows_overdue_badge(self):
        self._tmpl(day=1, start=date(2026, 1, 1))
        self.client.force_login(self.user)
        r = self.client.get('/finance/recurring/')
        self.assertContains(r, 'пропущено')
