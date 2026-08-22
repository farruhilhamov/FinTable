from django.urls import path

from . import views

urlpatterns = [
    path('', views.SecurityListView.as_view(), name='securities'),
    path('new/', views.SecurityCreateView.as_view(), name='security_create'),
    path('<int:pk>/edit/', views.SecurityUpdateView.as_view(), name='security_edit'),
    path('<int:pk>/delete/', views.SecurityDeleteView.as_view(), name='security_delete'),
    path('<int:pk>/valuations/', views.SecurityValuationListView.as_view(), name='security_valuations'),
    path('<int:pk>/valuations/new/', views.SecurityValuationCreateView.as_view(), name='security_valuation_create'),
]
