from django.urls import path
from django.contrib.auth.mixins import LoginRequiredMixin

from . import views

urlpatterns = [
    path('dashboard/', views.DashboardView.as_view(), name='dashboard'),
    path('stats/', views.StatsView.as_view(), name='stats'),
]
