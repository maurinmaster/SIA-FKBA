from __future__ import annotations

from django import forms
import re
from django.core.validators import RegexValidator
from django.utils import timezone

from core.models import Academy, Coach
from events.models import AthleteRegistration, Event


class AthleteRegistrationForm(forms.ModelForm):
    cpf = forms.CharField(
        label='CPF do atleta',
        max_length=11,
        validators=[RegexValidator(r'^\d{11}$', 'Informe o CPF com 11 digitos numericos.')],
        widget=forms.TextInput(
            attrs={
                'class': 'input is-medium',
                'placeholder': 'Somente numeros',
                'maxlength': '11',
                'inputmode': 'numeric',
            }
        ),
    )
    academy_name = forms.CharField(
        label='Academia',
        max_length=255,
        widget=forms.TextInput(
            attrs={'class': 'input is-medium', 'placeholder': 'Nome da academia'}
        ),
    )
    academy_city = forms.CharField(
        label='Cidade da academia',
        max_length=128,
        widget=forms.TextInput(
            attrs={'class': 'input is-medium', 'placeholder': 'Cidade'}
        ),
    )
    academy_state = forms.CharField(
        label='Estado (UF)',
        max_length=64,
        required=False,
        widget=forms.TextInput(
            attrs={'class': 'input is-medium', 'placeholder': 'Ex.: SP'}
        ),
    )
    coach_name = forms.CharField(
        label='Professor(a) responsavel',
        max_length=255,
        widget=forms.TextInput(
            attrs={'class': 'input is-medium', 'placeholder': 'Nome completo do professor(a)'}
        ),
    )
    total_fights = forms.IntegerField(
        label='Quantidade de lutas',
        min_value=0,
        widget=forms.NumberInput(
            attrs={
                'class': 'input is-medium',
                'min': 0,
                'placeholder': 'Total de lutas disputadas',
            }
        ),
    )

    def __init__(self, *args, event: Event | None = None, **kwargs):
        self.event = event
        super().__init__(*args, **kwargs)
        self.fields['event'].widget = forms.HiddenInput()
        self.fields['academy'].widget = forms.HiddenInput()
        self.fields['coach'].widget = forms.HiddenInput()
        self.fields['academy'].required = False
        self.fields['coach'].required = False
        if event:
            self.fields['event'].initial = event

        self.fields['total_fights'].initial = (
            self.instance.total_fights if self.instance.pk else 0
        )
        self.fields['total_fights'].help_text = 'Informe a quantidade total de lutas do atleta.'

        field_configs: dict[str, dict[str, str]] = {
            'athlete_name': {'label': 'Nome do atleta', 'placeholder': 'Nome completo do atleta'},
            'birth_date': {'label': 'Data de nascimento'},
            'practice_time': {'label': 'Tempo de pratica'},
            'weight_kg': {'label': 'Peso (kg)', 'placeholder': 'Peso oficial do atleta'},
            'rule_set': {'label': 'Modalidade'},
            'whatsapp': {'label': 'WhatsApp do atleta', 'placeholder': 'Ex.: 5511987654321'},
            'sex': {'label': 'Sexo'},
        }

        for field_name, config in field_configs.items():
            field = self.fields[field_name]
            field.label = config['label']
            attrs = field.widget.attrs.copy()
            if isinstance(field.widget, forms.Textarea):
                attrs.setdefault('class', 'textarea is-medium')
                attrs.setdefault('rows', 4)
            elif isinstance(field.widget, forms.Select):
                attrs.setdefault('class', 'is-medium')
            else:
                attrs.setdefault('class', 'input is-medium')
            if 'placeholder' in config:
                attrs.setdefault('placeholder', config['placeholder'])
            field.widget.attrs = attrs

        self.fields['birth_date'].widget = forms.DateInput(
            attrs={'type': 'date', 'class': 'input is-medium'}
        )
        self.fields['weight_kg'].widget = forms.NumberInput(
            attrs={'class': 'input is-medium', 'step': '0.1', 'min': '0'}
        )

        self.fields['modality'].widget = forms.HiddenInput()
        self.fields['modality'].required = False
        self.fields['modality'].initial = (
            self.instance.modality
            if getattr(self.instance, 'modality', None)
            else AthleteRegistration.Modality.AMATEUR
        )

        for field_name in ('record_wins', 'record_draws', 'record_losses'):
            field = self.fields[field_name]
            field.widget = forms.HiddenInput()
            field.required = False
            field.initial = getattr(self.instance, field_name, 0)

    def validate_unique(self):
        try:
            super().validate_unique()
        except forms.ValidationError as exc:
            errors = exc.error_dict
            unique_errors = errors.get('__all__', [])
            handled = False
            for error in unique_errors:
                if 'unique_event_cpf' in error.message:
                    self.add_error('cpf', 'Este CPF ja esta inscrito neste evento.')
                    handled = True
            if not handled:
                raise exc

    class Meta:
        model = AthleteRegistration
        fields = [
            'event',
            'academy',
            'coach',
            'cpf',
            'athlete_name',
            'birth_date',
            'practice_time',
            'record_wins',
            'record_draws',
            'record_losses',
            'weight_kg',
            'rule_set',
            'modality',
            'whatsapp',
            'sex',
        ]
        help_texts = {
            'practice_time': 'Selecione o tempo aproximado de pratica do atleta.',
            'rule_set': 'Selecione se o atleta lutara em K1 Light ou K1 Rules.',
            'whatsapp': 'Numero para contato rapido com o atleta ou responsavel.',
        }

    def clean(self):
        cleaned_data = super().clean()

        event = self.event or cleaned_data.get('event')
        if event and not event.is_registration_open:
            raise forms.ValidationError('As inscricoes para este evento estao encerradas.')

        academy_name = (cleaned_data.get('academy_name') or '').strip()
        academy_city = (cleaned_data.get('academy_city') or '').strip()
        academy_state = (cleaned_data.get('academy_state') or '').strip().upper()
        if not academy_name:
            self.add_error('academy_name', 'Informe o nome da academia.')
        if not academy_city:
            self.add_error('academy_city', 'Informe a cidade da academia.')

        academy_obj: Academy | None = None
        if academy_name and academy_city:
            academy_obj = (
                Academy.objects.filter(
                    name__iexact=academy_name,
                    city__iexact=academy_city,
                    state__iexact=academy_state,
                ).first()
            )
            if not academy_obj:
                academy_obj = Academy.objects.create(
                    name=academy_name,
                    city=academy_city,
                    state=academy_state,
                )
            cleaned_data['academy'] = academy_obj

        coach_name = (cleaned_data.get('coach_name') or '').strip()
        cpf = (cleaned_data.get('cpf') or '').strip()
        if not coach_name:
            self.add_error('coach_name', 'Informe o nome do professor responsavel.')
        elif academy_obj:
            coach_obj = (
                Coach.objects.filter(full_name__iexact=coach_name, academy=academy_obj).first()
            )
            if not coach_obj:
                coach_obj = Coach.objects.create(full_name=coach_name, academy=academy_obj)
            cleaned_data['coach'] = coach_obj

        if event and cpf:
            if AthleteRegistration.objects.filter(event=event, cpf=cpf).exclude(pk=self.instance.pk).exists():
                self.add_error('cpf', 'Este CPF ja esta inscrito neste evento.')
        cleaned_data['cpf'] = cpf

        whatsapp_raw = (cleaned_data.get('whatsapp') or '').strip()
        digits = re.sub(r'\D', '', whatsapp_raw)
        if digits:
            if digits.startswith('00'):
                digits = digits[2:]
            if digits.startswith('55'):
                national_number = digits[2:]
            else:
                national_number = digits
            if len(national_number) not in (10, 11):
                self.add_error(
                    'whatsapp',
                    'Informe o WhatsApp com DDI 55, DDD e numero (10 ou 11 digitos).',
                )
            else:
                cleaned_data['whatsapp'] = '55' + national_number
        else:
            self.add_error('whatsapp', 'Informe o WhatsApp com DDD.')

        birth_date = cleaned_data.get('birth_date')
        if birth_date and birth_date > timezone.now().date():
            self.add_error('birth_date', 'A data de nascimento nao pode estar no futuro.')

        total_fights = cleaned_data.get('total_fights')
        if total_fights is None:
            self.add_error('total_fights', 'Informe a quantidade de lutas disputadas.')
        else:
            total = int(total_fights)
            cleaned_data['total_fights'] = total
            cleaned_data['record_wins'] = total
            cleaned_data['record_draws'] = 0
            cleaned_data['record_losses'] = 0

        return cleaned_data


class BulkAcademyForm(forms.Form):
    academy_name = forms.CharField(
        label='Academia',
        max_length=255,
        widget=forms.TextInput(
            attrs={'class': 'input is-medium', 'placeholder': 'Nome da academia'}
        ),
    )
    academy_city = forms.CharField(
        label='Cidade da academia',
        max_length=128,
        widget=forms.TextInput(
            attrs={'class': 'input is-medium', 'placeholder': 'Cidade'}
        ),
    )
    academy_state = forms.CharField(
        label='Estado (UF)',
        max_length=64,
        required=False,
        widget=forms.TextInput(
            attrs={'class': 'input is-medium', 'placeholder': 'Ex.: SP'}
        ),
    )
    coach_name = forms.CharField(
        label='Professor(a) responsavel',
        max_length=255,
        widget=forms.TextInput(
            attrs={'class': 'input is-medium', 'placeholder': 'Nome completo do professor(a)'}
        ),
    )
    modality = forms.ChoiceField(
        label='Modalidade do evento',
        choices=AthleteRegistration.Modality.choices,
        initial=AthleteRegistration.Modality.AMATEUR,
        widget=forms.Select(attrs={'class': 'is-medium'}),
    )

    def clean_academy_state(self):
        return (self.cleaned_data.get('academy_state') or '').strip().upper()

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data.get('academy_name'):
            self.add_error('academy_name', 'Informe o nome da academia.')
        if not cleaned_data.get('academy_city'):
            self.add_error('academy_city', 'Informe a cidade da academia.')
        if not cleaned_data.get('coach_name'):
            self.add_error('coach_name', 'Informe o nome do professor responsavel.')
        return cleaned_data

    def shared_payload(self) -> dict[str, str]:
        if not self.is_valid():
            raise ValueError('Form must be valid before accessing shared payload.')
        return {
            'academy_name': self.cleaned_data['academy_name'].strip(),
            'academy_city': self.cleaned_data['academy_city'].strip(),
            'academy_state': self.cleaned_data['academy_state'],
            'coach_name': self.cleaned_data['coach_name'].strip(),
            'modality': self.cleaned_data['modality'],
        }


class BulkAthleteRegistrationForm(AthleteRegistrationForm):
    SHARED_FIELDS = ('academy_name', 'academy_city', 'academy_state', 'coach_name', 'modality')

    def __init__(self, *args, shared: dict[str, str] | None = None, **kwargs):
        self.shared = shared or {}
        super().__init__(*args, **kwargs)
        for field in self.SHARED_FIELDS:
            if field in self.fields:
                field_obj = self.fields[field]
                field_obj.widget = forms.HiddenInput()
                field_obj.required = False
                if field in self.shared:
                    field_obj.initial = self.shared[field]
        if 'modality' in self.shared:
            self.fields['modality'].initial = self.shared['modality']

    def has_shared_initial(self) -> bool:
        return all(self.fields.get(field) and self.fields[field].initial for field in self.SHARED_FIELDS if field != 'academy_state')




class AthleteRegistrationLookupForm(forms.Form):
    cpf = forms.CharField(
        label='CPF',
        max_length=11,
        validators=[RegexValidator(r'^\d{11}$', 'Informe o CPF com 11 digitos.')],
        widget=forms.TextInput(
            attrs={
                'class': 'input',
                'placeholder': 'Somente numeros',
                'maxlength': '11',
                'inputmode': 'numeric',
            }
        ),
    )
    birth_date = forms.DateField(
        label='Data de nascimento',
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'input'}),
    )

    def clean_cpf(self):
        return self.cleaned_data['cpf'].strip()




class EventForm(forms.ModelForm):
    start_at = forms.DateTimeField(
        label='Data e hora do evento',
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        input_formats=['%Y-%m-%dT%H:%M'],
    )
    registration_deadline = forms.DateTimeField(
        label='Encerramento das inscrições',
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        input_formats=['%Y-%m-%dT%H:%M'],
    )

    class Meta:
        model = Event
        fields = [
            'title',
            'location',
            'description',
            'start_at',
            'registration_deadline',
            'registration_fee',
            'is_free',
            'rules_document',
            'is_published',
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 4}),
            'registration_fee': forms.NumberInput(attrs={'step': '0.01', 'min': '0'}),
            'rules_document': forms.ClearableFileInput(attrs={'class': 'file-input'}),
        }
        labels = {
            'title': 'Nome do evento',
            'location': 'Local',
            'description': 'Descrição',
            'registration_fee': 'Valor da inscrição (R$)',
            'rules_document': 'Circular ou regulamento (PDF)',
            'is_published': 'Publicar imediatamente',
        }

    def clean(self):
        cleaned_data = super().clean()
        start_at = cleaned_data.get('start_at')
        deadline = cleaned_data.get('registration_deadline')
        if start_at and start_at <= timezone.now():
            self.add_error('start_at', 'A data do evento deve estar no futuro.')
        if start_at and deadline and deadline >= start_at:
            self.add_error('registration_deadline', 'O encerramento das inscrições deve ocorrer antes do início do evento.')
        return cleaned_data


