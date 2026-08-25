from django.urls import path

from . import views

urlpatterns = [
    path('transactions/', views.TransactionListView.as_view(), name='transactions'),
    path('transactions/new/', views.TransactionCreateView.as_view(), name='transaction_create'),
    path('transactions/<int:pk>/edit/', views.TransactionUpdateView.as_view(), name='transaction_edit'),
    path('transactions/<int:pk>/delete/', views.TransactionDeleteView.as_view(), name='transaction_delete'),

    path('accounts/', views.AccountListView.as_view(), name='accounts'),
    path('accounts/new/', views.AccountCreateView.as_view(), name='account_create'),
    path('accounts/<int:pk>/edit/', views.AccountUpdateView.as_view(), name='account_edit'),
    path('accounts/<int:pk>/balance/', views.AccountBalanceView.as_view(), name='account_balance'),

    path('categories/', views.CategoryListView.as_view(), name='categories'),
    path('categories/new/', views.CategoryCreateView.as_view(), name='category_create'),
    path('categories/<int:pk>/edit/', views.CategoryUpdateView.as_view(), name='category_edit'),
    path('categories/<int:pk>/archive/', views.CategoryArchiveView.as_view(), name='category_archive'),

    path('recurring/', views.RecurringListView.as_view(), name='recurring'),
    path('recurring/new/', views.RecurringCreateView.as_view(), name='recurring_create'),
    path('recurring/<int:pk>/edit/', views.RecurringUpdateView.as_view(), name='recurring_edit'),
    path('recurring/<int:pk>/delete/', views.RecurringDeleteView.as_view(), name='recurring_delete'),
]
