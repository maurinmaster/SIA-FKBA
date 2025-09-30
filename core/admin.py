from django.contrib import admin

from core.models import Academy, Coach


@admin.register(Academy)
class AcademyAdmin(admin.ModelAdmin):
    list_display = ('name', 'city', 'state', 'federation_code', 'created_at')
    search_fields = ('name', 'city')
    list_filter = ('state',)


@admin.register(Coach)
class CoachAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'academy', 'whatsapp', 'email', 'created_at')
    search_fields = ('full_name', 'academy__name')
    autocomplete_fields = ('academy', 'user')
