from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from deposits.models import Deposit
from finance.models import Account, RecurringTemplate, Transaction
from onboarding.models import UserProfile
from securities.models import Security, SecurityValuation

User = get_user_model()

WP = 'onboarding_wizard'  # formtools wizard prefix (auto-derived)


def _step_data(step, fields):
    """Базовые данные POST для шага wizard (управляющая форма formtools)."""
    d = {f'{WP}-current_step': step}
    d.update(fields)
    return d


class WizardTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('wiz@x.com', password='pass1234')
        self.c = self.client
        self.c.login(username='wiz@x.com', password='pass1234')

    def _run_full_wizard(self, account_name='Кошелёк'):
        c = self.c
        # Шаг 1 — приветствие
        self.assertEqual(c.post('/wizard/step/1/', _step_data('1', {})).status_code, 302)
        # Шаг 2 — счета
        c.post('/wizard/step/2/', _step_data('2', {
            '2-TOTAL_FORMS': '2', '2-INITIAL_FORMS': '0',
            '2-MIN_NUM_FORMS': '0', '2-MAX_NUM_FORMS': '1000',
            '2-0-name': account_name, '2-0-type': 'cash', '2-0-balance': '100000',
            '2-1-name': '', '2-1-type': 'cash', '2-1-balance': '',
        }))
        # Шаг 3 — вклады
        c.post('/wizard/step/3/', _step_data('3', {
            '3-TOTAL_FORMS': '2', '3-INITIAL_FORMS': '0',
            '3-MIN_NUM_FORMS': '0', '3-MAX_NUM_FORMS': '1000',
            '3-0-name': 'ВкладА', '3-0-principal_amount': '1000000',
            '3-0-annual_rate': '12', '3-0-start_date': '2024-01-01',
            '3-0-capitalization_type': 'simple',
            '3-1-name': '', '3-1-principal_amount': '', '3-1-annual_rate': '',
            '3-1-start_date': '', '3-1-capitalization_type': 'simple',
        }))
        # Шаг 4 — бумаги
        c.post('/wizard/step/4/', _step_data('4', {
            '4-TOTAL_FORMS': '2', '4-INITIAL_FORMS': '0',
            '4-MIN_NUM_FORMS': '0', '4-MAX_NUM_FORMS': '1000',
            '4-0-name': 'Доля1', '4-0-acquisition_value': '500000',
            '4-0-current_value': '600000',
            '4-1-name': '', '4-1-acquisition_value': '', '4-1-current_value': '',
        }))
        # Шаг 5 — зарплата (последний шаг → redirect на done)
        r = c.post('/wizard/step/5/', _step_data('5', {
            '5-amount': '300000', '5-day_of_month': '10', '5-create_recurring': 'on',
        }))
        self.assertEqual(r.status_code, 302)
        # GET на /wizard/step/done/ запускает done()
        self.assertEqual(r.get('Location'), '/wizard/step/done/')
        done = c.get(r.get('Location'))
        self.assertEqual(done.status_code, 302)
        self.assertEqual(done.get('Location'), '/analytics/dashboard/')

    def test_full_wizard_creates_records(self):
        self._run_full_wizard()
        self.assertEqual(Account.objects.filter(user=self.user).count(), 1)
        # стартовый остаток создан как транзакция-пополнение
        self.assertTrue(
            Transaction.objects.filter(
                user=self.user, amount=Decimal('100000'),
                description__contains='Стартовый остаток',
            ).exists()
        )
        self.assertEqual(Deposit.objects.filter(user=self.user).count(), 1)
        sec = Security.objects.filter(user=self.user).first()
        self.assertIsNotNone(sec)
        self.assertEqual(
            SecurityValuation.objects.filter(security=sec).count(), 1
        )
        self.assertTrue(
            RecurringTemplate.objects.filter(user=self.user).exists()
        )
        self.assertTrue(UserProfile.objects.get(user=self.user).onboarding_completed)

    def test_cancel_delete_creates_no_records(self):
        c = self.c
        c.post('/wizard/step/1/', _step_data('1', {}))
        c.post('/wizard/step/2/', _step_data('2', {
            '2-TOTAL_FORMS': '2', '2-INITIAL_FORMS': '0',
            '2-MIN_NUM_FORMS': '0', '2-MAX_NUM_FORMS': '1000',
            '2-0-name': 'X', '2-0-type': 'cash', '2-0-balance': '500',
            '2-1-name': '', '2-1-type': 'cash', '2-1-balance': '',
        }))
        # на шаге 3 жмём «Отменить и удалить всё»
        r = c.post('/wizard/step/3/', _step_data('3', {'wizard_action': 'cancel_delete'}))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.get('Location'), '/analytics/dashboard/')
        # в БД нет ни одной записи за эту сессию
        self.assertEqual(Account.objects.filter(user=self.user).count(), 0)
        self.assertEqual(Deposit.objects.filter(user=self.user).count(), 0)
        self.assertEqual(Security.objects.filter(user=self.user).count(), 0)
        self.assertEqual(RecurringTemplate.objects.filter(user=self.user).count(), 0)
        self.assertFalse(UserProfile.objects.get(user=self.user).onboarding_completed)

    def test_cancel_save_persists_partial_data(self):
        c = self.c
        c.post('/wizard/step/1/', _step_data('1', {}))
        c.post('/wizard/step/2/', _step_data('2', {
            '2-TOTAL_FORMS': '2', '2-INITIAL_FORMS': '0',
            '2-MIN_NUM_FORMS': '0', '2-MAX_NUM_FORMS': '1000',
            '2-0-name': 'Сохранённый', '2-0-type': 'cash', '2-0-balance': '1000',
            '2-1-name': '', '2-1-type': 'cash', '2-1-balance': '',
        }))
        r = c.post('/wizard/step/3/', _step_data('3', {'wizard_action': 'cancel_save'}))
        self.assertEqual(r.status_code, 302)
        # частично сохранённые данные есть, но онбординг не завершён
        self.assertEqual(Account.objects.filter(user=self.user).count(), 1)
        self.assertFalse(UserProfile.objects.get(user=self.user).onboarding_completed)

    def test_skip_marks_profile(self):
        r = self.c.post('/wizard/step/1/', _step_data('1', {'wizard_action': 'skip'}))
        self.assertEqual(r.status_code, 302)
        p = UserProfile.objects.get(user=self.user)
        self.assertTrue(p.onboarding_completed)
        self.assertTrue(p.onboarding_skipped)

    def test_repeat_run_does_not_duplicate_or_modify_existing(self):
        # Первое прохождение
        self._run_full_wizard(account_name='Первый')
        first_account = Account.objects.get(user=self.user, name='Первый')
        first_account_pk = first_account.pk
        accounts_before = Account.objects.filter(user=self.user).count()
        # Повторный запуск wizard (режим добавления) с новым счётом
        c = self.c
        c.post('/wizard/step/1/', _step_data('1', {}))
        c.post('/wizard/step/2/', _step_data('2', {
            '2-TOTAL_FORMS': '2', '2-INITIAL_FORMS': '0',
            '2-MIN_NUM_FORMS': '0', '2-MAX_NUM_FORMS': '1000',
            '2-0-name': 'Второй', '2-0-type': 'card', '2-0-balance': '50000',
            '2-1-name': '', '2-1-type': 'cash', '2-1-balance': '',
        }))
        # шаг 3 без вкладов
        c.post('/wizard/step/3/', _step_data('3', {
            '3-TOTAL_FORMS': '1', '3-INITIAL_FORMS': '0',
            '3-MIN_NUM_FORMS': '0', '3-MAX_NUM_FORMS': '1000',
            '3-0-name': '', '3-0-principal_amount': '', '3-0-annual_rate': '',
            '3-0-start_date': '', '3-0-capitalization_type': 'simple',
        }))
        # шаг 4 без бумаг
        c.post('/wizard/step/4/', _step_data('4', {
            '4-TOTAL_FORMS': '1', '4-INITIAL_FORMS': '0',
            '4-MIN_NUM_FORMS': '0', '4-MAX_NUM_FORMS': '1000',
            '4-0-name': '', '4-0-acquisition_value': '', '4-0-current_value': '',
        }))
        # шаг 5 без зарплаты
        r = c.post('/wizard/step/5/', _step_data('5', {}))
        c.get(r.get('Location'))
        # существующий счёт не тронут, добавлен новый
        first_account.refresh_from_db()
        self.assertEqual(first_account.pk, first_account_pk)
        self.assertEqual(Account.objects.filter(user=self.user).count(), accounts_before + 1)
        self.assertTrue(Account.objects.filter(user=self.user, name='Второй').exists())

    def test_preview_matches_get_accrued_income(self):
        params = {
            'principal_amount': '1000000', 'annual_rate': '12',
            'start_date': '2024-01-01', 'capitalization_type': 'simple',
        }
        r = self.c.get('/onboarding/preview/?' + '&'.join(f'{k}={v}' for k, v in params.items()))
        self.assertEqual(r.status_code, 200)
        # расчёт через несохранённый экземпляр Deposit — тем же методом модели
        tmp = Deposit(
            user=self.user, principal_amount=Decimal('1000000'),
            annual_rate=Decimal('12'), start_date=date(2024, 1, 1),
            capitalization_type=Deposit.SIMPLE, status=Deposit.ACTIVE,
        )
        accrued = tmp.get_accrued_income()
        self.assertContains(r, str(accrued))
        self.assertContains(r, str((tmp.principal_amount + accrued).quantize(Decimal('0.01'))))


class RegistrationRedirectTestCase(TestCase):
    def test_signup_redirects_to_wizard(self):
        r = self.client.post('/signup/', {
            'email': 'new@x.com', 'password1': 'pass1234', 'password2': 'pass1234',
        })
        self.assertEqual(r.status_code, 302)
        # после регистрации — на первый шаг wizard
        loc = r.get('Location', '')
        self.assertTrue(loc.startswith('/wizard'))
        # профиль авто-создан, onboarding не завершён
        u = User.objects.get(email='new@x.com')
        self.assertFalse(u.profile.onboarding_completed)
