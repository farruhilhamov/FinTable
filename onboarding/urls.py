from django.urls import path

from .wizard import OnboardingWizard
from . import views

wizard = OnboardingWizard.as_view(url_name='wizard')

urlpatterns = [
    path('wizard/', wizard, name='wizard'),
    path('wizard/step/<step>/', wizard, name='wizard'),
    path('settings/', views.settings_view, name='settings'),
    path('onboarding/preview/', views.deposit_preview, name='deposit_preview'),
]
