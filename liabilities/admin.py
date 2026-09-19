from django.contrib import admin

from .models import Liability


@admin.register(Liability)
class LiabilityAdmin(admin.ModelAdmin):
    list_display = ('name', 'kind', 'direction', 'balance', 'principal', 'monthly_payment',
                    'payment_day', 'status', 'user')
    list_filter = ('kind', 'direction', 'status')
    search_fields = ('name', 'counterparty')
