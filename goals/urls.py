from django.urls import path

from . import views

urlpatterns = [
    path('', views.GoalListView.as_view(), name='goals'),
    path('new/', views.GoalCreateView.as_view(), name='goal_create'),
    path('<int:pk>/edit/', views.GoalUpdateView.as_view(), name='goal_edit'),
    path('<int:pk>/topup/', views.GoalTopUpView.as_view(), name='goal_topup'),
    path('<int:pk>/delete/', views.GoalDeleteView.as_view(), name='goal_delete'),
]
