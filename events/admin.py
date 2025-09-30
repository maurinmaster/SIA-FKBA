from django.contrib import admin
from django.utils import timezone

from events.models import AthleteRegistration, Event


class AthleteRegistrationInline(admin.TabularInline):
    model = AthleteRegistration
    extra = 0
    fields = (
        'athlete_name',
        'academy',
        'coach',
        'weight_kg',
        'rule_set',
        'modality',
        'status',
        'created_at',
    )
    readonly_fields = ('created_at',)


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = (
        'title',
        'start_at',
        'registration_deadline',
        'registration_fee',
        'is_published',
        'is_registration_open',
    )
    list_filter = ('is_published', 'start_at')
    search_fields = ('title', 'location')
    prepopulated_fields = {'slug': ('title',)}
    inlines = [AthleteRegistrationInline]

    @admin.display(boolean=True)
    def is_registration_open(self, obj: Event) -> bool:
        return obj.is_published and timezone.now() <= obj.registration_deadline


@admin.register(AthleteRegistration)
class AthleteRegistrationAdmin(admin.ModelAdmin):
    list_display = (
        'athlete_name',
        'event',
        'academy',
        'coach',
        'rule_set',
        'modality',
        'experience_level',
        'status',
        'created_at',
    )
    list_filter = ('status', 'rule_set', 'modality', 'experience_level', 'sex', 'event')
    search_fields = ('athlete_name', 'academy__name', 'coach__full_name')
    autocomplete_fields = ('event', 'academy', 'coach')
    readonly_fields = ('created_at', 'updated_at', 'total_fights')
