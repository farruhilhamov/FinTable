from django.urls import path
from django.contrib.auth.decorators import login_required
from django.views.generic import RedirectView

from . import views

urlpatterns = [
    path('', login_required(RedirectView.as_view(url='/analytics/dashboard/', permanent=False)), name='home'),
    path('signup/', views.signup_view, name='signup'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
]
