from django.contrib import admin

from .models import Goal


@admin.register(Goal)
class GoalAdmin(admin.ModelAdmin):
    list_display = ('name', 'target_amount', 'deadline', 'status', 'user')
    list_filter = ('status',)
    search_fields = ('name',)
