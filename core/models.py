from django.conf import settings
from django.db import models


class TimeStampedModel(models.Model):
    """Abstract base model that stores creation and update timestamps."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Academy(TimeStampedModel):
    name = models.CharField(max_length=255)
    city = models.CharField(max_length=128)
    state = models.CharField(max_length=64, blank=True)
    federation_code = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ['name']
        unique_together = ('name', 'city', 'state')
        verbose_name_plural = 'academies'

    def __str__(self) -> str:
        location = f"{self.city}/{self.state}" if self.state else self.city
        return f"{self.name} - {location}" if location else self.name


class Coach(TimeStampedModel):
    full_name = models.CharField(max_length=255)
    whatsapp = models.CharField(max_length=32, blank=True)
    email = models.EmailField(blank=True)
    academy = models.ForeignKey(Academy, on_delete=models.PROTECT, related_name='coaches')
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='coach_profile',
    )

    class Meta:
        ordering = ['full_name']
        unique_together = ('full_name', 'academy')

    def __str__(self) -> str:
        return self.full_name
