from django.contrib import admin

from .models import Deposit


@admin.register(Deposit)
class DepositAdmin(admin.ModelAdmin):
    list_display = ('name', 'principal_amount', 'annual_rate', 'status', 'user')
    list_filter = ('status', 'capitalization_type')
    search_fields = ('name',)
