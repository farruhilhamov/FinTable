from django.urls import path

from . import views

urlpatterns = [
    path('', views.ImportExportView.as_view(), name='importexport'),
]
