from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('painel/', include(('core.urls', 'core'), namespace='core')),
    path('pagamentos/', include(('payments.urls', 'payments'), namespace='payments')),
    path('', include(('events.urls', 'events'), namespace='events')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
