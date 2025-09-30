from django.urls import path

from events import views

app_name = 'events'

urlpatterns = [
    path('painel/eventos/novo/', views.EventCreateView.as_view(), name='create'),
    path('', views.EventListView.as_view(), name='list'),
    path('eventos/<slug:slug>/', views.EventDetailView.as_view(), name='detail'),
    path('eventos/<slug:slug>/editar/', views.EventUpdateView.as_view(), name='edit'),
    path('inscricoes/consulta/', views.AthleteRegistrationLookupView.as_view(), name='registration_lookup'),
    path('eventos/<slug:slug>/inscricao/', views.EventRegistrationView.as_view(), name='registration'),
    path('eventos/<slug:slug>/inscricoes/lote/', views.EventBulkRegistrationView.as_view(), name='registration_bulk'),
    path('eventos/<slug:slug>/inscricoes/lote/sucesso/', views.BulkRegistrationSuccessView.as_view(), name='registration_bulk_success'),
    path('eventos/<slug:slug>/inscricao/sucesso/', views.RegistrationSuccessView.as_view(), name='registration_success'),
]
