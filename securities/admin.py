from django.contrib import admin

from .models import Security, SecurityValuation


class SecurityValuationInline(admin.TabularInline):
    model = SecurityValuation
    extra = 0


@admin.register(Security)
class SecurityAdmin(admin.ModelAdmin):
    list_display = ('name', 'acquisition_value', 'user')
    search_fields = ('name',)
    inlines = [SecurityValuationInline]
