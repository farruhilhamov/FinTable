"""Сервисный слой finance: выполнение регулярных шаблонов.

Используется management-командой ``run_recurring`` и кнопкой «Выполнить сейчас» в UI.
"""
import logging
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import RecurringTemplate, Transaction

logger = logging.getLogger(__name__)


@dataclass
class RecurringRunReport:
    target: date
    created: int = 0
    skipped: int = 0
    errors: List[str] = field(default_factory=list)
    created_transactions: List[Transaction] = field(default_factory=list)

    def summary(self) -> str:
        msg = (
            f'Создано операций: {self.created}, пропущено дублей: {self.skipped} '
            f'(по {self.target.isoformat()})'
        )
        if self.errors:
            msg += f', ошибок: {len(self.errors)}'
        return msg


def run_template(
    tmpl: RecurringTemplate, target: date, report: RecurringRunReport, dry_run: bool = False
) -> None:
    """Создаёт все пропущенные операции одного шаблона по дату target включительно.

    Каждый шаблон обрабатывается в собственной транзакции с блокировкой строки,
    чтобы параллельные запуски (cron + кнопка в UI) не создавали дублей.
    Ошибка одного шаблона не влияет на остальные.
    """
    try:
        with transaction.atomic():
            locked = (
                RecurringTemplate.objects.select_for_update()
                .select_related('user', 'account', 'category')
                .get(pk=tmpl.pk)
            )
            if not locked.is_active:
                return
            if not locked.account.is_active or not locked.category.is_active:
                report.errors.append(
                    f'Шаблон #{locked.pk} «{locked}»: счёт или категория неактивны — пропущен'
                )
                return
            if locked.category.type != locked.type:
                report.errors.append(
                    f'Шаблон #{locked.pk} «{locked}»: тип операции не совпадает '
                    'с типом категории — пропущен'
                )
                return
            dates = locked.due_dates(target)
            if not dates:
                return
            for d in dates:
                if dry_run:
                    report.created += 1
                    continue
                try:
                    with transaction.atomic():
                        tx = Transaction.objects.create(
                            user=locked.user,
                            account=locked.account,
                            category=locked.category,
                            amount=locked.amount,
                            type=locked.type,
                            date=d,
                            description=locked.description or f'Регулярная операция: {locked}',
                            recurring_template=locked,
                        )
                except IntegrityError:
                    # Уже есть операция по этому шаблону на эту дату.
                    report.skipped += 1
                    continue
                report.created += 1
                report.created_transactions.append(tx)
            if not dry_run:
                locked.last_run = dates[-1]
                locked.save(update_fields=['last_run', 'updated_at'])
    except Exception as exc:  # noqa: BLE001 — один шаблон не должен ронять весь прогон
        logger.exception('run_recurring: ошибка шаблона #%s', tmpl.pk)
        report.errors.append(f'Шаблон #{tmpl.pk}: {exc}')


def run_recurring_templates(
    target: Optional[date] = None,
    user=None,
    template_ids: Optional[List[int]] = None,
    dry_run: bool = False,
) -> RecurringRunReport:
    """Выполняет все активные шаблоны (или шаблоны пользователя / по id) по дату target.

    Догоняет пропущенные даты: если cron не работал неделю, будут созданы все
    операции за эту неделю.
    """
    target = target or timezone.localdate()
    report = RecurringRunReport(target=target)
    qs = RecurringTemplate.objects.filter(is_active=True)
    if user is not None:
        qs = qs.filter(user=user)
    if template_ids:
        qs = qs.filter(pk__in=template_ids)
    for tmpl in qs.order_by('pk'):
        run_template(tmpl, target, report, dry_run=dry_run)
    logger.info('run_recurring: %s', report.summary())
    return report
