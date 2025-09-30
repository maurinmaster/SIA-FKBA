import os
import sys
from datetime import date
from decimal import Decimal
from itertools import cycle
from pathlib import Path

import django
from django.db import transaction

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "fkba_platform.settings")
django.setup()

from core.models import Coach
from events.models import AthleteRegistration, Event


MALE_NAMES = [
    "Alex",
    "Bruno",
    "Caio",
    "Diego",
    "Eduardo",
    "Felipe",
    "Gabriel",
    "Henrique",
    "Igor",
    "Joao",
    "Leandro",
    "Marcos",
    "Nicolas",
    "Otavio",
    "Paulo",
    "Rafael",
    "Sergio",
    "Tiago",
    "Ulisses",
    "Vitor",
]

FEMALE_NAMES = [
    "Ana",
    "Beatriz",
    "Clara",
    "Daniela",
    "Elisa",
    "Fernanda",
    "Giulia",
    "Helena",
    "Isabela",
    "Juliana",
    "Karina",
    "Larissa",
    "Marina",
    "Natalia",
    "Olivia",
    "Patricia",
    "Renata",
    "Sabrina",
    "Talita",
    "Vanessa",
]

LAST_NAMES = [
    "Silva",
    "Souza",
    "Almeida",
    "Ferreira",
    "Gomes",
    "Melo",
    "Rocha",
    "Barbosa",
    "Costa",
    "Dias",
    "Farias",
    "Pereira",
    "Rezende",
    "Moreira",
    "Teixeira",
    "Vieira",
    "Cardoso",
    "Cavalcante",
    "Azevedo",
    "Santana",
]

PRACTICE_OPTIONS = [
    AthleteRegistration.PracticeDuration.LESS_THAN_ONE,
    AthleteRegistration.PracticeDuration.ONE_TO_THREE,
    AthleteRegistration.PracticeDuration.THREE_TO_FIVE,
    AthleteRegistration.PracticeDuration.MORE_THAN_FIVE,
]

RECORD_PATTERNS = [
    (2, 0, 1),
    (4, 1, 0),
    (6, 2, 1),
    (9, 1, 2),
    (12, 2, 3),
]

MODALITIES = [
    AthleteRegistration.Modality.AMATEUR,
    AthleteRegistration.Modality.PROFESSIONAL,
]

STATUSES = [
    AthleteRegistration.Status.PENDING,
    AthleteRegistration.Status.CONFIRMED,
]

RULE_SETS = [
    AthleteRegistration.RuleSet.K1_LIGHT,
    AthleteRegistration.RuleSet.K1_RULES,
]


def generate_profiles():
    profiles = []
    for index in range(40):
        if index % 2 == 0:
            first_name = MALE_NAMES[index // 2]
            sex = AthleteRegistration.Sex.MALE
        else:
            first_name = FEMALE_NAMES[index // 2]
            sex = AthleteRegistration.Sex.FEMALE

        last_name = LAST_NAMES[index % len(LAST_NAMES)]
        if index >= len(LAST_NAMES):
            last_name = f"{last_name} Junior"

        athlete_name = f"{first_name} {last_name}"
        birth_year = 1985 + (index % 20)
        birth_month = (index % 12) + 1
        birth_day = ((index * 2) % 28) + 1
        birth_date = date(birth_year, birth_month, birth_day)

        practice_time = PRACTICE_OPTIONS[index % len(PRACTICE_OPTIONS)]
        wins, draws, losses = RECORD_PATTERNS[index % len(RECORD_PATTERNS)]
        modality = MODALITIES[index % len(MODALITIES)]
        status = STATUSES[index % len(STATUSES)]

        weight = (
            Decimal("60.0")
            + Decimal(index % 15)
            + (Decimal("0.5") * Decimal((index % 3) + 1))
        ).quantize(Decimal("0.01"))

        whatsapp = f"+5571{90000000 + index:08d}"

        profiles.append(
            {
                "name": athlete_name,
                "sex": sex,
                "birth_date": birth_date,
                "practice_time": practice_time,
                "wins": wins,
                "draws": draws,
                "losses": losses,
                "weight": weight,
                "modality": modality,
                "whatsapp": whatsapp,
                "status": status,
            }
        )
    return profiles


def seed_registrations(event):
    profiles = generate_profiles()
    coaches = list(Coach.objects.select_related("academy"))
    if not coaches:
        raise RuntimeError("Nenhum coach cadastrado para vincular aos atletas.")

    coach_cycle = cycle(coaches)
    created = 0

    with transaction.atomic():
        for profile in profiles:
            coach = next(coach_cycle)
            for rule in RULE_SETS:
                defaults = {
                    "academy": coach.academy,
                    "coach": coach,
                    "birth_date": profile["birth_date"],
                    "practice_time": profile["practice_time"],
                    "record_wins": profile["wins"],
                    "record_draws": profile["draws"],
                    "record_losses": profile["losses"],
                    "weight_kg": profile["weight"],
                    "modality": profile["modality"],
                    "whatsapp": profile["whatsapp"],
                    "sex": profile["sex"],
                    "notes": f"Seeded registration for {rule.replace('_', ' ').title()}",
                    "status": profile["status"],
                    "cpf": None,
                }
                _, was_created = AthleteRegistration.objects.get_or_create(
                    event=event,
                    athlete_name=profile["name"],
                    rule_set=rule,
                    defaults=defaults,
                )
                if was_created:
                    created += 1
    return created


def main():
    event = (
        Event.objects.filter(is_published=True).order_by("start_at").first()
        or Event.objects.order_by("start_at").first()
    )
    if event is None:
        raise RuntimeError("Nenhum evento encontrado para receber registros.")

    created = seed_registrations(event)
    print(f"Seed concluido. Registros criados: {created}")


if __name__ == "__main__":
    main()
