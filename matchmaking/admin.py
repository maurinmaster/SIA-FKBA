from django.contrib import admin

from matchmaking.models import MatchmakingMetric


@admin.register(MatchmakingMetric)
class MatchmakingMetricAdmin(admin.ModelAdmin):
    list_display = ('name', 'max_fights_per_athlete', 'created_at', 'updated_at')
    search_fields = ('name',)
    readonly_fields = ('created_at', 'updated_at')
