from __future__ import annotations

import logging
from datetime import timedelta
from dataclasses import dataclass
from uuid import uuid4
from decimal import Decimal
from typing import Any, Dict, Optional

import requests
from django.conf import settings
from django.utils import timezone

from events.models import AthleteRegistration
from payments.models import Payment

logger = logging.getLogger(__name__)


class MissingAsaasConfiguration(RuntimeError):
    """Raised when required ASAAS settings are not available."""


class AsaasAPIError(RuntimeError):
    def __init__(self, message: str, *, status_code: int, response_data: Any | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_data = response_data


@dataclass(slots=True)
class AsaasCustomer:
    id: str
    raw: Dict[str, Any]


@dataclass(slots=True)
class AsaasPayment:
    id: str
    status: str
    billing_type: str
    due_date: str
    value: Decimal
    invoice_url: Optional[str]
    bank_slip_url: Optional[str]
    raw: Dict[str, Any]
    pix_payload: Optional[Dict[str, Any]] = None


class AsaasClient:
    def __init__(self, *, api_key: Optional[str] = None, base_url: Optional[str] = None) -> None:
        self.api_key = api_key or getattr(settings, 'ASAAS_API_KEY', None)
        if not self.api_key:
            raise MissingAsaasConfiguration('Configure a variavel de ambiente ASAAS_API_KEY antes de usar a API.')
        self.base_url = (base_url or getattr(settings, 'ASAAS_API_BASE', '')).rstrip('/')
        if not self.base_url:
            raise MissingAsaasConfiguration('Configure a variavel ASAAS_API_BASE antes de usar a API.')
        self.session = requests.Session()

    def _request(self, method: str, path: str, *, params: Optional[Dict[str, Any]] = None, json: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'access_token': self.api_key,
        }
        try:
            response = self.session.request(
                method,
                url,
                params=params,
                json=json,
                headers=headers,
                timeout=15,
            )
        except requests.RequestException as exc:  # pragma: no cover - network failure
            raise AsaasAPIError(f'Erro de comunicacao com a API da Asaas: {exc}', status_code=0) from exc
        if response.status_code >= 400:
            try:
                data = response.json()
            except ValueError:
                data = {'raw': response.text}
            message = data.get('errors', data)
            raise AsaasAPIError(f'Erro da API Asaas: {message}', status_code=response.status_code, response_data=data)
        if response.status_code == 204:
            return {}
        try:
            return response.json()
        except ValueError as exc:  # pragma: no cover - unexpected format
            raise AsaasAPIError('Resposta invalida da API Asaas.', status_code=response.status_code) from exc

    def ensure_customer(self, *, name: str, cpf: str, email: str | None = None, mobile_phone: str | None = None) -> AsaasCustomer:
        params = {'cpfCnpj': cpf}
        data = self._request('GET', '/customers', params=params)
        existing = data.get('data', [])
        if existing:
            customer = existing[0]
            return AsaasCustomer(id=customer['id'], raw=customer)
        payload = {
            'name': name,
            'cpfCnpj': cpf,
        }
        if email:
            payload['email'] = email
        if mobile_phone:
            payload['mobilePhone'] = mobile_phone
        customer = self._request('POST', '/customers', json=payload)
        return AsaasCustomer(id=customer['id'], raw=customer)

    def create_payment(
        self,
        *,
        customer_id: str,
        value: Decimal,
        due_date: str,
        description: str,
        billing_type: str,
        external_reference: str,
    ) -> AsaasPayment:
        payload = {
            'customer': customer_id,
            'billingType': billing_type,
            'value': float(Decimal(value).quantize(Decimal('0.01'))),
            'dueDate': due_date,
            'description': description[:255],
            'externalReference': external_reference,
        }
        payment_raw = self._request('POST', '/payments', json=payload)
        pix_data = None
        if payment_raw.get('billingType') == 'PIX':
            try:
                pix_data = self._request('GET', f"/payments/{payment_raw['id']}/pixQrCode")
            except AsaasAPIError as exc:
                logger.warning('Nao foi possivel obter o QRCode PIX: %s', exc)
        return AsaasPayment(
            id=payment_raw['id'],
            status=payment_raw.get('status', ''),
            billing_type=payment_raw.get('billingType', ''),
            due_date=payment_raw.get('dueDate', due_date),
            value=Decimal(str(payment_raw.get('value', value))),
            invoice_url=payment_raw.get('invoiceUrl', ''),
            bank_slip_url=payment_raw.get('bankSlipUrl', ''),
            raw=payment_raw,
            pix_payload=pix_data,
        )


def _extract_mobile_phone(whatsapp: str | None) -> str | None:
    if not whatsapp:
        return None
    digits = ''.join(filter(str.isdigit, whatsapp))
    if len(digits) >= 11:
        return digits[-11:]
    return None


def create_payment_for_registration(registration: AthleteRegistration) -> Payment:
    client = AsaasClient()
    customer = client.ensure_customer(
        name=registration.athlete_name,
        cpf=registration.cpf,
        email=registration.coach.email if registration.coach and registration.coach.email else None,
        mobile_phone=_extract_mobile_phone(registration.whatsapp),
    )
    due_days = getattr(settings, 'ASAAS_PAYMENT_DUE_DAYS', 3)
    due_date = (timezone.localdate() + timedelta(days=due_days)).isoformat()
    billing_type = getattr(settings, 'ASAAS_DEFAULT_BILLING_TYPE', 'PIX') or 'PIX'
    description = f"Inscricao {registration.athlete_name} - {registration.event.title}"[:255]
    payment_data = client.create_payment(
        customer_id=customer.id,
        value=registration.event.registration_fee,
        due_date=due_date,
        description=description,
        billing_type=billing_type,
        external_reference=str(registration.pk),
    )
    pix_payload = payment_data.pix_payload or {}
    payment, _ = Payment.objects.update_or_create(
        registration=registration,
        defaults={
            'customer_id': customer.id,
            'asaas_payment_id': payment_data.id,
            'value': registration.event.registration_fee,
            'due_date': payment_data.due_date,
            'billing_type': payment_data.billing_type or billing_type,
            'status': payment_data.status or Payment.Status.PENDING,
            'invoice_url': payment_data.invoice_url or '',
            'bank_slip_url': payment_data.bank_slip_url or '',
            'pix_qr_code_image': pix_payload.get('encodedImage', ''),
            'pix_copy_and_paste': pix_payload.get('payload', ''),
            'external_reference': str(registration.pk),
            'payload': payment_data.raw,
        },
    )
    return payment


def mark_registration_paid_manually(registration: AthleteRegistration) -> Payment:
    payment = getattr(registration, 'payment', None)
    now = timezone.now()
    if payment:
        payload = payment.payload or {}
        payload.update({'manual_confirmation': True})
        payment.mark_as_paid(Payment.Status.CONFIRMED, payload=payload)
        return payment
    manual_payment = Payment.objects.create(
        registration=registration,
        customer_id='manual',
        asaas_payment_id=f'manual-{uuid4().hex}',
        value=registration.event.registration_fee,
        due_date=timezone.localdate(),
        billing_type=Payment.BillingType.UNDEFINED,
        status=Payment.Status.CONFIRMED,
        invoice_url='',
        bank_slip_url='',
        pix_qr_code_image='',
        pix_copy_and_paste='',
        external_reference=str(registration.pk),
        payload={'manual_confirmation': True},
        paid_at=now,
    )
    registration.status = registration.Status.CONFIRMED
    registration.save(update_fields=['status', 'updated_at'])
    return manual_payment
