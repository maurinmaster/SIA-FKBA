from __future__ import annotations

from datetime import timedelta
import logging
import math
from io import BytesIO
from openpyxl import Workbook
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Count, Q, Prefetch
from django.http import HttpResponse, HttpResponseForbidden, HttpResponseRedirect
from django.urls import reverse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView, ListView, CreateView, UpdateView, DeleteView

from core.models import Academy
from events.models import AthleteRegistration, Event
from matchmaking.forms import MatchmakingMetricForm
from matchmaking.models import MatchmakingMetric, MatchmakingBracket, MatchmakingEntry, MatchmakingMatch
from matchmaking.services import generate_brackets_for_event, rebuild_bracket_matches
from payments.services import (
    AsaasAPIError,
    MissingAsaasConfiguration,
    create_payment_for_registration,
    mark_registration_paid_manually,
)


logger = logging.getLogger(__name__)


class StaffOnlyMixin(LoginRequiredMixin, UserPassesTestMixin):
    login_url = 'admin:login'

    def test_func(self) -> bool:
        return bool(self.request.user and self.request.user.is_staff)

    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            return HttpResponseForbidden('Acesso restrito à equipe administrativa.')
        return super().handle_no_permission()


class DashboardView(StaffOnlyMixin, TemplateView):
    template_name = 'dashboard/index.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        agora = timezone.now()

        eventos = Event.objects.annotate(
            total_inscricoes=Count('registrations', distinct=True),
            inscricoes_confirmadas=Count(
                'registrations',
                filter=Q(registrations__status=AthleteRegistration.Status.CONFIRMED),
                distinct=True,
            ),
        ).order_by('start_at')

        eventos_publicados = eventos.filter(is_published=True)
        resumo_eventos = {
            'total': eventos_publicados.count(),
            'publicados': eventos_publicados.count(),
            'inscricoes_abertas': eventos_publicados.filter(
                registration_deadline__gte=agora,
            ).count(),
        }

        inscricoes_qs = AthleteRegistration.objects.select_related('event')
        resumo_inscricoes = {
            'total': inscricoes_qs.count(),
            'pendentes': inscricoes_qs.filter(status=AthleteRegistration.Status.PENDING).count(),
            'confirmadas': inscricoes_qs.filter(status=AthleteRegistration.Status.CONFIRMED).count(),
            'canceladas': inscricoes_qs.filter(status=AthleteRegistration.Status.CANCELLED).count(),
        }

        eventos_proximos = eventos_publicados.filter(start_at__gte=agora - timedelta(days=1))[:6]
        top_academias = (
            Academy.objects.annotate(total_inscricoes=Count('registrations'))
            .filter(total_inscricoes__gt=0)
            .order_by('-total_inscricoes')[:5]
        )
        inscricoes_recentes = (
            inscricoes_qs.select_related('academy', 'coach')
            .order_by('-created_at')[:8]
        )

        context.update(
            {
                'resumo_eventos': resumo_eventos,
                'resumo_inscricoes': resumo_inscricoes,
                'eventos_proximos': eventos_proximos,
                'top_academias': top_academias,
                'inscricoes_recentes': inscricoes_recentes,
            }
        )
        return context


class RegistrationListView(StaffOnlyMixin, ListView):
    model = AthleteRegistration
    template_name = 'dashboard/registrations.html'
    context_object_name = 'registrations'
    paginate_by = 20

    def get_queryset(self):
        queryset = (
            AthleteRegistration.objects.select_related('event', 'academy', 'coach')
            .order_by('-created_at')
        )
        return self._apply_filters(self.request, queryset)

    @staticmethod
    def _apply_filters(request, queryset):
        search = request.GET.get('busca')
        status = request.GET.get('status')
        event_slug = request.GET.get('evento')
        modality = request.GET.get('modalidade')
        if search:
            queryset = queryset.filter(
                Q(athlete_name__icontains=search)
                | Q(academy__name__icontains=search)
                | Q(coach__full_name__icontains=search)
            )
        if status:
            queryset = queryset.filter(status=status)
        if event_slug:
            queryset = queryset.filter(event__slug=event_slug)
        if modality:
            queryset = queryset.filter(modality=modality)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['eventos'] = Event.objects.filter(is_published=True).order_by('start_at')
        context['status_choices'] = AthleteRegistration.Status.choices
        context['modalidade_choices'] = AthleteRegistration.Modality.choices
        context['busca'] = self.request.GET.get('busca', '')
        context['status_atual'] = self.request.GET.get('status', '')
        context['evento_atual'] = self.request.GET.get('evento', '')
        context['modalidade_atual'] = self.request.GET.get('modalidade', '')
        context['querystring'] = self.request.GET.urlencode()
        return context





class RegistrationExportView(StaffOnlyMixin, View):
    def get(self, request, *args, **kwargs):
        queryset = RegistrationListView._apply_filters(
            request,
            AthleteRegistration.objects.select_related('event', 'academy', 'coach').order_by('-created_at'),
        )

        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = 'Inscricoes'

        headers = [
            'Criado em',
            'Evento',
            'Atleta',
            'Sexo',
            'Peso (kg)',
            'Total de lutas',
            'Academia',
            'Professor',
            'Regra',
            'Modalidade',
            'Status',
            'WhatsApp',
            'CPF',
        ]
        worksheet.append(headers)

        for registration in queryset:
            created_at = timezone.localtime(registration.created_at).strftime('%Y-%m-%d %H:%M')
            academy = registration.academy.name if registration.academy else ''
            coach = registration.coach.full_name if registration.coach else ''
            worksheet.append(
                [
                    created_at,
                    registration.event.title,
                    registration.athlete_name,
                    registration.get_sex_display(),
                    float(registration.weight_kg) if registration.weight_kg is not None else None,
                    registration.total_fights,
                    academy,
                    coach,
                    registration.get_rule_set_display(),
                    registration.get_modality_display(),
                    registration.get_status_display(),
                    registration.whatsapp,
                    registration.cpf,
                ]
            )

        for column_cells in worksheet.columns:
            max_length = 0
            column_letter = column_cells[0].column_letter
            for cell in column_cells:
                value = cell.value
                if value is None:
                    continue
                length = len(str(value))
                if length > max_length:
                    max_length = length
            worksheet.column_dimensions[column_letter].width = min(max_length + 2, 40)

        output = BytesIO()
        workbook.save(output)
        output.seek(0)

        filename = f"inscricoes-{timezone.now():%Y%m%d-%H%M}.xlsx"
        response = HttpResponse(
            output.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response
class RegistrationPaymentActionView(StaffOnlyMixin, View):
    def post(self, request, pk: int):
        registration = get_object_or_404(
            AthleteRegistration.objects.select_related('event', 'payment', 'academy', 'coach'),
            pk=pk,
        )
        action = request.POST.get('action')
        next_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or reverse('core:registrations')

        if action == 'resend':
            try:
                payment = create_payment_for_registration(registration)
            except MissingAsaasConfiguration as exc:
                messages.error(request, str(exc))
            except AsaasAPIError as exc:
                logger.exception('Falha ao gerar cobranca Asaas para inscricao %s: %s', registration.pk, exc)
                messages.error(
                    request,
                    'Nao foi possivel gerar uma nova cobranca agora. Tente novamente em instantes.',
                )
            else:
                if registration.status != registration.Status.PENDING:
                    registration.status = registration.Status.PENDING
                    registration.save(update_fields=['status', 'updated_at'])
                link = payment.invoice_url or payment.bank_slip_url
                if link:
                    messages.success(
                        request,
                        f'Novo link de pagamento gerado. Copie e encaminhe ao atleta: {link}',
                    )
                else:
                    messages.success(
                        request,
                        'Novo pagamento criado. Consulte os detalhes atualizados da inscricao.',
                    )
        elif action == 'manual-confirm':
            mark_registration_paid_manually(registration)
            messages.success(
                request,
                'Pagamento marcado como confirmado. A inscricao foi atualizada.',
            )
        else:
            messages.error(request, 'Acao de pagamento invalida.')

        return redirect(next_url)


class MatchmakingMetricListView(StaffOnlyMixin, ListView):
    model = MatchmakingMetric
    template_name = 'dashboard/matchmaking/metric_list.html'
    context_object_name = 'metrics'
    paginate_by = 20

    def get_queryset(self):
        queryset = MatchmakingMetric.objects.order_by('name')
        search = self.request.GET.get('busca')
        if search:
            queryset = queryset.filter(name__icontains=search)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['busca'] = self.request.GET.get('busca', '')
        return context


class MatchmakingMetricCreateView(StaffOnlyMixin, CreateView):
    model = MatchmakingMetric
    form_class = MatchmakingMetricForm
    template_name = 'dashboard/matchmaking/metric_form.html'

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, 'Métrica de casamento criada com sucesso.')
        return response

    def get_success_url(self):
        return reverse('core:matchmaking-metrics')


class MatchmakingMetricUpdateView(StaffOnlyMixin, UpdateView):
    model = MatchmakingMetric
    form_class = MatchmakingMetricForm
    template_name = 'dashboard/matchmaking/metric_form.html'

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, 'Métrica de casamento atualizada com sucesso.')
        return response

    def get_success_url(self):
        return reverse('core:matchmaking-metrics')



class MatchmakingEventView(StaffOnlyMixin, TemplateView):
    template_name = 'dashboard/matchmaking/event_brackets.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        event = get_object_or_404(Event, slug=kwargs['slug'])
        match_prefetch = Prefetch(
            'matches',
            queryset=MatchmakingMatch.objects.select_related(
                'blue_entry__registration__academy',
                'red_entry__registration__academy',
                'winner_entry__registration',
                'blue_source_match',
                'red_source_match',
            ).order_by('round_number', 'position'),
            to_attr='export_matches',
        )
        brackets = list(
            event.matchmaking_brackets
            .annotate(entry_total=Count('entries', distinct=True), match_total=Count('matches', distinct=True))
            .select_related('metric', 'generated_by')
            .prefetch_related(match_prefetch)
            .order_by('rule_set', 'experience_label', 'sex', 'age_group', 'weight_label', 'bracket_index')
        )
        confirmed_qs = event.registrations.filter(status=AthleteRegistration.Status.CONFIRMED)
        assigned_ids = confirmed_qs.filter(matchmaking_entries__bracket__event=event).values_list('pk', flat=True)
        unassigned = confirmed_qs.exclude(pk__in=assigned_ids).select_related('academy', 'coach').order_by('athlete_name')
        context.update(
            {
                'event': event,
                'metrics': MatchmakingMetric.objects.order_by('name'),
                'brackets': brackets,
                'confirmed_count': confirmed_qs.count(),
                'unassigned_registrations': unassigned,
                'unassigned_count': unassigned.count(),
            }
        )
        return context


class MatchmakingGenerateView(StaffOnlyMixin, View):
    def post(self, request, slug):
        if request.POST.get('export_action') == 'event':
            event = get_object_or_404(Event, slug=slug)
            return MatchmakingBracketExportView()._export_all_brackets(event)

        event = get_object_or_404(Event, slug=slug)
        metric_id = request.POST.get('metric')
        if not metric_id:
            messages.error(request, 'Selecione uma metrica para gerar as chaves.')
            return redirect('core:matchmaking-event', slug=event.slug)
        metric = get_object_or_404(MatchmakingMetric, pk=metric_id)
        replace = request.POST.get('replace', 'on') == 'on'
        result = generate_brackets_for_event(
            event=event,
            metric=metric,
            user=request.user,
            replace_existing=replace,
        )
        if result['brackets_created']:
            messages.success(
                request,
                f"{result['brackets_created']} chave(s) geradas ({result['matches_created']} luta(s)).",
            )
        else:
            messages.info(
                request,
                'Nenhuma chave criada. Verifique se existem atletas confirmados para esta combinacao.',
            )
        if result['replaced']:
            messages.info(request, f"{result['replaced']} chave(s) anteriores foram substituidas.")
        unmatched = result.get('unmatched', [])
        if unmatched:
            nomes = ', '.join(item['athlete'] for item in unmatched[:5])
            messages.warning(
                request,
                f"{len(unmatched)} inscricao(oes) nao entraram em nenhuma chave: {nomes}.",
            )
        return redirect('core:matchmaking-event', slug=event.slug)


class MatchmakingBracketDetailView(StaffOnlyMixin, TemplateView):
    template_name = 'dashboard/matchmaking/bracket_detail.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        bracket = get_object_or_404(
            MatchmakingBracket.objects.select_related('event', 'metric', 'generated_by'),
            pk=kwargs['pk'],
        )
        entries = bracket.entries.select_related('registration').order_by('slot')
        matches_queryset = (
            bracket.matches
            .select_related('blue_entry__registration', 'red_entry__registration', 'blue_source_match', 'red_source_match')
            .order_by('round_number', 'position')
        )
        matches = list(matches_queryset)
        rounds: list[dict] = []
        for match in matches:
            if not rounds or match.round_number != rounds[-1]['number']:
                rounds.append({
                    'number': match.round_number,
                    'label': match.round_label,
                    'items': [],
                })
            rounds[-1]['items'].append(match)

        match_height = 140
        gap = 32
        unit = match_height + gap

        round_numbers = [round_data['number'] for round_data in rounds]
        round_matches_map = {round_data['number']: round_data['items'] for round_data in rounds}

        layout_rounds: list[dict] = []
        max_bottom = match_height

        for round_index, round_data in enumerate(rounds):
            span_multiplier = 2 ** round_index
            offset = ((span_multiplier - 1) / 2) * unit
            connector_length = unit * span_multiplier / 2 if round_index < len(rounds) - 1 else 0.0

            matches_layout: list[dict] = []
            for match_index, match in enumerate(round_data['items']):
                top = match_index * unit * span_multiplier + offset
                bottom = top + match_height
                max_bottom = max(max_bottom, bottom + connector_length)
                matches_layout.append({
                    'object': match,
                    'top': top,
                    'connector_length': connector_length,
                    'connector_direction': 'link' if connector_length else 'none',
                })

            layout_rounds.append({
                'number': round_data['number'],
                'label': round_data['label'],
                'matches': matches_layout,
            })

        total_height = max_bottom + gap

        context.update(
            {
                'bracket': bracket,
                'entries': entries,
                'round_layout': layout_rounds,
                'matches': matches,
                'bracket_dimensions': {
                    'match_height': match_height,
                    'gap': gap,
                    'total_height': total_height,
                },
            }
        )
        return context



class MatchmakingBracketExportView(StaffOnlyMixin, View):
    HEADER_HEIGHT = 78
    ROSTER_ROW_HEIGHT = 28
    BASE_MATCH_HEIGHT = 58
    BASE_GAP = 32
    BASE_COLUMN_WIDTH = 160
    BASE_COLUMN_GAP = 80

    def post(self, request, pk: int):
        bracket = get_object_or_404(
            MatchmakingBracket.objects.select_related('event', 'metric'),
            pk=pk,
        )
        matches_queryset = (
            bracket.matches
            .select_related(
                'blue_entry__registration',
                'red_entry__registration',
                'winner_entry__registration',
                'blue_source_match',
                'red_source_match',
            )
            .order_by('round_number', 'position')
        )

        scope = request.POST.get('export_scope', 'all')
        if scope == 'selected':
            match_ids: list[int] = []
            for raw in request.POST.getlist('match_ids'):
                try:
                    match_ids.append(int(raw))
                except (TypeError, ValueError):
                    continue
            matches = list(matches_queryset.filter(pk__in=match_ids)) if match_ids else []
            if not matches:
                messages.error(request, 'Selecione ao menos uma luta para exportar.')
                return redirect('core:matchmaking-bracket-detail', pk=pk)
        else:
            matches = list(matches_queryset)
            if not matches:
                messages.error(request, 'Nao existem lutas nesta chave para exportacao.')
                return redirect('core:matchmaking-bracket-detail', pk=pk)

        return self._build_pdf_response(bracket, matches)

    def _build_pdf_response(self, bracket: MatchmakingBracket, matches: list[MatchmakingMatch]) -> HttpResponse:
        buffer = BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=A4)
        width, height = A4
        margin = 18 * mm

        entries = list(
            bracket.entries.select_related('registration__academy', 'registration__coach').order_by('slot')
        )
        matches = matches or list(
            bracket.matches
            .select_related(
                'blue_entry__registration__academy',
                'red_entry__registration__academy',
                'winner_entry__registration',
                'blue_source_match',
                'red_source_match',
            )
            .order_by('round_number', 'position')
        )
        layout_data = self._compute_bracket_layout(bracket)
        highlight_ids = {match.pk for match in matches}

        self._draw_export_page(
            pdf=pdf,
            bracket=bracket,
            entries=entries,
            layout_data=layout_data,
            highlight_ids=highlight_ids,
            matches=matches,
            width=width,
            height=height,
            margin=margin,
        )
        pdf.showPage()
        pdf.save()
        buffer.seek(0)
        filename = f'chave-{bracket.pk}-lutas.pdf'
        response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename={filename}'
        return response

    def _draw_export_page(
        self,
        pdf: canvas.Canvas,
        bracket: MatchmakingBracket,
        entries: list,
        layout_data: dict,
        highlight_ids: set[int],
        matches: list[MatchmakingMatch],
        width: float,
        height: float,
        margin: float,
    ) -> None:
        header_top = height - margin
        header_bottom = header_top - self.HEADER_HEIGHT

        pdf.setFillColorRGB(0.12, 0.28, 0.52)
        pdf.roundRect(margin, header_bottom, width - 2 * margin, self.HEADER_HEIGHT, 10, stroke=0, fill=1)

        pdf.setFillColorRGB(1, 1, 1)
        title_text = pdf.beginText(margin + 16, header_top - 24)
        title_text.setFont('Helvetica-Bold', 17)
        title_text.setWordSpace(1.4)
        title_text.textLine(bracket.event.title)
        pdf.drawText(title_text)

        pdf.setFont('Helvetica', 11)
        pdf.drawRightString(
            width - margin - 16,
            header_top - 44,
            f"{len(matches)} luta(s) selecionada(s)"
        )

        chip_texts = [
            bracket.get_rule_set_display(),
            f"{bracket.age_group.title()} · {bracket.weight_label}",
            bracket.experience_label.title(),
            bracket.get_sex_display(),
        ]
        chip_x = margin + 16
        chip_y = header_bottom + 20
        pdf.setFont('Helvetica-Bold', 9)
        for text in chip_texts:
            if not text:
                continue
            text_width = pdf.stringWidth(text, 'Helvetica-Bold', 9)
            chip_width = text_width + 28
            pdf.setFillColorRGB(1, 1, 1)
            pdf.roundRect(chip_x, chip_y - 6, chip_width, 18, 6, stroke=0, fill=1)
            pdf.setFillColorRGB(0.12, 0.28, 0.52)
            text_x = chip_x + (chip_width - text_width) / 2
            pdf.drawString(text_x, chip_y + 5, text)
            chip_x += chip_width + 8

        roster_rows = max(1, math.ceil(len(entries) / 2))
        roster_height = roster_rows * self.ROSTER_ROW_HEIGHT + 36
        roster_top = header_bottom - 26
        roster_bottom = roster_top - roster_height

        pdf.setFillColorRGB(0.96, 0.98, 1)
        pdf.roundRect(margin, roster_bottom, width - 2 * margin, roster_height, 10, stroke=0, fill=1)

        pdf.setFillColorRGB(0.12, 0.16, 0.22)
        pdf.setFont('Helvetica-Bold', 12)
        pdf.drawString(margin + 16, roster_top - 20, 'Atletas nesta chave')

        pdf.setFont('Helvetica', 9)
        col_width = (width - 2 * margin - 32) / 2
        start_y = roster_top - 40
        for idx, entry in enumerate(entries):
            reg = entry.registration
            academy = reg.academy.name if reg.academy else 'Academia nao informada'
            coach_name = reg.coach.full_name if reg.coach else 'Professor nao informado'
            col = idx % 2
            row = idx // 2
            row_y = start_y - row * self.ROSTER_ROW_HEIGHT
            base_x = margin + 16 + col * (col_width + 16)
            pdf.setFillColorRGB(0.12, 0.16, 0.22)
            main_text = f"{entry.slot}. {reg.athlete_name}"
            pdf.drawString(base_x, row_y, self._truncate_text(pdf, main_text, col_width, 'Helvetica-Bold', 9))
            pdf.setFillColorRGB(0.35, 0.4, 0.48)
            detail_text = (
                f"{academy} · Peso {reg.weight_kg} kg · {reg.total_fights} lutas · {coach_name}"
            )
            pdf.drawString(base_x, row_y - 11, self._truncate_text(pdf, detail_text, col_width, 'Helvetica', 8))

        bracket_top = roster_bottom - 40
        bracket_height = max(margin + 140, bracket_top - margin - 120)
        bracket_width = width - 2 * margin

        self._draw_bracket_grid(
            pdf=pdf,
            layout_data=layout_data,
            highlight_ids=highlight_ids,
            left=margin,
            top=bracket_top,
            width=bracket_width,
            height=bracket_height,
        )

        pdf.setFillColorRGB(0.55, 0.58, 0.62)
        pdf.setFont('Helvetica-Oblique', 9)
        pdf.drawRightString(width - margin, margin - 6, 'Gerado automaticamente pelo painel FKBA')

    def _compute_bracket_layout(self, bracket: MatchmakingBracket) -> dict:
        matches = list(
            bracket.matches
            .select_related(
                'blue_entry__registration',
                'red_entry__registration',
                'blue_source_match',
                'red_source_match',
            )
            .order_by('round_number', 'position')
        )
        rounds: list[dict] = []
        for match in matches:
            if not rounds or match.round_number != rounds[-1]['number']:
                rounds.append({'number': match.round_number, 'label': match.round_label, 'items': []})
            rounds[-1]['items'].append(match)

        layout_rounds: list[dict] = []
        match_height = self.BASE_MATCH_HEIGHT
        gap = self.BASE_GAP
        unit = match_height + gap
        max_bottom = match_height

        for round_index, round_data in enumerate(rounds):
            span_multiplier = 2 ** round_index
            offset = ((span_multiplier - 1) / 2) * unit
            column_matches: list[dict] = []
            for match_index, match in enumerate(round_data['items']):
                top = match_index * unit * span_multiplier + offset
                bottom = top + match_height
                max_bottom = max(max_bottom, bottom)
                column_matches.append({'match': match, 'top': top})
            layout_rounds.append({'label': round_data['label'], 'matches': column_matches})

        total_height = max_bottom + gap
        return {
            'rounds': layout_rounds,
            'total_height': total_height,
        }

    def _draw_bracket_grid(
        self,
        pdf: canvas.Canvas,
        layout_data: dict,
        highlight_ids: set[int],
        left: float,
        top: float,
        width: float,
        height: float,
    ) -> None:
        rounds = layout_data.get('rounds', [])
        if not rounds:
            pdf.setFillColorRGB(0.45, 0.48, 0.52)
            pdf.setFont('Helvetica', 10)
            pdf.drawString(left, top - 20, 'Nenhuma luta cadastrada para esta chave.')
            return

        total_height = layout_data['total_height']
        base_total_width = (
            len(rounds) * self.BASE_COLUMN_WIDTH + max(len(rounds) - 1, 0) * self.BASE_COLUMN_GAP
        )
        scale_y = min(1.0, height / total_height) if total_height else 1.0
        scale_x = min(1.0, width / base_total_width) if base_total_width else 1.0
        scale = min(scale_x, scale_y)

        col_width = self.BASE_COLUMN_WIDTH * scale
        col_gap = self.BASE_COLUMN_GAP * scale
        match_height = self.BASE_MATCH_HEIGHT * scale

        usable_width = len(rounds) * col_width + max(len(rounds) - 1, 0) * col_gap
        offset_x = left + (width - usable_width) / 2

        positions: dict[int, dict[str, float]] = {}

        pdf.setFont('Helvetica-Bold', max(9, 11 * scale))
        pdf.setFillColorRGB(0.18, 0.2, 0.24)

        for round_index, round_data in enumerate(rounds):
            column_x = offset_x + round_index * (col_width + col_gap)
            pdf.drawString(column_x, top + 12, round_data['label'].upper())
            for item in round_data['matches']:
                match = item['match']
                top_offset = item['top'] * scale
                box_y = top - top_offset - match_height
                self._draw_bracket_box(
                    pdf=pdf,
                    match=match,
                    x=column_x,
                    y=box_y,
                    width=col_width,
                    height=match_height,
                    highlight=match.pk in highlight_ids,
                )
                positions[match.pk] = {
                    'match': match,
                    'x': column_x,
                    'y': box_y,
                    'center_y': box_y + match_height / 2,
                    'right_x': column_x + col_width,
                    'left_x': column_x,
                    'width': col_width,
                }

        pdf.setStrokeColorRGB(0.75, 0.79, 0.84)
        pdf.setLineWidth(1.0 * scale)
        pdf.setLineCap(1)
        for data in positions.values():
            obj = data['match']
            target_x = data['left_x']
            target_y = data['center_y']
            for source in (obj.blue_source_match, obj.red_source_match):
                if source and source.pk in positions:
                    start = positions[source.pk]
                    start_x = start['right_x']
                    start_y = start['center_y']
                    mid_x = (start_x + target_x) / 2
                    pdf.line(start_x, start_y, mid_x, start_y)
                    pdf.line(mid_x, start_y, mid_x, target_y)
                    pdf.line(mid_x, target_y, target_x, target_y)

    def _draw_bracket_box(
        self,
        pdf: canvas.Canvas,
        match: MatchmakingMatch,
        x: float,
        y: float,
        width: float,
        height: float,
        highlight: bool,
    ) -> None:
        corner = 10
        if highlight:
            fill_color = (0.88, 0.93, 1.0)
            stroke_color = (0.18, 0.38, 0.78)
        else:
            fill_color = (1, 1, 1)
            stroke_color = (0.82, 0.86, 0.92)

        pdf.setFillColorRGB(*fill_color)
        pdf.setStrokeColorRGB(*stroke_color)
        pdf.setLineWidth(1.4 if highlight else 1.0)
        pdf.roundRect(x, y, width, height, corner, fill=1, stroke=1)

        pdf.setStrokeColorRGB(0.88, 0.9, 0.94)
        pdf.setLineWidth(0.7)
        pdf.line(x, y + height / 2, x + width, y + height / 2)

        self._draw_slot(
            pdf=pdf,
            x=x,
            y=y + height / 2,
            width=width,
            height=height / 2,
            name=match.blue_entry.registration.athlete_name if match.blue_entry else '',
            academy=match.blue_entry.registration.academy.name if match.blue_entry and match.blue_entry.registration.academy else '',
        )
        self._draw_slot(
            pdf=pdf,
            x=x,
            y=y,
            width=width,
            height=height / 2,
            name=match.red_entry.registration.athlete_name if match.red_entry else '',
            academy=match.red_entry.registration.academy.name if match.red_entry and match.red_entry.registration.academy else '',
        )

    def _draw_slot(
        self,
        pdf: canvas.Canvas,
        x: float,
        y: float,
        width: float,
        height: float,
        name: str,
        academy: str,
    ) -> None:
        padding_x = 14
        padding_top = 14
        main_font = 9 if width >= 130 else 8
        detail_font = 7 if width >= 130 else 6
        if name:
            pdf.setFont('Helvetica-Bold', main_font)
            pdf.setFillColorRGB(0.16, 0.18, 0.22)
            pdf.drawString(
                x + padding_x,
                y + height - padding_top,
                self._truncate_text(pdf, name, width - 2 * padding_x, 'Helvetica-Bold', main_font),
            )
        if academy:
            pdf.setFont('Helvetica', detail_font)
            pdf.setFillColorRGB(0.42, 0.45, 0.5)
            text_y = y + height - padding_top - (11 if name else 0)
            pdf.drawString(
                x + padding_x,
                text_y,
                self._truncate_text(pdf, academy, width - 2 * padding_x, 'Helvetica', detail_font),
            )
    def _truncate_text(self, pdf: canvas.Canvas, text: str, max_width: float, font: str, size: float) -> str:
        if pdf.stringWidth(text, font, size) <= max_width:
            return text
        ellipsis = pdf.stringWidth('...', font, size)
        available = max_width - ellipsis
        if available <= 0:
            return '...'
        result = ''
        for char in text:
            if pdf.stringWidth(result + char, font, size) > available:
                break
            result += char
        return result + '...'


    def _export_all_brackets(self, event: Event) -> HttpResponse:
        buffer = BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=A4)
        width, height = A4
        margin = 18 * mm

        match_prefetch = Prefetch(
            'matches',
            queryset=MatchmakingMatch.objects.select_related(
                'blue_entry__registration__academy',
                'red_entry__registration__academy',
                'winner_entry__registration',
                'blue_source_match',
                'red_source_match',
            ).order_by('round_number', 'position'),
            to_attr='export_matches',
        )
        entry_prefetch = Prefetch(
            'entries',
            queryset=MatchmakingEntry.objects.select_related('registration__academy', 'registration__coach').order_by('slot'),
            to_attr='export_entries',
        )

        brackets = list(
            event.matchmaking_brackets
            .select_related('metric')
            .prefetch_related(match_prefetch, entry_prefetch)
            .order_by('rule_set', 'experience_label', 'sex', 'age_group', 'weight_label', 'bracket_index')
        )

        for bracket in brackets:
            entries = list(getattr(bracket, 'export_entries', []))
            if not entries:
                entries = list(
                    bracket.entries.select_related('registration__academy', 'registration__coach').order_by('slot')
                )
            matches = list(getattr(bracket, 'export_matches', []))
            if not matches:
                matches = list(
                    bracket.matches
                    .select_related(
                        'blue_entry__registration__academy',
                        'red_entry__registration__academy',
                        'winner_entry__registration',
                        'blue_source_match',
                        'red_source_match',
                    )
                    .order_by('round_number', 'position')
                )
            layout_data = self._compute_bracket_layout(bracket)
            highlight_ids: set[int] = {match.pk for match in matches}
            self._draw_export_page(
                pdf=pdf,
                bracket=bracket,
                entries=entries,
                layout_data=layout_data,
                highlight_ids=highlight_ids,
                matches=matches,
                width=width,
                height=height,
                margin=margin,
            )
            pdf.showPage()

        if not brackets:
            pdf.setFont('Helvetica-Bold', 16)
            pdf.drawString(margin, height - margin - 40, f'{event.title} - Nenhuma chave gerada at� o momento.')
            pdf.showPage()

        pdf.save()
        buffer.seek(0)
        filename = f'chaves-{event.pk}.pdf'
        response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename={filename}'
        return response

class MatchmakingBracketManualEditView(StaffOnlyMixin, TemplateView):
    template_name = 'dashboard/matchmaking/bracket_manual_edit.html'

    def dispatch(self, request, *args, **kwargs):
        self.bracket = get_object_or_404(MatchmakingBracket, pk=kwargs['pk'])
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        entries = self.bracket.entries.select_related('registration').order_by('slot')
        context.update(
            {
                'bracket': self.bracket,
                'entries': entries,
                'order_initial': ','.join(str(entry.pk) for entry in entries),
            }
        )
        return context

    def post(self, request, *args, **kwargs):
        order_raw = (request.POST.get('order') or '').strip()
        entries = list(self.bracket.entries.select_related('registration').order_by('slot'))
        entry_map = {str(entry.pk): entry for entry in entries}
        order_ids = [item for item in order_raw.split(',') if item]

        errors: list[str] = []
        if not order_ids:
            errors.append('Informe a nova ordem dos atletas.')
        elif len(order_ids) != len(entries):
            errors.append('A ordem enviada no confere com a quantidade de atletas.')
        elif set(order_ids) != set(entry_map.keys()):
            errors.append('Identificamos atletas desconhecidos na ordem informada.')

        if errors:
            for error in errors:
                messages.error(request, error)
            context = self.get_context_data()
            context['order_initial'] = order_raw or context['order_initial']
            return self.render_to_response(context)

        updated_entries: list[tuple[MatchmakingEntry, int]] = []
        for index, entry_id in enumerate(order_ids, start=1):
            entry = entry_map[entry_id]
            if entry.slot != index:
                updated_entries.append((entry, index))
        if updated_entries:
            temp_entries = []
            for entry, index in updated_entries:
                entry.slot = index + len(entries)
                temp_entries.append(entry)
            MatchmakingEntry.objects.bulk_update(temp_entries, ['slot'])
            final_entries = []
            for entry, index in updated_entries:
                entry.slot = index
                final_entries.append(entry)
            MatchmakingEntry.objects.bulk_update(final_entries, ['slot'])
        self.bracket.is_manual = True
        self.bracket.save(update_fields=['is_manual', 'updated_at'])
        rebuild_bracket_matches(self.bracket)
        messages.success(request, 'Chave atualizada com sucesso.')
        return redirect('core:matchmaking-bracket-detail', pk=self.bracket.pk)

class MatchmakingMetricDeleteView(StaffOnlyMixin, DeleteView):
    model = MatchmakingMetric
    template_name = 'dashboard/matchmaking/metric_confirm_delete.html'

    def delete(self, request, *args, **kwargs):
        messages.success(request, 'Métrica removida com sucesso.')
        return super().delete(request, *args, **kwargs)

    def get_success_url(self):
        return reverse('core:matchmaking-metrics')


class EventListView(StaffOnlyMixin, ListView):
    model = Event
    template_name = 'dashboard/events.html'
    context_object_name = 'events'
    paginate_by = 15

    def get_queryset(self):
        queryset = Event.objects.annotate(
            total_inscricoes=Count('registrations'),
            inscricoes_confirmadas=Count(
                'registrations',
                filter=Q(registrations__status=AthleteRegistration.Status.CONFIRMED),
            ),
        ).order_by('-start_at')
        search = self.request.GET.get('busca')
        status = self.request.GET.get('status')
        if search:
            queryset = queryset.filter(
                Q(title__icontains=search)
                | Q(location__icontains=search)
            )
        if status == 'publicados':
            queryset = queryset.filter(is_published=True)
        elif status == 'rascunhos':
            queryset = queryset.filter(is_published=False)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['busca'] = self.request.GET.get('busca', '')
        context['status_atual'] = self.request.GET.get('status', '')
        return context




