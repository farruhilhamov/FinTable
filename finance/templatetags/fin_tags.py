from django import template
from decimal import Decimal

register = template.Library()


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
