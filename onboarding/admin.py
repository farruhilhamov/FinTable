from django.contrib import admin

from .models import UserProfile


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'onboarding_completed', 'onboarding_skipped')
    list_filter = ('onboarding_completed', 'onboarding_skipped')
