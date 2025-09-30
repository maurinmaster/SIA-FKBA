from __future__ import annotations

import json
import re
from typing import Any

from django import forms

from matchmaking.models import (
    MatchmakingEntry,
    MatchmakingMetric,
    default_age_metrics,
    default_experience_metrics,
    default_weight_categories,
)


class MatchmakingMetricForm(forms.ModelForm):
    age_metrics_json = forms.CharField(
        label='Métricas de idade (JSON)',
        widget=forms.Textarea(attrs={'rows': 6, 'class': 'textarea is-medium monospace'}),
        required=True,
    )
    experience_metrics_json = forms.CharField(
        label='Métricas de experiência (JSON)',
        widget=forms.Textarea(attrs={'rows': 4, 'class': 'textarea is-medium monospace'}),
        required=True,
    )
    weight_categories_json = forms.CharField(
        label='Categorias de peso por modalidade (JSON)',
        widget=forms.Textarea(attrs={'rows': 12, 'class': 'textarea is-medium monospace'}),
        required=True,
        help_text='Lista de objetos com nome, sexo, faixa_idade e faixas_peso. Ex.: [{"nome": "K1 Light", ...}]',
    )

    class Meta:
        model = MatchmakingMetric
        fields = ['name', 'max_fights_per_athlete', 'notes']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'input is-medium', 'placeholder': 'Nome da métrica'}),
            'max_fights_per_athlete': forms.NumberInput(attrs={'class': 'input is-medium', 'min': 1}),
            'notes': forms.Textarea(attrs={'class': 'textarea is-medium', 'rows': 3}),
        }
        labels = {
            'name': 'Nome da métrica',
            'max_fights_per_athlete': 'Quantidade máxima de lutas por atleta',
            'notes': 'Observações',
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        metric = self.instance if self.instance and self.instance.pk else None
        age_data = metric.age_metrics if metric else default_age_metrics()
        exp_data = metric.experience_metrics if metric else default_experience_metrics()
        weight_data = metric.weight_categories if metric else default_weight_categories()
        self.fields['age_metrics_json'].initial = self._to_pretty_json(
            self._normalize_age_metrics(age_data, strict=False)
        )
        self.fields['experience_metrics_json'].initial = self._to_pretty_json(
            self._normalize_experience_metrics(exp_data, strict=False)
        )
        self.fields['weight_categories_json'].initial = self._to_pretty_json(
            self._normalize_weight_categories(weight_data, strict=False)
        )

    def clean_age_metrics_json(self) -> list[dict]:
        data = self._validate_json('age_metrics_json')
        normalized = self._normalize_age_metrics(data, strict=True)
        if not normalized:
            raise forms.ValidationError('Informe ao menos uma faixa de idade.')
        return normalized

    def clean_experience_metrics_json(self) -> list[dict]:
        data = self._validate_json('experience_metrics_json')
        normalized = self._normalize_experience_metrics(data, strict=True)
        if not normalized:
            raise forms.ValidationError('Informe ao menos uma métrica de experiência.')
        return normalized

    def clean_weight_categories_json(self) -> list[dict]:
        data = self._validate_json('weight_categories_json')
        normalized = self._normalize_weight_categories(data, strict=True)
        if not normalized:
            raise forms.ValidationError('Informe ao menos uma categoria de peso.')
        return normalized

    def save(self, commit: bool = True):
        metric: MatchmakingMetric = super().save(commit=False)
        metric.age_metrics = self.cleaned_data['age_metrics_json']
        metric.experience_metrics = self.cleaned_data['experience_metrics_json']
        metric.weight_categories = self.cleaned_data['weight_categories_json']
        if commit:
            metric.save()
        return metric

    # Helpers -----------------------------------------------------------------

    def _validate_json(self, field_name: str) -> list[dict]:
        raw = self.cleaned_data.get(field_name, '')
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise forms.ValidationError(f'JSON inválido: {exc.msg}') from exc
        if not isinstance(parsed, list):
            raise forms.ValidationError('Informe uma lista de objetos JSON.')
        for item in parsed:
            if not isinstance(item, dict):
                raise forms.ValidationError('Cada item deve ser um objeto JSON {}.')
        return parsed

    def _normalize_age_metrics(self, data: list[dict], *, strict: bool) -> list[dict]:
        normalized: list[dict] = []
        for item in data:
            try:
                normalized.append(self._normalize_age_metric(item))
            except forms.ValidationError as exc:
                if strict:
                    raise exc
        if not normalized and not strict:
            return default_age_metrics()
        return normalized

    def _normalize_age_metric(self, item: dict) -> dict:
        nome = (item.get('nome') or item.get('name') or '').strip()
        if not nome:
            raise forms.ValidationError('Campo "nome" é obrigatório nas métricas de idade.')
        min_age = item.get('idade_minima', item.get('min_age'))
        max_age = item.get('idade_maxima', item.get('max_age'))
        if min_age is None or max_age is None:
            raise forms.ValidationError('Use as chaves "idade_minima" e "idade_maxima".')
        try:
            min_age_int = int(min_age)
            max_age_int = int(max_age)
        except (TypeError, ValueError) as exc:
            raise forms.ValidationError('Idades devem ser números inteiros.') from exc
        if min_age_int > max_age_int:
            raise forms.ValidationError('A idade mínima não pode ser maior que a máxima.')
        return {'nome': nome, 'idade_minima': min_age_int, 'idade_maxima': max_age_int}

    def _normalize_experience_metrics(self, data: list[dict], *, strict: bool) -> list[dict]:
        normalized: list[dict] = []
        for item in data:
            try:
                normalized.append(self._normalize_experience_metric(item))
            except forms.ValidationError as exc:
                if strict:
                    raise exc
        if not normalized and not strict:
            return default_experience_metrics()
        return normalized

    def _normalize_experience_metric(self, item: dict) -> dict:
        nome = (item.get('nome') or item.get('name') or '').strip()
        if not nome:
            raise forms.ValidationError('Campo "nome" é obrigatório nas métricas de experiência.')
        minimo = item.get('minimo_lutas', item.get('min_fights'))
        maximo = item.get('maximo_lutas', item.get('max_fights'))
        data: dict[str, Any] = {'nome': nome}
        if minimo is not None:
            try:
                data['minimo_lutas'] = int(minimo)
            except (TypeError, ValueError) as exc:
                raise forms.ValidationError('O campo "minimo_lutas" deve ser numérico.') from exc
        if maximo is not None:
            try:
                data['maximo_lutas'] = int(maximo)
            except (TypeError, ValueError) as exc:
                raise forms.ValidationError('O campo "maximo_lutas" deve ser numérico.') from exc
        if 'minimo_lutas' not in data and 'maximo_lutas' not in data:
            raise forms.ValidationError('Informe "minimo_lutas" ou "maximo_lutas".')
        return data

    def _normalize_weight_categories(self, data: list[dict], *, strict: bool) -> list[dict]:
        normalized: list[dict] = []
        for item in data:
            try:
                normalized.append(self._normalize_weight_category(item))
            except forms.ValidationError as exc:
                if strict:
                    raise exc
        if not normalized and not strict:
            return default_weight_categories()
        return normalized

    def _normalize_weight_category(self, item: dict) -> dict:
        nome = (item.get('nome') or item.get('name') or '').strip()
        if not nome:
            raise forms.ValidationError('Campo "nome" é obrigatório nas categorias de peso.')
        sexo_raw = (item.get('sexo') or item.get('sex') or '').strip().lower()
        sexo_map = {
            'masculino': 'masculino',
            'm': 'masculino',
            'male': 'masculino',
            'feminino': 'feminino',
            'f': 'feminino',
            'female': 'feminino',
        }
        if sexo_raw not in sexo_map:
            raise forms.ValidationError('Use "masculino" ou "feminino" no campo sexo.')
        faixa = (
            item.get('faixa_idade')
            or item.get('faixa-de-idade')
            or item.get('age_group')
            or ''
        ).strip()
        if not faixa:
            raise forms.ValidationError('Campo "faixa_idade" é obrigatório nas categorias de peso.')
        pesos = item.get('faixas_peso') or item.get('faixas-de-peso') or item.get('weights')
        if pesos is None:
            raise forms.ValidationError('Campo "faixas_peso" é obrigatório nas categorias de peso.')
        if isinstance(pesos, str):
            pesos = [p.strip() for p in re.split(r'[;,/]', pesos) if p.strip()]
        if not isinstance(pesos, (list, tuple)) or not pesos:
            raise forms.ValidationError('Cada categoria deve trazer a lista "faixas_peso".')
        pesos_norm = [str(p).replace('KG', 'Kg').strip() for p in pesos]
        return {
            'nome': nome,
            'sexo': sexo_map[sexo_raw],
            'faixa_idade': faixa,
            'faixas_peso': pesos_norm,
        }

    def _to_pretty_json(self, data: list[dict]) -> str:
        return json.dumps(data, ensure_ascii=False, indent=2)

class MatchmakingEntrySlotForm(forms.ModelForm):
    class Meta:
        model = MatchmakingEntry
        fields = ['slot']
        labels = {'slot': 'Posicao'}
        widgets = {
            'slot': forms.NumberInput(attrs={'class': 'input is-small', 'min': 1}),
        }


class BaseMatchmakingEntryFormSet(forms.BaseModelFormSet):
    bracket_size: int = 0

    def clean(self) -> None:
        super().clean()
        seen: set[int] = set()
        size = getattr(self, 'bracket_size', 0)
        for form in self.forms:
            if not hasattr(form, 'cleaned_data') or not form.cleaned_data:
                continue
            if form.cleaned_data.get('DELETE'):
                continue
            slot = form.cleaned_data.get('slot')
            if slot is None:
                form.add_error('slot', 'Informe a posicao desejada.')
                continue
            if size and (slot < 1 or slot > size):
                form.add_error('slot', f'Use valores entre 1 e {size}.')
            if slot in seen:
                form.add_error('slot', 'Cada posicao deve ser unica.')
            seen.add(slot)

