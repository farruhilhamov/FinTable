"""
Management-команда для запуска регулярных операций (RecurringTemplate).

Запускать по cron / systemd-timer. Безопасно запускать часто (раз в час):
команда идемпотентна и догоняет пропущенные дни.

    0 * * * * cd /root/FinTable && venv/bin/python manage.py run_recurring >> /var/log/fintable_recurring.log 2>&1
"""
from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from finance.services import run_recurring_templates


class Command(BaseCommand):
    help = (
        'Создаёт транзакции по активным регулярным шаблонам за все пропущенные даты '
        'по указанную включительно.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--date', type=str, default=None,
            help='Дата в формате YYYY-MM-DD (по умолчанию — сегодня по TIME_ZONE проекта).',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Только показать, сколько операций было бы создано.',
        )

    def handle(self, *args, **opts):
        target = timezone.localdate()
        if opts['date']:
            try:
                target = date.fromisoformat(opts['date'])
            except ValueError as e:
                raise CommandError(f'Неверная дата: {e}')

        report = run_recurring_templates(target=target, dry_run=opts['dry_run'])
        prefix = '[dry-run] ' if opts['dry_run'] else ''
        self.stdout.write(self.style.SUCCESS(prefix + report.summary()))
        for err in report.errors:
            self.stderr.write(self.style.WARNING(err))

        if not opts['dry_run']:
            from deposits.services import close_matured_deposits
            dep = close_matured_deposits(today=target)
            self.stdout.write(self.style.SUCCESS(f'Закрыто вкладов по сроку: {dep["closed"]}'))
            for err in dep['errors']:
                self.stderr.write(self.style.WARNING(err))
