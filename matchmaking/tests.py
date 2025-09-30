from __future__ import annotations

from datetime import timedelta
import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Academy, Coach
from events.models import AthleteRegistration, Event
from matchmaking.forms import MatchmakingMetricForm
from matchmaking.models import (
    MatchmakingBracket,
    MatchmakingEntry,
    MatchmakingMetric,
    default_age_metrics,
    default_experience_metrics,
    default_weight_categories,
)
from matchmaking.services import generate_brackets_for_event, rebuild_bracket_matches


class MatchmakingMetricFormTests(TestCase):
    def test_parses_json_fields(self):
        form = MatchmakingMetricForm(
            data={
                'name': 'GP Nacional',
                'max_fights_per_athlete': 2,
                'notes': '',
                'age_metrics_json': json.dumps(default_age_metrics(), ensure_ascii=False),
                'experience_metrics_json': json.dumps(default_experience_metrics(), ensure_ascii=False),
                'weight_categories_json': json.dumps(default_weight_categories(), ensure_ascii=False),
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        metric = form.save()
        self.assertEqual(metric.age_metrics[0]['nome'], 'infantil')
        self.assertEqual(metric.experience_metrics[0]['maximo_lutas'], 4)
        self.assertEqual(metric.weight_categories[0]['sexo'], 'masculino')

    def test_invalid_json(self):
        form = MatchmakingMetricForm(
            data={
                'name': 'Teste',
                'max_fights_per_athlete': 1,
                'notes': '',
                'age_metrics_json': 'invalid',
                'experience_metrics_json': '[]',
                'weight_categories_json': '[]',
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn('JSON inv', str(form.errors))

    def test_accepts_legacy_key_names(self):
        form = MatchmakingMetricForm(
            data={
                'name': 'Compatibilidade',
                'max_fights_per_athlete': 1,
                'notes': '',
                'age_metrics_json': json.dumps([
                    {'name': 'juvenil', 'min_age': 15, 'max_age': 17},
                ]),
                'experience_metrics_json': json.dumps([
                    {'name': 'avancado', 'min_fights': 5},
                ]),
                'weight_categories_json': json.dumps([
                    {'name': 'K1 Light', 'sex': 'male', 'age_group': 'adulto', 'weights': ['57', '63']},
                ]),
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        metric = form.save()
        self.assertEqual(metric.age_metrics[0]['nome'], 'juvenil')
        self.assertEqual(metric.experience_metrics[0]['minimo_lutas'], 5)
        self.assertEqual(metric.weight_categories[0]['sexo'], 'masculino')


class MatchmakingMetricViewsTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.staff = User.objects.create_user('staff', 'staff@example.com', 'senha123', is_staff=True)
        self.metric = MatchmakingMetric.objects.create(
            name='Regra Teste',
            max_fights_per_athlete=2,
            notes='',
        )

    def test_list_requires_staff(self):
        url = reverse('core:matchmaking-metrics')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.client.force_login(self.staff)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Regra Teste')

    def test_create_metric(self):
        self.client.force_login(self.staff)
        url = reverse('core:matchmaking-metric-create')
        payload = {
            'name': 'Novo GP',
            'max_fights_per_athlete': 3,
            'notes': '',
            'age_metrics_json': json.dumps(default_age_metrics()),
            'experience_metrics_json': json.dumps(default_experience_metrics()),
            'weight_categories_json': json.dumps(default_weight_categories()),
        }
        response = self.client.post(url, payload, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(MatchmakingMetric.objects.filter(name='Novo GP').exists())

    def test_edit_metric(self):
        self.client.force_login(self.staff)
        url = reverse('core:matchmaking-metric-edit', args=[self.metric.pk])
        payload = {
            'name': 'Regra Atualizada',
            'max_fights_per_athlete': 1,
            'notes': 'ajustes',
            'age_metrics_json': json.dumps(default_age_metrics()),
            'experience_metrics_json': json.dumps(default_experience_metrics()),
            'weight_categories_json': json.dumps(default_weight_categories()),
        }
        response = self.client.post(url, payload, follow=True)
        self.assertEqual(response.status_code, 200)
        self.metric.refresh_from_db()
        self.assertEqual(self.metric.name, 'Regra Atualizada')

    def test_delete_metric(self):
        self.client.force_login(self.staff)
        url = reverse('core:matchmaking-metric-delete', args=[self.metric.pk])
        response = self.client.post(url, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(MatchmakingMetric.objects.filter(pk=self.metric.pk).exists())


class MatchmakingServiceTests(TestCase):
    def setUp(self):
        start_at = timezone.now() + timedelta(days=20)
        deadline = start_at - timedelta(days=5)
        self.event = Event.objects.create(
            title='Copa Service',
            location='Ginasio Principal',
            start_at=start_at,
            registration_deadline=deadline,
            registration_fee=100,
            is_published=True,
        )
        self.metric = MatchmakingMetric.objects.create(name='Metrica Teste', max_fights_per_athlete=2)
        self.academy = Academy.objects.create(name='Service Team', city='Curitiba', state='PR')
        self.coach = Coach.objects.create(full_name='Coach Service', academy=self.academy)
        self.staff = get_user_model().objects.create_user(
            'staff-match', 'staff-match@example.com', 'senha123', is_staff=True
        )

    def _create_registration(self, **overrides):
        base = {
            'event': self.event,
            'academy': self.academy,
            'coach': self.coach,
            'cpf': overrides.get('cpf', '00000000000'),
            'athlete_name': overrides.get('athlete_name', 'Atleta Service'),
            'birth_date': overrides.get('birth_date', '2000-01-01'),
            'practice_time': overrides.get('practice_time', AthleteRegistration.PracticeDuration.ONE_TO_THREE),
            'record_wins': overrides.get('record_wins', 2),
            'record_draws': overrides.get('record_draws', 0),
            'record_losses': overrides.get('record_losses', 0),
            'weight_kg': overrides.get('weight_kg', 70),
            'rule_set': overrides.get('rule_set', AthleteRegistration.RuleSet.K1_LIGHT),
            'modality': overrides.get('modality', AthleteRegistration.Modality.AMATEUR),
            'whatsapp': overrides.get('whatsapp', '5511990000000'),
            'sex': overrides.get('sex', AthleteRegistration.Sex.MALE),
            'status': overrides.get('status', AthleteRegistration.Status.CONFIRMED),
        }
        base.update(overrides)
        return AthleteRegistration.objects.create(**base)

    def test_generate_creates_bracket_and_matches(self):
        self._create_registration(athlete_name='Atleta 1', cpf='11111111111', weight_kg=68)
        self._create_registration(athlete_name='Atleta 2', cpf='22222222222', weight_kg=66)

        result = generate_brackets_for_event(event=self.event, metric=self.metric, user=None)

        self.assertEqual(result['brackets_created'], 1, result)
        self.assertFalse(result['unmatched'])
        bracket = MatchmakingBracket.objects.filter(event=self.event).order_by('pk').first()
        self.assertIsNotNone(bracket)
        self.assertEqual(bracket.entries.count(), 2)
        self.assertEqual(bracket.matches.count(), 1)

    def test_generate_collects_unmatched(self):
        self._create_registration(athlete_name='Atleta Sem Sexo', cpf='33333333333', sex=AthleteRegistration.Sex.OTHER)

        result = generate_brackets_for_event(event=self.event, metric=self.metric, user=None)

        self.assertEqual(result['brackets_created'], 0)
        self.assertEqual(len(result['unmatched']), 1)

    def test_rebuild_bracket_matches_after_slot_change(self):
        self._create_registration(athlete_name='Atleta 1', cpf='44444444444', weight_kg=65)
        self._create_registration(athlete_name='Atleta 2', cpf='55555555555', weight_kg=67)
        self._create_registration(athlete_name='Atleta 3', cpf='66666666666', weight_kg=69)
    def test_manual_reorder_view_updates_slots(self):
        self._create_registration(athlete_name='Atleta 1', cpf='12312312312', weight_kg=58)
        self._create_registration(athlete_name='Atleta 2', cpf='32132132132', weight_kg=59)
        self._create_registration(athlete_name='Atleta 3', cpf='45645645645', weight_kg=60)

        generate_brackets_for_event(event=self.event, metric=self.metric, user=None)
        bracket = MatchmakingBracket.objects.filter(event=self.event).order_by('pk').first()
        self.assertIsNotNone(bracket)
        entries = list(bracket.entries.order_by('slot'))

        self.client.force_login(self.staff)
        response = self.client.get(reverse('core:matchmaking-bracket-edit', args=[bracket.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIn('Arraste os cartoes', response.content.decode())

        new_order = [str(entries[1].pk), str(entries[0].pk), str(entries[2].pk)]

        response = self.client.post(
            reverse('core:matchmaking-bracket-edit', args=[bracket.pk]),
            {'order': ','.join(new_order)},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)

        bracket.refresh_from_db()
        ordered_names = list(
            bracket.entries.order_by('slot').values_list('registration__athlete_name', flat=True)
        )
        self.assertEqual(ordered_names[0], entries[1].registration.athlete_name)
        self.assertEqual(ordered_names[1], entries[0].registration.athlete_name)

    def setUp(self):
        start_at = timezone.now() + timedelta(days=10)
        deadline = start_at - timedelta(days=2)
        self.event = Event.objects.create(
            title='Painel Teste',
            location='Arena Central',
            start_at=start_at,
            registration_deadline=deadline,
            registration_fee=80,
            is_published=True,
        )
        self.metric = MatchmakingMetric.objects.create(name='Painel', max_fights_per_athlete=2)
        self.academy = Academy.objects.create(name='Painel Team', city='Sao Paulo', state='SP')
        self.coach = Coach.objects.create(full_name='Coach Painel', academy=self.academy)
        self.staff = get_user_model().objects.create_user('painel', 'painel@example.com', 'senha123', is_staff=True)

    def test_event_view_lists_unassigned_confirmed(self):
        AthleteRegistration.objects.create(
            event=self.event,
            academy=self.academy,
            coach=self.coach,
            cpf='77777777777',
            athlete_name='Atleta Painel',
            birth_date='2000-04-01',
            practice_time=AthleteRegistration.PracticeDuration.ONE_TO_THREE,
            record_wins=2,
            record_draws=0,
            record_losses=0,
            weight_kg=70,
            rule_set=AthleteRegistration.RuleSet.K1_LIGHT,
            modality=AthleteRegistration.Modality.AMATEUR,
            whatsapp='5511990001111',
            sex=AthleteRegistration.Sex.MALE,
            status=AthleteRegistration.Status.CONFIRMED,
        )
        AthleteRegistration.objects.create(
            event=self.event,
            academy=self.academy,
            coach=self.coach,
            cpf='88888888888',
            athlete_name='Sem Categoria',
            birth_date='2001-05-02',
            practice_time=AthleteRegistration.PracticeDuration.ONE_TO_THREE,
            record_wins=1,
            record_draws=0,
            record_losses=0,
            weight_kg=68,
            rule_set=AthleteRegistration.RuleSet.K1_LIGHT,
            modality=AthleteRegistration.Modality.AMATEUR,
            whatsapp='5511990002222',
            sex=AthleteRegistration.Sex.OTHER,
            status=AthleteRegistration.Status.CONFIRMED,
        )

        generate_brackets_for_event(event=self.event, metric=self.metric, user=None)

        self.client.force_login(self.staff)
        url = reverse('core:matchmaking-event', args=[self.event.slug])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('unassigned_registrations', response.context)
        self.assertContains(response, 'Atletas sem chave')
        self.assertContains(response, 'Sem Categoria')


class MatchmakingBracketExportViewTests(TestCase):
    def setUp(self):
        start_at = timezone.now() + timedelta(days=14)
        deadline = start_at - timedelta(days=4)
        self.event = Event.objects.create(
            title='Evento Exportacao',
            location='Centro de Lutas',
            start_at=start_at,
            registration_deadline=deadline,
            registration_fee=150,
            is_published=True,
        )
        self.metric = MatchmakingMetric.objects.create(name='Exportacao', max_fights_per_athlete=2)
        self.academy = Academy.objects.create(name='Export Team', city='Salvador', state='BA')
        self.coach = Coach.objects.create(full_name='Professor Export', academy=self.academy)
        self.staff = get_user_model().objects.create_user('export', 'export@example.com', 'senha123', is_staff=True)

    def _create_registration(self, idx: int) -> AthleteRegistration:
        return AthleteRegistration.objects.create(
            event=self.event,
            academy=self.academy,
            coach=self.coach,
            cpf=f'{idx:011d}',
            athlete_name=f'Atleta Export {idx}',
            birth_date='2000-01-01',
            practice_time=AthleteRegistration.PracticeDuration.ONE_TO_THREE,
            record_wins=idx,
            record_draws=0,
            record_losses=0,
            weight_kg=60 + idx,
            rule_set=AthleteRegistration.RuleSet.K1_LIGHT,
            modality=AthleteRegistration.Modality.AMATEUR,
            whatsapp=f'551199000{idx:04d}',
            sex=AthleteRegistration.Sex.MALE,
            status=AthleteRegistration.Status.CONFIRMED,
        )

    def _build_bracket(self) -> MatchmakingBracket:
        for idx in range(1, 5):
            self._create_registration(idx)
        result = generate_brackets_for_event(event=self.event, metric=self.metric, user=self.staff)
        self.assertGreaterEqual(result['brackets_created'], 1)
        bracket = MatchmakingBracket.objects.filter(event=self.event).order_by('pk').first()
        self.assertIsNotNone(bracket)
        return bracket

    def test_export_all_matches_returns_pdf(self):
        bracket = self._build_bracket()
        self.client.force_login(self.staff)
        url = reverse('core:matchmaking-bracket-export', args=[bracket.pk])
        response = self.client.post(url, {'export_scope': 'all'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertIn('attachment; filename', response['Content-Disposition'])
        self.assertTrue(response.content)

    def test_export_selected_matches(self):
        bracket = self._build_bracket()
        match_id = bracket.matches.order_by('pk').first().pk
        self.client.force_login(self.staff)
        url = reverse('core:matchmaking-bracket-export', args=[bracket.pk])
        response = self.client.post(url, {'export_scope': 'selected', 'match_ids': [str(match_id)]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')

    def test_export_selected_requires_choices(self):
        bracket = self._build_bracket()
        self.client.force_login(self.staff)
        url = reverse('core:matchmaking-bracket-export', args=[bracket.pk])
        response = self.client.post(url, {'export_scope': 'selected'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('core:matchmaking-bracket-detail', args=[bracket.pk]))


