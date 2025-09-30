from __future__ import annotations

import json
import logging

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from payments.models import Payment

logger = logging.getLogger(__name__)


def _has_valid_token(request) -> bool:
    expected = getattr(settings, 'ASAAS_WEBHOOK_TOKEN', '')
    if not expected:
        return True
    candidates = [
        request.headers.get('X-Asaas-Token'),
        request.headers.get('asaas-access-token'),
        request.headers.get('Authorization'),
    ]
    for token in candidates:
        if not token:
            continue
        if token == expected or token == f'Bearer {expected}':
            return True
    return False


@csrf_exempt
@require_POST
def asaas_webhook(request):
    if not _has_valid_token(request):
        return HttpResponse(status=403)
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON invalido'}, status=400)
    payment_data = payload.get('payment') or payload.get('data') or payload
    payment_id = payment_data.get('id') if isinstance(payment_data, dict) else None
    if not payment_id:
        return JsonResponse({'error': 'Pagamento nao informado'}, status=400)
    try:
        payment = Payment.objects.select_related('registration').get(asaas_payment_id=payment_id)
    except Payment.DoesNotExist:
        logger.warning('Webhook Asaas recebido para pagamento desconhecido: %s', payment_id)
        return JsonResponse({'detail': 'Pagamento nao encontrado'}, status=404)
    status = payment_data.get('status') if isinstance(payment_data, dict) else None
    if status in {Payment.Status.RECEIVED, Payment.Status.CONFIRMED}:
        payment.mark_as_paid(status, payload=payment_data if isinstance(payment_data, dict) else None)
    else:
        update_fields = []
        if status:
            payment.status = status
            update_fields.append('status')
        if isinstance(payment_data, dict):
            payment.payload = payment_data
            update_fields.append('payload')
        if update_fields:
            update_fields.append('updated_at')
            payment.save(update_fields=update_fields)
    return JsonResponse({'ok': True})
