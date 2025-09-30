from __future__ import annotations

from django.db import models
from django.conf import settings

from core.models import TimeStampedModel
from events.models import AthleteRegistration, Event




def default_age_metrics() -> list[dict]:
    return [
        {'nome': 'infantil', 'idade_minima': 9, 'idade_maxima': 11},
        {'nome': 'cadete', 'idade_minima': 12, 'idade_maxima': 14},
        {'nome': 'juvenil', 'idade_minima': 15, 'idade_maxima': 17},
        {'nome': 'adulto', 'idade_minima': 18, 'idade_maxima': 40},
    ]


def default_experience_metrics() -> list[dict]:
    return [
        {'nome': 'iniciante', 'maximo_lutas': 4},
        {'nome': 'avancado', 'minimo_lutas': 5},
    ]


def default_weight_categories() -> list[dict]:
    return [
        {'nome': 'K1 Light', 'sexo': 'masculino', 'faixa_idade': 'infantil', 'faixas_peso': ['28', '32', '37', '42', '47', '+47']},
        {'nome': 'K1 Light', 'sexo': 'masculino', 'faixa_idade': 'cadete', 'faixas_peso': ['57', '63', '69', '74', '79', '84', '89', '+89']},
        {'nome': 'K1 Light', 'sexo': 'masculino', 'faixa_idade': 'juvenil', 'faixas_peso': ['57', '63', '69', '74', '79', '84', '89', '+89']},
        {'nome': 'K1 Light', 'sexo': 'feminino', 'faixa_idade': 'infantil', 'faixas_peso': ['28', '32', '37', '42', '47', '+47']},
        {'nome': 'K1 Light', 'sexo': 'feminino', 'faixa_idade': 'cadete', 'faixas_peso': ['50', '55', '60', '65', '70', '+70']},
        {'nome': 'K1 Light', 'sexo': 'feminino', 'faixa_idade': 'juvenil', 'faixas_peso': ['50', '55', '60', '65', '70', '+70']},
        {'nome': 'K1 Rules', 'sexo': 'masculino', 'faixa_idade': 'juvenil', 'faixas_peso': ['55', '60', '65', '70', '75', '80', '85', '90', '+90']},
        {'nome': 'K1 Rules', 'sexo': 'feminino', 'faixa_idade': 'juvenil', 'faixas_peso': ['50', '55', '60', '65', '+65']},
        {'nome': 'K1 Light', 'sexo': 'masculino', 'faixa_idade': 'adulto', 'faixas_peso': ['57', '63', '69', '74', '79', '84', '89', '+89']},
        {'nome': 'K1 Light', 'sexo': 'feminino', 'faixa_idade': 'adulto', 'faixas_peso': ['50', '55', '60', '65', '70', '+70']},
        {'nome': 'K1 Rules', 'sexo': 'masculino', 'faixa_idade': 'adulto', 'faixas_peso': ['55', '60', '65', '70', '75', '80', '85', '90', '+90']},
        {'nome': 'K1 Rules', 'sexo': 'feminino', 'faixa_idade': 'adulto', 'faixas_peso': ['52', '56', '60', '65', '70', '+70']},
    ]

class MatchmakingMetric(TimeStampedModel):
    name = models.CharField(max_length=255, unique=True)
    max_fights_per_athlete = models.PositiveIntegerField(default=1)
    notes = models.TextField(blank=True)
    age_metrics = models.JSONField(default=default_age_metrics, blank=True)
    experience_metrics = models.JSONField(default=default_experience_metrics, blank=True)
    weight_categories = models.JSONField(default=default_weight_categories, blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self) -> str:  # pragma: no cover - display helper
        return self.name

    def get_age_metrics(self) -> list[dict]:
        return self.age_metrics or []

    def get_experience_metrics(self) -> list[dict]:
        return self.experience_metrics or []

    def get_weight_categories(self) -> list[dict]:
        return self.weight_categories or []


class MatchmakingBracket(TimeStampedModel):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='matchmaking_brackets')
    metric = models.ForeignKey('matchmaking.MatchmakingMetric', on_delete=models.PROTECT, related_name='brackets')
    rule_set = models.CharField(max_length=32, choices=AthleteRegistration.RuleSet.choices)
    experience_label = models.CharField(max_length=64)
    sex = models.CharField(max_length=16, choices=AthleteRegistration.Sex.choices)
    age_group = models.CharField(max_length=32)
    weight_label = models.CharField(max_length=32)
    bracket_index = models.PositiveSmallIntegerField(default=1)
    size = models.PositiveSmallIntegerField(help_text='Numero total de vagas na chave')
    max_fights = models.PositiveSmallIntegerField()
    generated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='generated_brackets')
    is_manual = models.BooleanField(default=False)

    class Meta:
        ordering = ['event', 'rule_set', 'experience_label', 'sex', 'age_group', 'weight_label', 'bracket_index']
        unique_together = (
            'event',
            'metric',
            'rule_set',
            'experience_label',
            'sex',
            'age_group',
            'weight_label',
            'bracket_index',
        )

    def __str__(self) -> str:  # pragma: no cover - display helper
        return f"Chave {self.bracket_index} - {self.title}"

    @property
    def title(self) -> str:
        rule = dict(AthleteRegistration.RuleSet.choices).get(self.rule_set, self.rule_set)
        sex_display = dict(AthleteRegistration.Sex.choices).get(self.sex, self.sex)
        return f"{rule} | {self.experience_label} | {sex_display} | {self.age_group} | {self.weight_label}"


class MatchmakingEntry(TimeStampedModel):
    bracket = models.ForeignKey(MatchmakingBracket, on_delete=models.CASCADE, related_name='entries')
    registration = models.ForeignKey(AthleteRegistration, on_delete=models.CASCADE, related_name='matchmaking_entries')
    seed = models.PositiveSmallIntegerField()
    slot = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ['slot']
        unique_together = (
            ('bracket', 'registration'),
            ('bracket', 'slot'),
        )

    def __str__(self) -> str:  # pragma: no cover - display helper
        return f"{self.registration.athlete_name} (slot {self.slot})"


class MatchmakingMatch(TimeStampedModel):
    bracket = models.ForeignKey(MatchmakingBracket, on_delete=models.CASCADE, related_name='matches')
    round_number = models.PositiveSmallIntegerField()
    position = models.PositiveSmallIntegerField()
    blue_entry = models.ForeignKey(MatchmakingEntry, null=True, blank=True, on_delete=models.SET_NULL, related_name='as_blue')
    red_entry = models.ForeignKey(MatchmakingEntry, null=True, blank=True, on_delete=models.SET_NULL, related_name='as_red')
    blue_source_match = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='advance_as_blue')
    red_source_match = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='advance_as_red')
    winner_entry = models.ForeignKey(MatchmakingEntry, null=True, blank=True, on_delete=models.SET_NULL, related_name='wins_as_winner')
    is_bye = models.BooleanField(default=False)

    class Meta:
        ordering = ['round_number', 'position']

    def __str__(self) -> str:  # pragma: no cover - display helper
        return f"{self.bracket.title} - R{self.round_number} M{self.position}"

    @property
    def round_label(self) -> str:
        total_rounds = self._total_rounds()
        stages = [
            'Final',
            'Semifinal',
            'Quartas de final',
            'Oitavas de final',
            '16-avos de final',
            '32-avos de final',
        ]
        index = total_rounds - self.round_number
        if 0 <= index < len(stages):
            return stages[index]
        if self.round_number == 1:
            return 'Fase inicial'
        return f'Round {self.round_number}'

    def _total_rounds(self) -> int:
        size = max(self.bracket.size, self.bracket.entries.count(), 1)
        rounds = 0
        while size > 1:
            rounds += 1
            size = (size + 1) // 2
        return max(rounds, 1)
