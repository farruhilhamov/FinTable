"""Миксин и утилиты для owner-scoped views: строгая фильтрация по request.user."""
from django.contrib.auth.mixins import LoginRequiredMixin


class OwnerQuerySetMixin(LoginRequiredMixin):
    """Переопределяет get_queryset так, чтобы возвращать только объекты пользователя.

    Все views, работающие с пользовательскими данными, наследуются от него
    (или переопределяют get_queryset сами), гарантируя изоляцию данных.
    """

    owner_field = 'user'

    def get_queryset(self):
        qs = super().get_queryset()
        return qs.filter(**{self.owner_field: self.request.user})
