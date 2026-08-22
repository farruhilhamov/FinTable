from django.urls import path

from . import views

urlpatterns = [
    path('', views.DepositListView.as_view(), name='deposits'),
    path('new/', views.DepositCreateView.as_view(), name='deposit_create'),
    path('<int:pk>/edit/', views.DepositUpdateView.as_view(), name='deposit_edit'),
    path('<int:pk>/close/', views.DepositCloseView.as_view(), name='deposit_close'),
    path('<int:pk>/delete/', views.DepositDeleteView.as_view(), name='deposit_delete'),
]
