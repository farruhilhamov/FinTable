from django.contrib import admin

from .models import Account, Category, RecurringTemplate, Transaction


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ('name', 'type', 'user', 'is_active')
    list_filter = ('type', 'is_active')
    search_fields = ('name',)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'type', 'user', 'is_default', 'is_active')
    list_filter = ('type', 'is_default', 'is_active')
    search_fields = ('name',)


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ('date', 'type', 'amount', 'account', 'category', 'user')
    list_filter = ('type', 'date')
    search_fields = ('description',)


@admin.register(RecurringTemplate)
class RecurringTemplateAdmin(admin.ModelAdmin):
    list_display = ('day_of_month', 'type', 'amount', 'account', 'category', 'is_active')
    list_filter = ('type', 'is_active')
