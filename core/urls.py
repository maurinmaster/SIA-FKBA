from django.urls import path

from core.views import (
    DashboardView,
    EventListView,
    RegistrationListView,
    RegistrationExportView,
    RegistrationPaymentActionView,
    MatchmakingMetricListView,
    MatchmakingMetricCreateView,
    MatchmakingMetricUpdateView,
    MatchmakingMetricDeleteView,
    MatchmakingEventView,
    MatchmakingGenerateView,
    MatchmakingBracketDetailView,
    MatchmakingBracketExportView,
    MatchmakingBracketManualEditView,
)

app_name = 'core'

urlpatterns = [
    path('', DashboardView.as_view(), name='dashboard'),
    path('eventos/', EventListView.as_view(), name='events'),
    path('inscricoes/', RegistrationListView.as_view(), name='registrations'),
    path('inscricoes/exportar/', RegistrationExportView.as_view(), name='registrations-export'),
    path('inscricoes/<int:pk>/pagamento/', RegistrationPaymentActionView.as_view(), name='registration-payment'),
    path('casamentos/metricas/', MatchmakingMetricListView.as_view(), name='matchmaking-metrics'),
    path('casamentos/metricas/nova/', MatchmakingMetricCreateView.as_view(), name='matchmaking-metric-create'),
    path('casamentos/metricas/<int:pk>/editar/', MatchmakingMetricUpdateView.as_view(), name='matchmaking-metric-edit'),
    path('casamentos/metricas/<int:pk>/remover/', MatchmakingMetricDeleteView.as_view(), name='matchmaking-metric-delete'),
    path('casamentos/eventos/<slug:slug>/', MatchmakingEventView.as_view(), name='matchmaking-event'),
    path('casamentos/eventos/<slug:slug>/gerar/', MatchmakingGenerateView.as_view(), name='matchmaking-generate'),
    path('casamentos/chaves/<int:pk>/', MatchmakingBracketDetailView.as_view(), name='matchmaking-bracket-detail'),
    path('casamentos/chaves/<int:pk>/exportar/', MatchmakingBracketExportView.as_view(), name='matchmaking-bracket-export'),
    path('casamentos/chaves/<int:pk>/editar/', MatchmakingBracketManualEditView.as_view(), name='matchmaking-bracket-edit'),
]




