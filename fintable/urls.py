from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('accounts.urls')),
    path('finance/', include('finance.urls')),
    path('deposits/', include('deposits.urls')),
    path('securities/', include('securities.urls')),
    path('analytics/', include('analytics.urls')),
    path('importexport/', include('importexport.urls')),
    path('', include('onboarding.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
