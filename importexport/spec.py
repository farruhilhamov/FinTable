"""
Единая спецификация импорта/экспорта CSV.

Для каждой модели описаны: человекочитаемые заголовки колонок, mapping
на имена полей модели, обязательность, тип данных, формат даты (ISO 8601),
и upsert-логика (по каким полям искать дубликаты).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional


@dataclass
class FieldSpec:
    header: str
    field: str
    required: bool = True
    type: str = 'text'     # text|decimal|date|bool|int|choice
    choices: Optional[Dict[str, str]] = None


@dataclass
class ModelSpec:
    app_label: str
    model_name: str
    verbose_name: str
    fields: List[FieldSpec]
    upsert_keys: List[str] = field(default_factory=list)
    fks: Dict[str, tuple] = field(default_factory=dict)


def _parse_decimal(v: str) -> Decimal:
    return Decimal(v.strip().replace(',', '.'))


def _parse_date(v: str) -> date:
    return datetime.fromisoformat(v.strip()).date()


def _parse_bool(v: str) -> bool:
    return v.strip().lower() in ('1', 'true', 'yes', 'да', 'y', 't')


def _parse_int(v: str) -> int:
    return int(v.strip())


PARSERS = {
    'text': lambda v: v,
    'decimal': _parse_decimal,
    'date': _parse_date,
    'bool': _parse_bool,
    'int': _parse_int,
    'choice': lambda v: v,
}


def get_specs() -> Dict[str, ModelSpec]:
    return {
        'accounts': ModelSpec(
            app_label='finance', model_name='Account', verbose_name='Счета',
            fields=[
                FieldSpec('Название', 'name'),
                FieldSpec('Тип', 'type', choices={'card': 'Карта', 'cash': 'Наличные', 'other': 'Другое'}),
                FieldSpec('Активен', 'is_active', required=False, type='bool'),
            ],
            upsert_keys=['name'],
        ),
        'categories': ModelSpec(
            app_label='finance', model_name='Category', verbose_name='Категории',
            fields=[
                FieldSpec('Название', 'name'),
                FieldSpec('Тип', 'type', choices={'income': 'Доход', 'expense': 'Расход'}),
                FieldSpec('Активна', 'is_active', required=False, type='bool'),
            ],
            upsert_keys=['name', 'type'],
        ),
        'transactions': ModelSpec(
            app_label='finance', model_name='Transaction', verbose_name='Транзакции',
            fields=[
                FieldSpec('Счёт', 'account', type='text'),
                FieldSpec('Категория', 'category', type='text'),
                FieldSpec('Сумма', 'amount', type='decimal'),
                FieldSpec('Тип', 'type', choices={'income': 'Доход', 'expense': 'Расход'}),
                FieldSpec('Дата', 'date', type='date'),
                FieldSpec('Описание', 'description', required=False),
            ],
            upsert_keys=['account', 'category', 'amount', 'date'],
            fks={
                'account': ('finance', 'Account', 'name'),
                'category': ('finance', 'Category', 'name'),
            },
        ),
        'deposits': ModelSpec(
            app_label='deposits', model_name='Deposit', verbose_name='Вклады',
            fields=[
                FieldSpec('Название', 'name'),
                FieldSpec('Счёт', 'account', required=False, type='text'),
                FieldSpec('Тело вклада', 'principal_amount', type='decimal'),
                FieldSpec('Годовая ставка %', 'annual_rate', type='decimal'),
                FieldSpec('Дата начала', 'start_date', type='date'),
                FieldSpec('Капитализация', 'capitalization_type',
                          choices={'simple': 'Простой процент',
                                   'monthly_compound': 'Ежемесячная капитализация'}),
                FieldSpec('Статус', 'status', required=False,
                          choices={'active': 'Активен', 'closed': 'Закрыт'}),
                FieldSpec('Дата закрытия', 'closed_date', required=False, type='date'),
            ],
            upsert_keys=['name'],
            fks={'account': ('finance', 'Account', 'name')},
        ),
        'securities': ModelSpec(
            app_label='securities', model_name='Security', verbose_name='Ценные бумаги',
            fields=[
                FieldSpec('Название', 'name'),
                FieldSpec('Стоимость приобретения', 'acquisition_value', type='decimal'),
                FieldSpec('Количество/доля', 'quantity_or_share', required=False, type='decimal'),
                FieldSpec('Дата приобретения', 'acquisition_date', type='date'),
            ],
            upsert_keys=['name'],
        ),
        'security_valuations': ModelSpec(
            app_label='securities', model_name='SecurityValuation', verbose_name='Переоценки бумаг',
            fields=[
                FieldSpec('Бумага', 'security', type='text'),
                FieldSpec('Оценка', 'value', type='decimal'),
                FieldSpec('Дата', 'date', type='date'),
            ],
            upsert_keys=['security', 'date'],
            fks={'security': ('securities', 'Security', 'name')},
        ),
        'recurring': ModelSpec(
            app_label='finance', model_name='RecurringTemplate', verbose_name='Регулярные шаблоны',
            fields=[
                FieldSpec('Категория', 'category', type='text'),
                FieldSpec('Счёт', 'account', type='text'),
                FieldSpec('Сумма', 'amount', type='decimal'),
                FieldSpec('Тип', 'type', choices={'income': 'Доход', 'expense': 'Расход'}),
                FieldSpec('День месяца', 'day_of_month', type='int'),
                FieldSpec('Описание', 'description', required=False),
                FieldSpec('Активен', 'is_active', required=False, type='bool'),
            ],
            upsert_keys=['category', 'account', 'amount', 'day_of_month'],
            fks={
                'category': ('finance', 'Category', 'name'),
                'account': ('finance', 'Account', 'name'),
            },
        ),
    }


# ---------- экспорт ----------

def serialize_value(value, spec: FieldSpec):
    if value is None:
        return ''
    if spec.type == 'date':
        return value.isoformat() if value else ''
    if spec.type == 'bool':
        return '1' if value else '0'
    if spec.type == 'decimal':
        return str(value)
    if spec.type == 'choice' and spec.choices:
        return spec.choices.get(value, str(value))
    return str(value)


def export_rows(user, spec: ModelSpec) -> List[List[str]]:
    from django.apps import apps as django_apps
    model = django_apps.get_model(spec.app_label, spec.model_name)
    qs = model.objects.filter(user=user)
    headers = [f.header for f in spec.fields]
    rows = [headers]
    for obj in qs.iterator():
        row = []
        for f in spec.fields:
            val = getattr(obj, f.field, None)
            if f.field in spec.fks:
                val = getattr(val, spec.fks[f.field][2], '') if val else ''
            row.append(serialize_value(val, f))
        rows.append(row)
    return rows


def export_all(user) -> Dict[str, List[List[str]]]:
    return {key: export_rows(user, spec) for key, spec in get_specs().items()}


# ---------- импорт ----------

def parse_row(row: List[str], spec: ModelSpec):
    errors: List[str] = []
    parsed: Dict = {}
    headers_count = len(spec.fields)
    if len(row) < headers_count:
        row = list(row) + [''] * (headers_count - len(row))
    for f, raw in zip(spec.fields, row):
        val = (raw or '').strip()
        if not val:
            if f.required:
                errors.append(f'Поле «{f.header}» обязательно')
            continue
        try:
            if f.type == 'choice' and f.choices:
                rev = {v: k for k, v in f.choices.items()}
                parsed[f.field] = rev.get(val, val)
            else:
                parsed[f.field] = PARSERS[f.type](val)
        except (ValueError, InvalidOperation) as e:
            errors.append(f'Поле «{f.header}»: неверный формат ({e})')
    return parsed, errors


def import_rows(user, spec: ModelSpec, rows: List[List[str]]) -> dict:
    """Импортирует данные. rows: [header_row, *data_rows].
    Возвращает отчёт {created, updated, errors: [{row, msg}]}.
    Не прерывает весь импорт из-за одной плохой строки.
    """
    from django.apps import apps as django_apps
    from django.db import transaction

    report = {'created': 0, 'updated': 0, 'errors': []}
    if not rows:
        report['errors'].append({'row': 0, 'msg': 'Пустой файл'})
        return report

    header = rows[0]
    expected = [f.header for f in spec.fields]
    if [h.strip() for h in header] != expected:
        report['errors'].append({
            'row': 0,
            'msg': 'Заголовки не совпадают. Ожидались: ' + '; '.join(expected),
        })
        return report

    model = django_apps.get_model(spec.app_label, spec.model_name)

    fk_cache: Dict[str, Dict[str, object]] = {}
    for fk_field, (al, mn, lookup) in spec.fks.items():
        fk_model = django_apps.get_model(al, mn)
        fk_cache[fk_field] = {
            str(getattr(o, lookup)): o
            for o in fk_model.objects.filter(user=user).only('pk', lookup)
        }

    data_rows = rows[1:]
    for idx, raw_row in enumerate(data_rows, start=2):
        parsed, errs = parse_row(raw_row, spec)
        if errs:
            for e in errs:
                report['errors'].append({'row': idx, 'msg': e})
            continue

        fk_resolved = True
        for fk_field in spec.fks:
            name_val = parsed.get(fk_field)
            if name_val is None:
                continue
            obj = fk_cache.get(fk_field, {}).get(name_val)
            if obj is None:
                report['errors'].append({
                    'row': idx,
                    'msg': f'Не найдена связанная запись «{fk_field}»: {name_val}',
                })
                fk_resolved = False
            else:
                parsed[fk_field + '_id'] = obj.pk
                parsed.pop(fk_field)
        if not fk_resolved:
            continue

        try:
            with transaction.atomic():
                qs = model.objects.filter(user=user)
                lookup = {}
                for k in spec.upsert_keys:
                    if k in spec.fks:
                        if (k + '_id') in parsed:
                            lookup[k + '_id'] = parsed[k + '_id']
                    elif k in parsed:
                        lookup[k] = parsed[k]
                existing = qs.filter(**lookup).first() if lookup else None
                if existing is not None:
                    for k, v in parsed.items():
                        setattr(existing, k, v)
                    existing.full_clean(exclude=['user'])
                    existing.save()
                    report['updated'] += 1
                else:
                    obj = model(user=user, **parsed)
                    obj.full_clean(exclude=['user'])
                    obj.save()
                    report['created'] += 1
        except Exception as e:
            report['errors'].append({'row': idx, 'msg': f'Ошибка сохранения: {e}'})

    return report
