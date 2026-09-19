"""Сервис вкладов: автоматическое закрытие по сроку."""
import logging
from datetime import date
from typing import Optional

from django.utils import timezone

from .models import Deposit

logger = logging.getLogger(__name__)


def close_matured_deposits(today: Optional[date] = None, user=None) -> dict:
    """Закрывает активные вклады с end_date <= today и auto_close=True."""
    today = today or timezone.localdate()
    qs = Deposit.objects.filter(status=Deposit.ACTIVE, auto_close=True, end_date__lte=today)
    if user is not None:
        qs = qs.filter(user=user)
    report = {'closed': 0, 'errors': []}
    for dep in qs.select_related('user', 'account'):
        try:
            dep.mature(dep.end_date)
            report['closed'] += 1
        except Exception as exc:  # noqa: BLE001
            logger.exception('close_matured_deposits: вклад #%s', dep.pk)
            report['errors'].append(f'Вклад #{dep.pk} «{dep.name}»: {exc}')
    return report
