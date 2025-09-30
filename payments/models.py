from __future__ import annotations

from decimal import Decimal

from django.db import models
from django.utils import timezone

from core.models import TimeStampedModel


class Payment(TimeStampedModel):
    class BillingType(models.TextChoices):
        PIX = 'PIX', 'PIX'
        BOLETO = 'BOLETO', 'Boleto'
        CREDIT_CARD = 'CREDIT_CARD', 'Cartao de credito'
        UNDEFINED = 'UNDEFINED', 'Outro'

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pendente'
        AWAITING_RISK_ANALYSIS = 'AWAITING_RISK_ANALYSIS', 'Em analise'
        RECEIVED = 'RECEIVED', 'Recebido'
        CONFIRMED = 'CONFIRMED', 'Confirmado'
        OVERDUE = 'OVERDUE', 'Vencido'
        REFUNDED = 'REFUNDED', 'Reembolsado'
        REFUND_REQUESTED = 'REFUND_REQUESTED', 'Reembolso solicitado'
        CHARGEBACK_REQUESTED = 'CHARGEBACK_REQUESTED', 'Chargeback solicitado'
        CHARGEBACK_DISPUTE = 'CHARGEBACK_DISPUTE', 'Em disputa'
        CHARGEBACK_REVERSED = 'CHARGEBACK_REVERSED', 'Chargeback revertido'
        BANK_SLIP_VIEWED = 'BANK_SLIP_VIEWED', 'Boleto visualizado'
        PAYMENT_DELETED = 'PAYMENT_DELETED', 'Pagamento removido'
        UNKNOWN = 'UNKNOWN', 'Desconhecido'

    registration = models.OneToOneField(
        'events.AthleteRegistration',
        on_delete=models.CASCADE,
        related_name='payment',
    )
    customer_id = models.CharField(max_length=64)
    asaas_payment_id = models.CharField(max_length=64, unique=True)
    value = models.DecimalField(max_digits=9, decimal_places=2, default=Decimal('0.00'))
    due_date = models.DateField()
    billing_type = models.CharField(
        max_length=16,
        choices=BillingType.choices,
        default=BillingType.PIX,
    )
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.PENDING,
    )
    invoice_url = models.URLField(blank=True)
    bank_slip_url = models.URLField(blank=True)
    pix_qr_code_image = models.TextField(blank=True)
    pix_copy_and_paste = models.TextField(blank=True)
    external_reference = models.CharField(max_length=128, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self) -> str:  # pragma: no cover - simple display
        return f"Pagamento {self.asaas_payment_id} - {self.registration.athlete_name}"

    def mark_as_paid(self, event_status: str | None = None, payload: dict | None = None) -> None:
        self.status = event_status or self.Status.RECEIVED
        self.paid_at = timezone.now()
        update_fields = ['status', 'paid_at', 'updated_at']
        if payload is not None:
            self.payload = payload
            update_fields.append('payload')
        self.save(update_fields=update_fields)
        registration = self.registration
        registration.status = registration.Status.CONFIRMED
        registration.save(update_fields=['status', 'updated_at'])

    @property
    def is_paid(self) -> bool:
        return self.status in {self.Status.RECEIVED, self.Status.CONFIRMED}

    @property
    def amount_display(self) -> str:
        return f"R$ {self.value:0.2f}"
