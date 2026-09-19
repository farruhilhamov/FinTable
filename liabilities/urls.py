from django.urls import path

from . import views

urlpatterns = [
    path('', views.LiabilityListView.as_view(), name='liabilities'),
    path('new/', views.LiabilityCreateView.as_view(), name='liability_create'),
    path('<int:pk>/edit/', views.LiabilityUpdateView.as_view(), name='liability_edit'),
    path('<int:pk>/pay/', views.LiabilityPayView.as_view(), name='liability_pay'),
    path('<int:pk>/delete/', views.LiabilityDeleteView.as_view(), name='liability_delete'),
]
