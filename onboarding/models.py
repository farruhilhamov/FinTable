from django.conf import settings
from django.db import models


class UserProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile'
    )
    onboarding_completed = models.BooleanField(default=False)
    onboarding_skipped = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        status = []
        if self.onboarding_completed:
            status.append('завершён')
        if self.onboarding_skipped:
            status.append('пропущен')
        return f'{self.user.email} ({", ".join(status) or "не пройден"})'
