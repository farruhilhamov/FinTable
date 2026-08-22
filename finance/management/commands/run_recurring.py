"""
Management-команда для запуска регулярных операций (RecurringTemplate).

Запускать по cron/Task Scheduler ежедневно, например:
    0 1 * * * /path/to/python /path/to/manage.py run_recurring
"""
from datetime import date

from django.core.management.base import BaseCommand
from django.db import transaction

from finance.models import RecurringTemplate, Transaction


class Command(BaseCommand):
    help = 'Создаёт транзакции по активным регулярным шаблонам за сегодняшний день.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--date', type=str, default=None,
            help='Дата в формате YYYY-MM-DD (по умолчанию сегодня).',
        )

    @transaction.atomic
    def handle(self, *args, **opts):
        target = date.today()
        if opts['date']:
            target = date.fromisoformat(opts['date'])

        day = target.day
        # Берём шаблоны на этот день, а также шаблоны 31-го в месяцах без 31-го
        extra_days = []
        if day == 28 and target.month == 2 and not _is_leap(target.year):
            extra_days = [29, 30, 31]
        elif day == 30 and target.month in (2, 4, 6, 9, 11):
            pass
        days = {day} | set(extra_days)

        qs = RecurringTemplate.objects.filter(is_active=True, day_of_month__in=days)
        created = 0
        for tmpl in qs.select_related('user', 'account', 'category'):
            if tmpl.last_run is not None and tmpl.last_run >= target:
                continue
            Transaction.objects.create(
                user=tmpl.user,
                account=tmpl.account,
                category=tmpl.category,
                amount=tmpl.amount,
                type=tmpl.type,
                date=target,
                description=tmpl.description or f'Регулярная операция: {tmpl}',
            )
            tmpl.last_run = target
            tmpl.save(update_fields=['last_run', 'updated_at'])
            created += 1

        self.stdout.write(self.style.SUCCESS(
            f'Создано транзакций по регулярным шаблонам: {created} (на {target.isoformat()})'
        ))


def _is_leap(year: int) -> bool:
    return (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)
