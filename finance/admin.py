from django.contrib import admin

from .models import Account, Budget, Category, RecurringTemplate, Transaction


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
    list_display = ('day_of_month', 'type', 'amount', 'account', 'category', 'user',
                    'start_date', 'last_run', 'is_active')
    list_filter = ('type', 'is_active')
    readonly_fields = ('last_run',)
    actions = ['run_now']

    @admin.action(description='Выполнить выбранные шаблоны сейчас (догнать пропущенные даты)')
    def run_now(self, request, queryset):
        from .services import run_recurring_templates
        report = run_recurring_templates(template_ids=list(queryset.values_list('pk', flat=True)))
        self.message_user(request, report.summary())
        for err in report.errors:
            self.message_user(request, err, level='warning')


@admin.register(Budget)
class BudgetAdmin(admin.ModelAdmin):
    list_display = ('category', 'limit', 'user', 'is_active')
    list_filter = ('is_active',)
