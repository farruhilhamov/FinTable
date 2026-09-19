from django.db.models.signals import post_save
from django.dispatch import receiver

from accounts.models import User
from finance.models import Category
from finance.default_categories import DEFAULT_CATEGORIES


@receiver(post_save, sender=User)
def create_default_categories(sender, instance, created, **kwargs):
    """Создаёт копии дефолтных категорий для нового пользователя.

    Дефолтные категории-шаблоны хранятся как глобальные (user=None, is_default=True).
    При создании пользователя создаём персональные копии с is_default=False.
    """
    if not created:
        return
    # Убедимся, что глобальные шаблоны существуют
    existing_global = {c.name for c in Category.objects.filter(user__isnull=True, is_default=True)}
    to_create_global = [
        Category(name=name, type=ctype, user=None, is_default=True)
        for name, ctype in DEFAULT_CATEGORIES
        if name not in existing_global
    ]
    if to_create_global:
        Category.objects.bulk_create(to_create_global)

    # Персональные копии
    user_cat_names = set(
        Category.objects.filter(user=instance).values_list('name', flat=True)
    )
    to_create = [
        Category(name=name, type=ctype, user=instance, is_default=False)
        for name, ctype in DEFAULT_CATEGORIES
        if name not in user_cat_names
    ]
    if to_create:
        Category.objects.bulk_create(to_create)

    # Технические категории для переводов между счетами
    Category.transfer_pair(instance)
