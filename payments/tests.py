from unittest import mock

import json
from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from core.models import Academy, Coach
from events.models import AthleteRegistration, Event
from payments.models import Payment
from payments.services import (
    AsaasCustomer,
    AsaasPayment,
    MissingAsaasConfiguration,
    create_payment_for_registration,
    mark_registration_paid_manually,
)


class CreatePaymentForRegistrationTests(TestCase):
    def setUp(self):
        self.academy = Academy.objects.create(name='Team Teste', city='Sao Paulo', state='SP')
        self.coach = Coach.objects.create(full_name='Professor Teste', academy=self.academy, email='coach@example.com')
        start_at = timezone.now() + timedelta(days=30)
        deadline = start_at - timedelta(days=7)
        self.event = Event.objects.create(
            title='Evento Teste',
            location='Arena Teste',
            start_at=start_at,
            registration_deadline=deadline,
            registration_fee=150,
            is_published=True,
        )
        self.registration = AthleteRegistration.objects.create(
            event=self.event,
            academy=self.academy,
            coach=self.coach,
            cpf='12345678901',
            athlete_name='Atleta Teste',
            birth_date='2000-01-01',
            practice_time=AthleteRegistration.PracticeDuration.ONE_TO_THREE,
            record_wins=0,
            record_draws=0,
            record_losses=0,
            weight_kg=70,
            rule_set=AthleteRegistration.RuleSet.K1_LIGHT,
            modality=AthleteRegistration.Modality.AMATEUR,
            whatsapp='551199999999',
            sex=AthleteRegistration.Sex.MALE,
        )

    @override_settings(ASAAS_API_KEY='test', ASAAS_API_BASE='https://sandbox.asaas.com/api/v3')
    def test_create_payment_persists_record(self):
        fake_customer = AsaasCustomer(id='cus_123', raw={'id': 'cus_123'})
        fake_payment = AsaasPayment(
            id='pay_123',
            status='PENDING',
            billing_type='PIX',
            due_date='2025-10-01',
            value=self.event.registration_fee,
            invoice_url='https://sandbox.asaas.com/payments/pay_123',
            bank_slip_url=None,
            raw={'id': 'pay_123', 'status': 'PENDING'},
            pix_payload={'payload': '000201010211', 'encodedImage': 'iVBORw0KGgo='},
        )
        with mock.patch('payments.services.AsaasClient') as client_class:
            client = client_class.return_value
            client.ensure_customer.return_value = fake_customer
            client.create_payment.return_value = fake_payment
            payment = create_payment_for_registration(self.registration)
        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(payment.asaas_payment_id, 'pay_123')
        self.assertEqual(payment.pix_copy_and_paste, '000201010211')
        self.assertEqual(payment.customer_id, 'cus_123')
        self.assertEqual(payment.bank_slip_url, '')
        client.ensure_customer.assert_called_once()
        client.create_payment.assert_called_once()

    @override_settings(ASAAS_API_KEY='', ASAAS_API_BASE='')
    def test_missing_configuration_raises(self):
        with self.assertRaises(MissingAsaasConfiguration):
            create_payment_for_registration(self.registration)


class AsaasWebhookTests(TestCase):
    def setUp(self):
        self.academy = Academy.objects.create(name='Equipe Webhook', city='Sao Paulo', state='SP')
        self.coach = Coach.objects.create(full_name='Coach Webhook', academy=self.academy)
        start_at = timezone.now() + timedelta(days=15)
        deadline = start_at - timedelta(days=5)
        self.event = Event.objects.create(
            title='Evento Webhook',
            location='Centro de Lutas',
            start_at=start_at,
            registration_deadline=deadline,
            registration_fee=200,
            is_published=True,
        )
        self.registration = AthleteRegistration.objects.create(
            event=self.event,
            academy=self.academy,
            coach=self.coach,
            cpf='98765432100',
            athlete_name='Webhook Atleta',
            birth_date='1998-05-05',
            practice_time=AthleteRegistration.PracticeDuration.ONE_TO_THREE,
            record_wins=1,
            record_draws=0,
            record_losses=0,
            weight_kg=60,
            rule_set=AthleteRegistration.RuleSet.K1_RULES,
            modality=AthleteRegistration.Modality.AMATEUR,
            whatsapp='551199111111',
            sex=AthleteRegistration.Sex.FEMALE,
        )
        self.payment = Payment.objects.create(
            registration=self.registration,
            customer_id='cus_999',
            asaas_payment_id='pay_999',
            value=self.event.registration_fee,
            due_date=timezone.localdate(),
            billing_type=Payment.BillingType.PIX,
            status=Payment.Status.PENDING,
        )

    @override_settings(ASAAS_WEBHOOK_TOKEN='token-123')
    def test_webhook_confirms_payment(self):
        url = '/pagamentos/webhooks/asaas/'
        payload = {
            'event': 'PAYMENT_RECEIVED',
            'payment': {
                'id': self.payment.asaas_payment_id,
                'status': 'RECEIVED',
            },
        }
        response = self.client.post(
            url,
            data=json.dumps(payload),
            content_type='application/json',
            **{'HTTP_X_ASAAS_TOKEN': 'token-123'},
        )
        self.assertEqual(response.status_code, 200)
        self.payment.refresh_from_db()
        self.registration.refresh_from_db()
        self.assertTrue(self.payment.is_paid)
        self.assertEqual(self.registration.status, AthleteRegistration.Status.CONFIRMED)

    @override_settings(ASAAS_WEBHOOK_TOKEN='token-123')
    def test_webhook_rejects_invalid_token(self):
        url = '/pagamentos/webhooks/asaas/'
        payload = {'payment': {'id': self.payment.asaas_payment_id}}
        response = self.client.post(
            url,
            data=json.dumps(payload),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 403)

    def test_mark_registration_paid_manually_creates_payment(self):
        registration = self.registration
        payment = mark_registration_paid_manually(registration)
        self.assertEqual(payment.status, Payment.Status.CONFIRMED)
        self.assertEqual(payment.registration, registration)
        self.assertEqual(registration.payment, payment)
        registration.refresh_from_db()
        self.assertEqual(registration.status, AthleteRegistration.Status.CONFIRMED)

    def test_mark_registration_paid_manually_updates_existing(self):
        registration = self.registration
        self.payment.status = Payment.Status.PENDING
        self.payment.invoice_url = 'https://asaas.test/pay_existing'
        self.payment.save(update_fields=['status', 'invoice_url', 'updated_at'])
        payment = mark_registration_paid_manually(registration)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.pk, payment.pk)
        self.assertTrue(self.payment.is_paid)
        registration.refresh_from_db()
        self.assertEqual(registration.status, AthleteRegistration.Status.CONFIRMED)
