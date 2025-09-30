from django.urls import path

from payments import views

app_name = 'payments'

urlpatterns = [
    path('webhooks/asaas/', views.asaas_webhook, name='asaas-webhook'),
]
