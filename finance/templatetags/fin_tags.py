from django import template
from decimal import Decimal

register = template.Library()


def fmt_money(value, decimal_places=0):
    """Форматирует денежное значение с пробелом между тысячами.

    Примеры: 1000000 -> '1 000 000', 24254000 -> '24 254 000'.
    Если есть дробная часть, округляет до decimal_places (по умолчанию 0).
    """
    try:
        d = Decimal(str(value))
    except Exception:
        return str(value)
    q = Decimal('1') if decimal_places == 0 else Decimal('1').scaleb(-decimal_places)
    d = d.quantize(q)
    sign = '-' if d < 0 else ''
    s = format(abs(d), f',.{decimal_places}f')
    return sign + s.replace(',', '\u00A0')


@register.filter
def money(value, decimal_places=0):
    return fmt_money(value, decimal_places)


@register.filter
def sub(value, arg):
    try:
        return (Decimal(str(value)) - Decimal(str(arg))).quantize(Decimal('0.01'))
    except Exception:
        return value


@register.filter
def get_item(d, key):
    return d.get(key) if isinstance(d, dict) else None


@register.filter(name='mul')
def mul(value, arg):
    try:
        return (Decimal(str(value)) * Decimal(str(arg))).quantize(Decimal('0.01'))
    except Exception:
        return value
