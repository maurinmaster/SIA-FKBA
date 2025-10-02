from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.models import Academy, Coach
from events.models import AthleteRegistration, Event


class Command(BaseCommand):
    help = 'Cria 40 inscrições de teste com faixas de idade e peso distintas.'

    def add_arguments(self, parser):
        parser.add_argument('--event-id', type=int, help='ID de um evento existente para receber as inscrições.')

    def handle(self, *args, **options):
        event = self._get_or_create_event(options.get('event_id'))
        athletes = self._build_dataset()

        created = 0
        for index, data in enumerate(athletes, start=1):
            academy, _ = Academy.objects.get_or_create(
                name=data['academy'],
                city=data['city'],
                defaults={'state': data['state']},
            )
            coach, _ = Coach.objects.get_or_create(
                full_name=data['coach'],
                academy=academy,
                defaults={'whatsapp': data['whatsapp'], 'email': ''},
            )
            rule_set = data.get('rule_set')
            if not rule_set:
                rule_set = AthleteRegistration.RuleSet.K1_LIGHT if index % 2 else AthleteRegistration.RuleSet.K1_RULES
            defaults = {
                'academy': academy,
                'coach': coach,
                'athlete_name': data['name'],
                'birth_date': data['birth_date'],
                'practice_time': data['practice_time'],
                'rule_set': rule_set,
                'record_wins': data['wins'],
                'record_draws': data['draws'],
                'record_losses': data['losses'],
                'weight_kg': Decimal(str(data['weight_kg'])),
                'modality': data['modality'],
                'whatsapp': data['whatsapp'],
                'sex': data['sex'],
                'status': data['status'],
            }
            _, created_flag = AthleteRegistration.objects.update_or_create(
                event=event,
                cpf=data['cpf'],
                defaults=defaults,
            )
            if created_flag:
                created += 1
        self.stdout.write(self.style.SUCCESS(f'{created} inscrições criadas para o evento "{event.title}".'))

    def _get_or_create_event(self, event_id: int | None) -> Event:
        if event_id:
            try:
                return Event.objects.get(pk=event_id)
            except Event.DoesNotExist:
                raise CommandError(f'Evento com id {event_id} não encontrado.')
        start_at = timezone.now() + timedelta(days=20)
        deadline = start_at - timedelta(days=7)
        event, _ = Event.objects.get_or_create(
            title='Circuito Teste Automático',
            defaults={
                'location': 'Ginásio Municipal',
                'start_at': start_at,
                'registration_deadline': deadline,
                'registration_fee': Decimal('150.00'),
                'is_published': True,
            },
        )
        return event