from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from django.views.generic import RedirectView

# Customizar o comportamento de login do admin
class AdminLoginView(auth_views.LoginView):
    def get_success_url(self):
        # Se o usuário for staff, redireciona para o dashboard
        if self.request.user.is_staff:
            return '/painel/'
        # Caso contrário, redireciona para a página principal
        return '/'

urlpatterns = [
    path('admin/login/', AdminLoginView.as_view(template_name='admin/login.html'), name='admin_login'),
    path('admin/', admin.site.urls),
    path('painel/', include(('core.urls', 'core'), namespace='core')),
    path('pagamentos/', include(('payments.urls', 'payments'), namespace='payments')),
    path('', include(('events.urls', 'events'), namespace='events')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
