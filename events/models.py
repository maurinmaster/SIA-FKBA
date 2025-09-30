from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.template.defaultfilters import slugify
from django.urls import reverse
from django.utils import timezone

from core.models import Academy, Coach, TimeStampedModel


class Event(TimeStampedModel):
    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True, blank=True)
    location = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    start_at = models.DateTimeField()
    registration_deadline = models.DateTimeField(help_text='Data limite para novas inscrições.')
    registration_fee = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00'))],
    )
    is_free = models.BooleanField(default=False)
    rules_document = models.FileField(upload_to='event_rules/', blank=True)
    is_published = models.BooleanField(default=False)

    class Meta:
        ordering = ['-start_at']

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.title

    def clean(self) -> None:
        super().clean()
        if self.registration_deadline >= self.start_at:
            raise ValidationError({'registration_deadline': 'O término das inscrições deve ser antes do início do evento.'})

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.title)
            slug_candidate = base_slug
            index = 1
            while Event.objects.filter(slug=slug_candidate).exclude(pk=self.pk).exists():
                index += 1
                slug_candidate = f"{base_slug}-{index}"
            self.slug = slug_candidate
        super().save(*args, **kwargs)

    @property
    def is_registration_open(self) -> bool:
        if not self.is_published:
            return False
        now = timezone.now()
        return now <= self.registration_deadline

    def get_absolute_url(self) -> str:
        return reverse('events:detail', kwargs={'slug': self.slug})



class AthleteRegistration(TimeStampedModel):
    class PracticeDuration(models.TextChoices):
        LESS_THAN_ONE = 'lt_1', 'Menos de 1 ano'
        ONE_TO_THREE = '1_3', '1 a 3 anos'
        THREE_TO_FIVE = '3_5', '3 a 5 anos'
        MORE_THAN_FIVE = 'gt_5', 'Mais de 5 anos'

    class ExperienceLevel(models.TextChoices):
        BEGINNER = 'beginner', 'Iniciante'
        INTERMEDIATE = 'intermediate', 'Intermediário'
        ADVANCED = 'advanced', 'Avançado'

    class RuleSet(models.TextChoices):
        K1_LIGHT = 'k1_light', 'K1 Light'
        K1_RULES = 'k1_rules', 'K1 Rules'

    class Modality(models.TextChoices):
        AMATEUR = 'amateur', 'Amador'
        PROFESSIONAL = 'professional', 'Profissional'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pendente'
        CONFIRMED = 'confirmed', 'Confirmada'
        CANCELLED = 'cancelled', 'Cancelada'

    class Sex(models.TextChoices):
        MALE = 'male', 'Masculino'
        FEMALE = 'female', 'Feminino'
        OTHER = 'other', 'Outro'

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='registrations')
    academy = models.ForeignKey(Academy, on_delete=models.PROTECT, related_name='registrations')
    coach = models.ForeignKey(Coach, on_delete=models.PROTECT, related_name='registrations')
    athlete_name = models.CharField(max_length=255)
    birth_date = models.DateField()
    practice_time = models.CharField(max_length=32, choices=PracticeDuration.choices, default=PracticeDuration.LESS_THAN_ONE)
    record_wins = models.PositiveSmallIntegerField(default=0)
    record_draws = models.PositiveSmallIntegerField(default=0)
    record_losses = models.PositiveSmallIntegerField(default=0)
    weight_kg = models.DecimalField(max_digits=6, decimal_places=2, validators=[MinValueValidator(Decimal('0.00'))])
    rule_set = models.CharField(max_length=32, choices=RuleSet.choices, default=RuleSet.K1_LIGHT)
    modality = models.CharField(max_length=32, choices=Modality.choices)
    whatsapp = models.CharField(max_length=32)
    sex = models.CharField(max_length=16, choices=Sex.choices)
    experience_level = models.CharField(max_length=32, choices=ExperienceLevel.choices, default=ExperienceLevel.BEGINNER)
    cpf = models.CharField(max_length=11, blank=True, null=True)
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)

    class Meta:
        ordering = ['athlete_name']
        constraints = [
            models.UniqueConstraint(
                fields=['event', 'cpf'],
                name='unique_event_cpf',
                condition=models.Q(cpf__isnull=False),
            ),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.athlete_name} - {self.event.title}"

    def clean(self) -> None:
        super().clean()
        if self.coach_id and self.academy_id:
            coach_academy_id = Coach.objects.filter(pk=self.coach_id).values_list('academy_id', flat=True).first()
            if coach_academy_id and coach_academy_id != self.academy_id:
                raise ValidationError({'coach': 'O professor selecionado não pertence à academia escolhida.'})
        if self.event_id:
            event = getattr(self, 'event', None)
            if event is None or event.pk != self.event_id:
                event = Event.objects.filter(pk=self.event_id).first()
            if event and event.registration_deadline < timezone.now():
                raise ValidationError({'event': 'As inscrições para este evento estão encerradas.'})

    def save(self, *args, **kwargs):
        self.experience_level = self.derive_experience_level()
        super().save(*args, **kwargs)

    def derive_experience_level(self) -> str:
        total = self.total_fights
        if total < 5:
            return self.ExperienceLevel.BEGINNER
        if total < 15:
            return self.ExperienceLevel.INTERMEDIATE
        return self.ExperienceLevel.ADVANCED

    @property
    def total_fights(self) -> int:
        return self.record_wins + self.record_draws + self.record_losses
