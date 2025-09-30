from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from math import ceil
from typing import Dict, Iterable, List, Tuple

from django.db import transaction
from django.utils import timezone

from events.models import AthleteRegistration, Event
from matchmaking.models import (
    MatchmakingBracket,
    MatchmakingEntry,
    MatchmakingMatch,
    MatchmakingMetric,
)

logger = logging.getLogger(__name__)


class MatchmakingError(Exception):
    """Base error for matchmaking services."""


class ClassificationError(MatchmakingError):
    """Raised when an athlete cannot be classified for a bracket."""


@dataclass(frozen=True)
class ClassifiedRegistration:
    registration: AthleteRegistration
    rule_set_value: str
    rule_set_label: str
    sex_value: str
    experience_label: str
    age_group: str
    weight_label: str

    def group_key(self) -> Tuple[str, str, str, str, str]:
        return (
            self.rule_set_value,
            self.experience_label,
            self.sex_value,
            self.age_group,
            self.weight_label,
        )


@dataclass(frozen=True)
class WeightRange:
    label: str
    lower: Decimal
    upper: Decimal | None

    def contains(self, weight: Decimal) -> bool:
        if self.upper is None:
            return weight > self.lower
        if self.lower == Decimal('0'):
            return weight <= self.upper
        return self.lower < weight <= self.upper


@dataclass
class MetricProfile:
    age_groups: List[dict]
    experience_groups: List[dict]
    weight_index: Dict[Tuple[str, str, str], List[WeightRange]]


def generate_brackets_for_event(
    *,
    event: Event,
    metric: MatchmakingMetric,
    user=None,
    replace_existing: bool = True,
) -> dict:
    """Generate brackets for confirmed registrations using the provided metric."""

    profile = _build_metric_profile(metric)
    reference_date = (event.start_at.date() if event.start_at else timezone.now().date())

    confirmed = (
        event.registrations.select_related('academy', 'coach')
        .filter(status=AthleteRegistration.Status.CONFIRMED)
        .order_by('created_at')
    )

    grouped: Dict[Tuple[str, str, str, str, str], List[ClassifiedRegistration]] = defaultdict(list)
    unmatched: List[tuple[AthleteRegistration, str]] = []

    for registration in confirmed:
        try:
            classified = _classify_registration(registration, profile, reference_date)
        except ClassificationError as exc:
            unmatched.append((registration, str(exc)))
            logger.debug('Skipping registration %s: %s', registration.pk, exc)
            continue
        grouped[classified.group_key()].append(classified)

    removed = 0
    if replace_existing:
        existing_qs = MatchmakingBracket.objects.filter(event=event, metric=metric)
        removed = existing_qs.count()
    else:
        existing_qs = MatchmakingBracket.objects.none()

    created_brackets: List[MatchmakingBracket] = []
    group_summaries = []
    matches_created = 0

    with transaction.atomic():
        if replace_existing and existing_qs.exists():
            existing_qs.delete()

        for key in sorted(grouped.keys()):
            participants = grouped[key]
            rule_set_value, experience_label, sex_value, age_group, weight_label = key
            sex_display = dict(AthleteRegistration.Sex.choices).get(sex_value, sex_value)
            rule_set_label = participants[0].rule_set_label if participants else dict(AthleteRegistration.RuleSet.choices).get(rule_set_value, rule_set_value)

            sorted_participants = sorted(
                participants,
                key=lambda item: (
                    item.registration.weight_kg,
                    item.registration.birth_date or timezone.now().date(),
                    item.registration.pk,
                ),
            )

            capacity = max(1, 2 ** metric.max_fights_per_athlete)
            chunks = _split_into_chunks(sorted_participants, capacity)

            for index, chunk in enumerate(chunks, start=1):
                size = _next_power_of_two(len(chunk)) if len(chunk) > 1 else len(chunk)
                bracket = MatchmakingBracket.objects.create(
                    event=event,
                    metric=metric,
                    rule_set=rule_set_value,
                    experience_label=experience_label,
                    sex=sex_value,
                    age_group=age_group,
                    weight_label=weight_label,
                    bracket_index=index,
                    size=size or 1,
                    max_fights=metric.max_fights_per_athlete,
                    generated_by=user if getattr(user, 'is_authenticated', False) else None,
                    is_manual=False,
                )

                for seed, classification in enumerate(chunk, start=1):
                    MatchmakingEntry.objects.create(
                        bracket=bracket,
                        registration=classification.registration,
                        seed=seed,
                        slot=seed,
                    )

                matches_created += _build_matches_for_bracket(bracket)
                created_brackets.append(bracket)

            group_summaries.append(
                {
                    'rule_set': rule_set_label,
                    'experience': experience_label,
                    'sex': sex_display,
                    'age_group': age_group,
                    'weight': weight_label,
                    'athlete_count': len(participants),
                    'bracket_count': len(chunks),
                }
            )

    return {
        'brackets_created': len(created_brackets),
        'matches_created': matches_created,
        'replaced': removed,
        'groups': group_summaries,
        'unmatched': [
            {
                'registration_id': registration.pk,
                'athlete': registration.athlete_name,
                'reason': reason,
            }
            for registration, reason in unmatched
        ],
        'created_brackets': created_brackets,
    }


def rebuild_bracket_matches(bracket: MatchmakingBracket) -> int:
    """Rebuild all matches for a bracket after manual reseeding."""
    return _build_matches_for_bracket(bracket)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _classify_registration(
    registration: AthleteRegistration,
    profile: MetricProfile,
    reference_date,
) -> ClassifiedRegistration:
    rule_set_value = registration.rule_set
    if not rule_set_value:
        raise ClassificationError('Inscricao sem regra de luta definida.')

    rule_set_label = registration.get_rule_set_display()

    sex_value = registration.sex
    if sex_value not in (AthleteRegistration.Sex.MALE, AthleteRegistration.Sex.FEMALE):
        raise ClassificationError('Metricas atuais contemplam apenas sexo masculino ou feminino.')

    if registration.weight_kg is None:
        raise ClassificationError('Peso nao informado.')

    if registration.birth_date is None:
        raise ClassificationError('Data de nascimento nao informada.')

    age = _age_on_date(registration.birth_date, reference_date)
    age_group = _match_age_group(profile.age_groups, age)
    experience_label = _match_experience_group(profile.experience_groups, registration.total_fights)

    sex_metric = 'masculino' if sex_value == AthleteRegistration.Sex.MALE else 'feminino'
    weight_label = _match_weight_group(
        profile.weight_index,
        rule_set_label.lower(),
        sex_metric,
        age_group,
        Decimal(registration.weight_kg),
    )

    return ClassifiedRegistration(
        registration=registration,
        rule_set_value=rule_set_value,
        rule_set_label=rule_set_label,
        sex_value=sex_value,
        experience_label=experience_label,
        age_group=age_group,
        weight_label=weight_label,
    )


def _build_metric_profile(metric: MatchmakingMetric) -> MetricProfile:
    age_groups = metric.get_age_metrics()
    experience_groups = metric.get_experience_metrics()
    weight_index: Dict[Tuple[str, str, str], List[WeightRange]] = {}

    for entry in metric.get_weight_categories():
        rule_name = str(entry.get('nome', '')).strip().lower()
        sex = str(entry.get('sexo', '')).strip().lower()
        age_group = str(entry.get('faixa_idade', '')).strip()
        weights = entry.get('faixas_peso') or []
        if not rule_name or not sex or not age_group or not weights:
            logger.debug('Ignorando categoria de peso mal formatada: %s', entry)
            continue
        key = (rule_name, sex, age_group)
        weight_index[key] = _build_weight_ranges(weights)

    return MetricProfile(
        age_groups=age_groups,
        experience_groups=experience_groups,
        weight_index=weight_index,
    )


def _build_weight_ranges(weights: Iterable[str]) -> List[WeightRange]:
    ranges: List[WeightRange] = []
    previous_upper: Decimal | None = None
    for raw in weights:
        token = str(raw).strip()
        if not token:
            continue
        value, is_plus = _parse_weight_token(token)
        lower = previous_upper if previous_upper is not None else Decimal('0')
        if is_plus:
            ranges.append(WeightRange(label=token, lower=lower, upper=None))
        else:
            ranges.append(WeightRange(label=token, lower=lower, upper=value))
            previous_upper = value
        if is_plus:
            previous_upper = value
    return ranges


def _parse_weight_token(token: str) -> Tuple[Decimal, bool]:
    cleaned = token.lower().replace('kg', '').replace(' ', '')
    is_plus = cleaned.startswith('+') or cleaned.endswith('+')
    cleaned = cleaned.replace('+', '')
    cleaned = cleaned.replace(',', '.')
    if not cleaned:
        raise ClassificationError(f'Faixa de peso invalida: "{token}".')
    try:
        value = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ClassificationError(f'Nao foi possivel interpretar a faixa de peso "{token}".') from exc
    return value, is_plus


def _age_on_date(birth_date, reference_date) -> int:
    years = reference_date.year - birth_date.year
    if (reference_date.month, reference_date.day) < (birth_date.month, birth_date.day):
        years -= 1
    return years


def _match_age_group(age_groups: Iterable[dict], age: int) -> str:
    for group in age_groups:
        min_age = group.get('idade_minima') or group.get('min_age')
        max_age = group.get('idade_maxima') or group.get('max_age')
        name = group.get('nome') or group.get('name')
        if name is None:
            continue
        min_age = int(min_age) if min_age is not None else 0
        max_age = int(max_age) if max_age is not None else 200
        if min_age <= age <= max_age:
            return str(name)
    raise ClassificationError('Idade fora das faixas configuradas.')


def _match_experience_group(experience_groups: Iterable[dict], total_fights: int) -> str:
    for group in experience_groups:
        name = group.get('nome') or group.get('name')
        if not name:
            continue
        min_fights = group.get('minimo_lutas', group.get('min_fights'))
        max_fights = group.get('maximo_lutas', group.get('max_fights'))
        if min_fights is not None and total_fights < int(min_fights):
            continue
        if max_fights is not None and total_fights > int(max_fights):
            continue
        return str(name)
    raise ClassificationError('Total de lutas fora das metricas configuradas.')


def _match_weight_group(
    weight_index: Dict[Tuple[str, str, str], List[WeightRange]],
    rule_set_label: str,
    sex_metric: str,
    age_group: str,
    weight: Decimal,
) -> str:
    key = (rule_set_label, sex_metric, age_group)
    ranges = weight_index.get(key)
    if not ranges:
        raise ClassificationError('Sem configuracao de peso para esta combinacao de regras, sexo e faixa etaria.')
    for weight_range in ranges:
        if weight_range.contains(weight):
            return weight_range.label
    raise ClassificationError('Peso fora das faixas configuradas para esta combinacao.')


def _split_into_chunks(participants: List[ClassifiedRegistration], capacity: int) -> List[List[ClassifiedRegistration]]:
    if capacity <= 0:
        capacity = 1
    chunks = [participants[i:i + capacity] for i in range(0, len(participants), capacity)]
    if len(chunks) > 1 and len(chunks[-1]) == 1:
        previous = chunks[-2]
        last = chunks[-1]
        if len(previous) > 2:
            last.insert(0, previous.pop())
        elif len(previous) + len(last) <= capacity:
            previous.extend(last)
            chunks.pop()
    return chunks if chunks else [[]]


def _next_power_of_two(value: int) -> int:
    if value <= 1:
        return max(1, value)
    result = 1
    while result < value:
        result <<= 1
    return result


def _build_matches_for_bracket(bracket: MatchmakingBracket) -> int:
    bracket.matches.all().delete()

    entries = list(bracket.entries.order_by('slot'))
    if not entries:
        return 0
    if len(entries) == 1:
        return 0

    size = max(bracket.size, _next_power_of_two(len(entries)))
    if size != bracket.size:
        MatchmakingBracket.objects.filter(pk=bracket.pk).update(size=size)
        bracket.size = size
    slots: List[MatchmakingEntry | None] = [None] * size
    for entry in entries:
        if 1 <= entry.slot <= size:
            slots[entry.slot - 1] = entry

    created_matches: List[MatchmakingMatch] = []
    round_matches: List[MatchmakingMatch] = []
    position = 1
    for index in range(0, size, 2):
        blue = slots[index] if index < len(slots) else None
        red = slots[index + 1] if (index + 1) < len(slots) else None
        if not blue and not red:
            continue
        is_bye = (bool(blue) != bool(red))
        match = MatchmakingMatch.objects.create(
            bracket=bracket,
            round_number=1,
            position=position,
            blue_entry=blue,
            red_entry=red,
            is_bye=is_bye,
        )
        position += 1
        if is_bye:
            match.winner_entry = blue or red
            match.save(update_fields=['winner_entry'])
        round_matches.append(match)
        created_matches.append(match)

    current_round = round_matches
    round_number = 2
    while len(current_round) > 1:
        next_round: List[MatchmakingMatch] = []
        position = 1
        for idx in range(0, len(current_round), 2):
            blue_source = current_round[idx]
            red_source = current_round[idx + 1] if (idx + 1) < len(current_round) else None
            match = MatchmakingMatch.objects.create(
                bracket=bracket,
                round_number=round_number,
                position=position,
                blue_source_match=blue_source,
                red_source_match=red_source,
                blue_entry=blue_source.winner_entry if blue_source and blue_source.winner_entry else None,
                red_entry=red_source.winner_entry if red_source and red_source.winner_entry else None,
            )
            created_matches.append(match)
            next_round.append(match)
            position += 1
        current_round = next_round
        round_number += 1

    return len(created_matches)

