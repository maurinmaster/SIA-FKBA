from datetime import timedelta
from decimal import Decimal

from unittest import mock
from django.contrib.auth import get_user_model

from django.test import TestCase
from django.urls import reverse
from payments.models import Payment
from django.utils import timezone

from core.models import Academy, Coach
from events.forms import AthleteRegistrationForm
from events.models import AthleteRegistration, Event



class AthleteRegistrationFormTests(TestCase):
    def setUp(self):
        self.academy = Academy.objects.create(name='Team Alpha', city='São Paulo', state='SP')
        self.coach = Coach.objects.create(full_name='Professor Silva', academy=self.academy)
        start_at = timezone.now() + timedelta(days=30)
        deadline = start_at - timedelta(days=7)
        self.event = Event.objects.create(
            title='Grand Prix Kickboxing',
            location='Ginásio Municipal',
            start_at=start_at,
            registration_deadline=deadline,
            registration_fee=150,
            is_published=True,
        )

    def _valid_payload(self) -> dict[str, str | int]:
        return {
            'event': self.event.id,
            'academy_name': 'Team Alpha',
            'academy_city': 'São Paulo',
            'academy_state': 'SP',
            'coach_name': 'Professor Silva',
            'cpf': '12345678901',
            'athlete_name': 'João Santos',
            'birth_date': '2000-05-10',
            'practice_time': AthleteRegistration.PracticeDuration.ONE_TO_THREE,
            'total_fights': 6,
            'weight_kg': '72.5',
            'rule_set': AthleteRegistration.RuleSet.K1_LIGHT,
            'modality': AthleteRegistration.Modality.AMATEUR,
            'whatsapp': '1199999999',
            'sex': AthleteRegistration.Sex.MALE,
        }

    def test_form_valid_for_open_event_reuses_academy(self):
        form = AthleteRegistrationForm(data=self._valid_payload(), event=self.event)
        self.assertTrue(form.is_valid())
        registration = form.save()
        self.assertEqual(registration.event, self.event)
        self.assertEqual(registration.academy, self.academy)
        self.assertEqual(registration.coach, self.coach)
        self.assertEqual(registration.record_wins, 6)
        self.assertEqual(registration.record_draws, 0)
        self.assertEqual(registration.record_losses, 0)
        self.assertEqual(
            registration.experience_level,
            AthleteRegistration.ExperienceLevel.INTERMEDIATE,
        )

    def test_form_creates_new_academy_and_coach(self):
        payload = self._valid_payload() | {
            'academy_name': 'Nova União',
            'academy_city': 'Curitiba',
            'academy_state': 'PR',
            'coach_name': 'Profa. Andrade',
            'cpf': '09876543210',
        }
        form = AthleteRegistrationForm(data=payload, event=self.event)
        self.assertTrue(form.is_valid())
        registration = form.save()
        self.assertEqual(registration.academy.name, 'Nova União')
        self.assertEqual(registration.coach.full_name, 'Profa. Andrade')

    def test_form_rejects_closed_event(self):
        self.event.registration_deadline = timezone.now() - timedelta(days=1)
        self.event.save()
        form = AthleteRegistrationForm(data=self._valid_payload(), event=self.event)
        self.assertFalse(form.is_valid())
        self.assertIn(
            'As inscricoes para este evento estao encerradas.',
            form.errors['__all__'],
        )

    def test_form_requires_academia_nome(self):
        payload = self._valid_payload()
        payload['academy_name'] = ''
        form = AthleteRegistrationForm(data=payload, event=self.event)
        self.assertFalse(form.is_valid())
        self.assertIn('Informe o nome da academia.', form.errors['academy_name'])

    def test_form_rejects_duplicate_cpf(self):
        AthleteRegistration.objects.create(
            event=self.event,
            academy=self.academy,
            coach=self.coach,
            cpf='12345678901',
            athlete_name='Outro Atleta',
            birth_date='1999-01-01',
            practice_time=AthleteRegistration.PracticeDuration.LESS_THAN_ONE,
            record_wins=0,
            record_draws=0,
            record_losses=0,
            weight_kg=60,
            rule_set=AthleteRegistration.RuleSet.K1_LIGHT,
            modality=AthleteRegistration.Modality.AMATEUR,
            whatsapp='4190000000',
            sex=AthleteRegistration.Sex.FEMALE,
        )
        form = AthleteRegistrationForm(data=self._valid_payload(), event=self.event)
        self.assertFalse(form.is_valid())
        self.assertIn('cpf', form.errors)

    def test_whatsapp_accepts_eleven_digit_number(self):
        payload = self._valid_payload()
        payload['whatsapp'] = '11999999999'
        form = AthleteRegistrationForm(data=payload, event=self.event)
        self.assertTrue(form.is_valid())
        registration = form.save()
        self.assertEqual(registration.whatsapp, '5511999999999')

    def test_whatsapp_rejects_number_with_wrong_length(self):
        payload = self._valid_payload()
        payload['whatsapp'] = '123456'
        form = AthleteRegistrationForm(data=payload, event=self.event)
        self.assertFalse(form.is_valid())
        self.assertIn('DDI 55', form.errors['whatsapp'][0])


class BulkRegistrationViewTests(TestCase):
    def setUp(self):
        self.academy = Academy.objects.create(name='Equipe Central', city='Salvador', state='BA')
        self.coach = Coach.objects.create(full_name='Professor Braga', academy=self.academy)
        start_at = timezone.now() + timedelta(days=15)
        deadline = start_at - timedelta(days=5)
        self.event = Event.objects.create(
            title='Open Bahia',
            location='Arena Central',
            start_at=start_at,
            registration_deadline=deadline,
            registration_fee=200,
            is_published=True,
        )
        self.url = reverse('events:registration_bulk', args=[self.event.slug])

    def _formset_payload(self, total: int) -> dict[str, str]:
        payload = {
            'academy_name': 'Equipe Central',
            'academy_city': 'Salvador',
            'academy_state': 'BA',
            'coach_name': 'Professor Braga',
            'modality': AthleteRegistration.Modality.AMATEUR,
            'athletes-TOTAL_FORMS': str(total),
            'athletes-INITIAL_FORMS': '0',
            'athletes-MIN_NUM_FORMS': '0',
            'athletes-MAX_NUM_FORMS': '1000',
        }
        for index in range(total):
            prefix = f'athletes-{index}-'
            payload[f'{prefix}athlete_name'] = f'Atleta {index + 1}'
            payload[f'{prefix}cpf'] = f'1234567890{index}'
            payload[f'{prefix}birth_date'] = '2000-01-01'
            payload[f'{prefix}practice_time'] = AthleteRegistration.PracticeDuration.ONE_TO_THREE
            payload[f'{prefix}total_fights'] = '5'
            payload[f'{prefix}weight_kg'] = '70.0'
            payload[f'{prefix}rule_set'] = AthleteRegistration.RuleSet.K1_LIGHT
            payload[f'{prefix}sex'] = AthleteRegistration.Sex.MALE
            payload[f'{prefix}whatsapp'] = '11999999999'
            payload[f'{prefix}event'] = str(self.event.pk)
            payload[f'{prefix}academy_name'] = 'Equipe Central'
            payload[f'{prefix}academy_city'] = 'Salvador'
            payload[f'{prefix}academy_state'] = 'BA'
            payload[f'{prefix}coach_name'] = 'Professor Braga'
            payload[f'{prefix}modality'] = AthleteRegistration.Modality.AMATEUR
            payload[f'{prefix}record_wins'] = '0'
            payload[f'{prefix}record_draws'] = '0'
            payload[f'{prefix}record_losses'] = '0'
        return payload

    def test_get_renders_form(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Inscricao em lote', status_code=200)

    def test_post_creates_multiple_registrations(self):
        data = self._formset_payload(2)
        with mock.patch('events.views.create_payment_for_registration', autospec=True) as create_payment:
            response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 302)
        success_url = reverse('events:registration_bulk_success', args=[self.event.slug])
        self.assertEqual(response['Location'], success_url)
        registrations = AthleteRegistration.objects.filter(event=self.event)
        self.assertEqual(registrations.count(), 2)
        self.assertEqual(create_payment.call_count, 2)
        session = self.client.session
        self.assertIn('recent_bulk_registration_ids', session)
        self.assertEqual(len(session['recent_bulk_registration_ids']), 2)
        total_amount = session.get('recent_bulk_total_amount')
        self.assertIsNotNone(total_amount)
        registration_fee = Decimal(str(self.event.registration_fee))
        expected_total = (registration_fee * 2).quantize(Decimal('0.01'))
        self.assertEqual(Decimal(total_amount), expected_total)

        success_response = self.client.get(success_url)
        self.assertEqual(success_response.status_code, 200)
        context_regs = success_response.context['registrations']
        self.assertEqual(len(context_regs), 2)
        self.assertEqual(success_response.context['total_amount'], expected_total)

    def test_post_without_athletes_shows_error(self):
        data = self._formset_payload(1)
        data['athletes-0-athlete_name'] = ''
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Informe ao menos um atleta.')
        self.assertEqual(AthleteRegistration.objects.filter(event=self.event).count(), 0)

class AthleteRegistrationLookupViewTests(TestCase):
    def setUp(self):
        start_at = timezone.now() + timedelta(days=10)
        deadline = start_at - timedelta(days=3)
        self.event = Event.objects.create(
            title='Arena Fight',
            location='Pituba Arena',
            start_at=start_at,
            registration_deadline=deadline,
            registration_fee=250,
            is_published=True,
        )
        self.academy = Academy.objects.create(name='Equipe Norte', city='Salvador', state='BA')
        self.coach = Coach.objects.create(full_name='Professor Lima', academy=self.academy)
        self.registration = AthleteRegistration.objects.create(
            event=self.event,
            academy=self.academy,
            coach=self.coach,
            athlete_name='Carlos Guerreiro',
            birth_date='2003-05-18',
            practice_time=AthleteRegistration.PracticeDuration.ONE_TO_THREE,
            record_wins=3,
            record_draws=0,
            record_losses=1,
            weight_kg=75,
            rule_set=AthleteRegistration.RuleSet.K1_RULES,
            modality=AthleteRegistration.Modality.AMATEUR,
            whatsapp='71999990000',
            sex=AthleteRegistration.Sex.MALE,
            cpf='12345678901',
        )
        self.url = reverse('events:registration_lookup')

    def test_get_renders_lookup_form(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('form', response.context)

    def test_post_returns_registrations(self):
        response = self.client.post(self.url, {'cpf': '12345678901', 'birth_date': '2003-05-18'})
        self.assertEqual(response.status_code, 200)
        registrations = response.context['registrations']
        self.assertEqual(len(registrations), 1)
        self.assertEqual(registrations[0], self.registration)

    def test_request_payment_triggers_service(self):
        with mock.patch('events.views.create_payment_for_registration', autospec=True) as create_payment:
            response = self.client.post(
                self.url,
                {
                    'cpf': '12345678901',
                    'birth_date': '2003-05-18',
                    'registration_id': str(self.registration.pk),
                    'action': 'send-payment',
                },
            )
        self.assertEqual(response.status_code, 200)
        create_payment.assert_called_once_with(self.registration)
        self.assertEqual(len(response.context['registrations']), 1)




class BulkRegistrationFreeEventTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='manager', password='secret', is_staff=True)
        self.client.force_login(self.user)
        start_at = timezone.now() + timedelta(days=12)
        deadline = start_at - timedelta(days=3)
        self.event = Event.objects.create(
            title='Open Kids',
            location='Centro Juvenil',
            start_at=start_at,
            registration_deadline=deadline,
            registration_fee=Decimal('0.00'),
            is_free=True,
            is_published=True,
        )
        self.url = reverse('events:registration_bulk', args=[self.event.slug])

    def _payload(self):
        return {
            'academy_name': 'Luta Livre',
            'academy_city': 'Salvador',
            'academy_state': 'BA',
            'coach_name': 'Professor Nunes',
            'modality': AthleteRegistration.Modality.AMATEUR,
            'athletes-TOTAL_FORMS': '1',
            'athletes-INITIAL_FORMS': '0',
            'athletes-MIN_NUM_FORMS': '0',
            'athletes-MAX_NUM_FORMS': '1000',
            'athletes-0-athlete_name': 'Aluno Gratis',
            'athletes-0-cpf': '11122233344',
            'athletes-0-birth_date': '2012-04-15',
            'athletes-0-practice_time': AthleteRegistration.PracticeDuration.LESS_THAN_ONE,
            'athletes-0-total_fights': '0',
            'athletes-0-weight_kg': '45.0',
            'athletes-0-rule_set': AthleteRegistration.RuleSet.K1_LIGHT,
            'athletes-0-modality': AthleteRegistration.Modality.AMATEUR,
            'athletes-0-whatsapp': '71988880000',
            'athletes-0-sex': AthleteRegistration.Sex.MALE,
            'athletes-0-event': str(self.event.pk),
            'athletes-0-academy_name': 'Luta Livre',
            'athletes-0-academy_city': 'Salvador',
            'athletes-0-academy_state': 'BA',
            'athletes-0-coach_name': 'Professor Nunes',
        }

    def test_bulk_registration_skips_gateway_for_free_event(self):
        data = self._payload()
        response = self.client.post(self.url, data, follow=True)
        self.assertEqual(response.status_code, 200)
        registrations = AthleteRegistration.objects.filter(event=self.event)
        self.assertEqual(registrations.count(), 1)
        self.assertEqual(registrations.first().status, AthleteRegistration.Status.CONFIRMED)
        self.assertFalse(Payment.objects.filter(registration__event=self.event).exists())
class EventUpdateViewTests(TestCase):
    def setUp(self):
        self.staff_user = get_user_model().objects.create_user(
            username='coordenador', password='senha-segura', is_staff=True
        )
        start_at = timezone.now() + timedelta(days=15)
        deadline = start_at - timedelta(days=5)
        self.event = Event.objects.create(
            title='Bahia Fight Night',
            location='Arena Pituba',
            start_at=start_at,
            registration_deadline=deadline,
            registration_fee=180,
            is_published=True,
        )
        self.url = reverse('events:edit', args=[self.event.slug])
        self.client.force_login(self.staff_user)

    def test_requires_staff(self):
        self.client.logout()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('admin/login', response.url)

    def test_staff_can_update_event(self):
        payload = {
            'title': 'Bahia Fight Night Finals',
            'location': 'Centro de Esportes',
            'description': 'Atualizacao de local e titulo.',
            'start_at': (self.event.start_at + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M'),
            'registration_deadline': (self.event.registration_deadline + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M'),
            'registration_fee': '220.00',
            'is_published': 'on',
        }
        response = self.client.post(self.url, payload, follow=True)
        self.assertEqual(response.status_code, 200)
        self.event.refresh_from_db()
        self.assertEqual(self.event.title, 'Bahia Fight Night Finals')
        self.assertEqual(self.event.location, 'Centro de Esportes')
        self.assertEqual(self.event.registration_fee, Decimal('220.00'))


class EventRegistrationViewFreeEventTests(TestCase):
    def setUp(self):
        start_at = timezone.now() + timedelta(days=10)
        deadline = start_at - timedelta(days=2)
        self.event = Event.objects.create(
            title='Open Bahia Free',
            location='Ginásio Central',
            start_at=start_at,
            registration_deadline=deadline,
            registration_fee=Decimal('0.00'),
            is_free=True,
            is_published=True,
        )
        self.url = reverse('events:registration', args=[self.event.slug])

    def _payload(self):
        return {
            'academy_name': 'Equipe Livre',
            'academy_city': 'Salvador',
            'academy_state': 'BA',
            'coach_name': 'Professor Livre',
            'cpf': '98765432100',
            'athlete_name': 'Atleta Gratis',
            'birth_date': '2005-07-20',
            'practice_time': AthleteRegistration.PracticeDuration.ONE_TO_THREE,
            'total_fights': 3,
            'weight_kg': '70.0',
            'rule_set': AthleteRegistration.RuleSet.K1_LIGHT,
            'modality': AthleteRegistration.Modality.AMATEUR,
            'whatsapp': '71999990001',
            'sex': AthleteRegistration.Sex.MALE,
            'event': str(self.event.pk),
        }

    def test_free_event_confirms_without_gateway(self):
        payload = self._payload()
        response = self.client.post(self.url, payload)
        if response.status_code != 302:
            form = response.context.get('form') if hasattr(response, 'context') else None
            errors = form.errors if form is not None else 'no-form'
            self.fail(f'Formulario invalido: {errors}')
        registration = AthleteRegistration.objects.get(cpf='98765432100')
        self.assertEqual(registration.status, AthleteRegistration.Status.CONFIRMED)
        self.assertFalse(hasattr(registration, 'payment'))

