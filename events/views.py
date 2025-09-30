from __future__ import annotations

import logging
from decimal import Decimal

from django import forms
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.forms import formset_factory
from django.urls import reverse, reverse_lazy
from django.db.models import Prefetch
from django.views.generic import CreateView, DetailView, FormView, ListView, UpdateView
from django.db import transaction

from events.forms import (
    AthleteRegistrationForm,
    BulkAcademyForm,
    BulkAthleteRegistrationForm,
    AthleteRegistrationLookupForm,
    EventForm,
)
from payments.services import AsaasAPIError, MissingAsaasConfiguration, create_payment_for_registration
from matchmaking.models import MatchmakingEntry
from events.models import AthleteRegistration, Event


logger = logging.getLogger(__name__)


class EventListView(ListView):
    queryset = Event.objects.filter(is_published=True)
    template_name = 'events/event_list.html'
    context_object_name = 'events'
    paginate_by = 10

    def get_queryset(self):
        return super().get_queryset().order_by('start_at')

class AthleteRegistrationLookupView(FormView):
    template_name = 'events/registration_lookup.html'
    form_class = AthleteRegistrationLookupForm

    def get(self, request, *args, **kwargs):
        form = self.get_form()
        return self.render_to_response(self.get_context_data(form=form, registrations=None))

    def post(self, request, *args, **kwargs):
        form = self.get_form()
        registrations = None
        if form.is_valid():
            cpf = form.cleaned_data['cpf']
            birth_date = form.cleaned_data['birth_date']
            registrations = list(self._get_registrations(cpf, birth_date))
            action = request.POST.get('action')
            if action == 'send-payment':
                registration = self._find_registration(registrations, request.POST.get('registration_id'))
                if registration:
                    self._handle_payment(request, registration)
                    registrations = list(self._get_registrations(cpf, birth_date))
            if not registrations:
                messages.info(request, 'Nao encontramos inscricoes para os dados informados.')
        return self.render_to_response(self.get_context_data(form=form, registrations=registrations))

    def _get_registrations(self, cpf: str, birth_date):
        entry_prefetch = Prefetch(
            'matchmaking_entries',
            queryset=MatchmakingEntry.objects.select_related('bracket').order_by('slot'),
        )
        return (
            AthleteRegistration.objects.select_related('event', 'payment', 'academy', 'coach')
            .prefetch_related(entry_prefetch)
            .filter(cpf=cpf, birth_date=birth_date)
            .order_by('-created_at')
        )

    @staticmethod
    def _find_registration(registrations, registration_id):
        try:
            target = int(registration_id or 0)
        except (TypeError, ValueError):
            return None
        for registration in registrations:
            if registration.pk == target:
                return registration
        return None

    def _handle_payment(self, request, registration: AthleteRegistration):
        if registration.event.is_free:
            if registration.status != registration.Status.CONFIRMED:
                registration.status = registration.Status.CONFIRMED
                registration.save(update_fields=['status', 'updated_at'])
            messages.info(request, 'Evento gratuito: nao ha link de pagamento. Inscricao confirmada.')
            return
        if registration.status == registration.Status.CONFIRMED:
            messages.info(request, 'Esta inscricao ja esta confirmada. Nenhuma cobranca adicional foi gerada.')
            return
        try:
            payment = create_payment_for_registration(registration)
        except MissingAsaasConfiguration as exc:
            messages.error(request, str(exc))
            return
        except AsaasAPIError as exc:
            logger.exception('Falha ao criar cobranca Asaas: %s', exc)
            messages.error(request, 'Nao foi possivel gerar o pagamento no momento. Tente novamente em instantes.')
            return
        else:
            link = payment.invoice_url or payment.bank_slip_url
            if link:
                messages.success(request, 'Link de pagamento atualizado com sucesso.')
            else:
                messages.success(request, 'Cobranca gerada. Consulte o painel para detalhes do pagamento.')





class EventDetailView(DetailView):
    model = Event
    template_name = 'events/event_detail.html'
    context_object_name = 'event'
    slug_field = 'slug'
    slug_url_kwarg = 'slug'

    def get_queryset(self):
        return Event.objects.filter(is_published=True)


class EventRegistrationView(FormView):
    form_class = AthleteRegistrationForm
    template_name = 'events/registration_form.html'

    def dispatch(self, request, *args, **kwargs):
        self.event = get_object_or_404(Event, slug=kwargs['slug'], is_published=True)
        if not self.event.is_registration_open:
            messages.error(request, 'As inscrições para este evento estão encerradas.')
            return HttpResponseRedirect(self.event.get_absolute_url())
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['event'] = self.event
        initial = kwargs.setdefault('initial', {})
        initial['event'] = self.event
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['event'] = self.event
        return context

    def form_valid(self, form: AthleteRegistrationForm):
        try:
            with transaction.atomic():
                registration = form.save(commit=False)
                registration.event = self.event
                if self.event.is_free:
                    registration.status = registration.Status.CONFIRMED
                    registration.save()
                    payment = None
                else:
                    registration.status = registration.Status.PENDING
                    registration.save()
                    payment = create_payment_for_registration(registration)
        except MissingAsaasConfiguration as exc:
            messages.error(self.request, str(exc))
            form.add_error(None, str(exc))
            return self.form_invalid(form)
        except AsaasAPIError as exc:
            logger.exception('Falha ao criar cobranca Asaas: %s', exc)
            error_message = 'Nao foi possivel gerar o pagamento no momento. Tente novamente em instantes.'
            messages.error(self.request, error_message)
            form.add_error(None, error_message)
            return self.form_invalid(form)
        self.request.session['recent_registration_id'] = registration.pk
        if self.event.is_free:
            messages.success(self.request, 'Inscricao confirmada! Evento gratuito, nao ha cobranca pendente.')
        else:
            messages.success(self.request, 'Inscricao criada! Realize o pagamento para confirmar sua vaga.')
        return HttpResponseRedirect(reverse('events:registration_success', kwargs={'slug': self.event.slug}))


    def form_invalid(self, form):
        messages.error(self.request, 'Por favor corrija os erros abaixo e tente novamente.')
        return super().form_invalid(form)


class EventBulkRegistrationView(FormView):
    template_name = 'events/registration_bulk_form.html'
    form_class = BulkAcademyForm
    formset_class = formset_factory(BulkAthleteRegistrationForm, extra=1, can_delete=True, validate_min=False)

    def dispatch(self, request, *args, **kwargs):
        self.event = get_object_or_404(Event, slug=kwargs['slug'], is_published=True)
        if not self.event.is_registration_open:
            messages.error(request, 'As inscricoes para este evento estao encerradas.')
            return HttpResponseRedirect(self.event.get_absolute_url())
        return super().dispatch(request, *args, **kwargs)

    def get_success_url(self):
        return reverse('events:registration_bulk_success', kwargs={'slug': self.event.slug})

    def get(self, request, *args, **kwargs):
        form = self.get_form()
        formset = self._build_formset(shared=self._shared_from_form(form))
        return self.render_to_response(self.get_context_data(form=form, formset=formset, event=self.event))

    def post(self, request, *args, **kwargs):
        form = self.get_form()
        shared_initial = self._shared_from_form(form)
        formset = self._build_formset(data=request.POST, shared=shared_initial)
        has_errors = False

        if form.is_valid():
            shared_valid = form.shared_payload()
            formset = self._build_formset(data=request.POST, shared=shared_valid)
            if formset.is_valid():
                valid_forms = [
                    sub_form
                    for sub_form in formset.forms
                    if getattr(sub_form, 'cleaned_data', None)
                    and sub_form.cleaned_data.get('athlete_name')
                    and not sub_form.cleaned_data.get('DELETE')
                ]
                if not valid_forms:
                    self._append_formset_error(formset, 'Informe ao menos um atleta.')
                    has_errors = True
                else:
                    try:
                        with transaction.atomic():
                            registrations: list[AthleteRegistration] = []
                            for athlete_form in valid_forms:
                                registration = athlete_form.save(commit=False)
                                registration.event = self.event
                                registration.modality = shared_valid.get('modality', registration.Modality.AMATEUR)
                                if self.event.is_free:
                                    registration.status = registration.Status.CONFIRMED
                                    registration.save()
                                    athlete_form.save_m2m()
                                else:
                                    registration.status = registration.Status.PENDING
                                    registration.save()
                                    athlete_form.save_m2m()
                                    create_payment_for_registration(registration)
                                registrations.append(registration)
                    except MissingAsaasConfiguration as exc:
                        self._append_formset_error(formset, str(exc))
                        messages.error(request, str(exc))
                        has_errors = True
                    except AsaasAPIError as exc:
                        logger.exception('Falha ao criar cobranca Asaas: %s', exc)
                        error_message = 'Nao foi possivel gerar os pagamentos no momento. Tente novamente em instantes.'
                        self._append_formset_error(formset, error_message)
                        messages.error(request, error_message)
                        has_errors = True
                    else:
                        count = len(registrations)
                        registration_fee = self.event.registration_fee or Decimal('0')
                        total_amount = (registration_fee * count).quantize(Decimal('0.01')) if not self.event.is_free else Decimal('0.00')
                        request.session['recent_bulk_registration_ids'] = [reg.pk for reg in registrations]
                        request.session['recent_bulk_total_amount'] = str(total_amount)
                        if self.event.is_free:
                            messages.success(request, f'{count} inscricao(oes) confirmadas (evento gratuito).')
                        else:
                            messages.success(request, f'{count} inscricao(oes) criadas com sucesso!')
                        return HttpResponseRedirect(self.get_success_url())
            else:
                has_errors = True
                if not self._has_candidate(formset):
                    self._append_formset_error(formset, 'Informe ao menos um atleta.')
        else:
            has_errors = True
            if not self._has_candidate(formset):
                self._append_formset_error(formset, 'Informe ao menos um atleta.')

        if has_errors:
            messages.error(request, 'Nao foi possivel enviar as inscricoes. Verifique os campos destacados.')

        context = self.get_context_data(form=form, formset=formset, event=self.event)
        return self.render_to_response(context)
    def _build_formset(self, data=None, shared=None):
        shared_data = dict(shared or {})
        shared_data.setdefault('modality', AthleteRegistration.Modality.AMATEUR)
        form_kwargs = {'event': self.event, 'shared': shared_data}
        formset = self.formset_class(data=data, prefix='athletes', form_kwargs=form_kwargs)
        delete_field = getattr(formset, 'deletion_field_name', None)
        for form in formset.forms:
            form.empty_permitted = True
            if delete_field and delete_field in form.fields:
                form.fields[delete_field].widget = forms.HiddenInput()
                form.delete_field_widget = form[delete_field]
            else:
                form.delete_field_widget = None
        return formset

    def _shared_from_form(self, form):
        shared = {}
        for field in BulkAthleteRegistrationForm.SHARED_FIELDS:
            if field in form.fields:
                shared[field] = (form[field].value() or '')
        if 'modality' in getattr(form, 'fields', {}):
            shared['modality'] = form['modality'].value() or form.fields['modality'].initial or AthleteRegistration.Modality.AMATEUR
        else:
            shared['modality'] = AthleteRegistration.Modality.AMATEUR
        return shared

    @staticmethod
    def _append_formset_error(formset, message: str) -> None:
        existing = getattr(formset, '_non_form_errors', None)
        if existing is None:
            formset._non_form_errors = formset.error_class([message])
        else:
            error_list = list(existing) if isinstance(existing, (list, tuple)) else list(existing)
            if message not in error_list:
                error_list.append(message)
            formset._non_form_errors = formset.error_class(error_list)

    def _has_candidate(self, formset):
        delete_field = getattr(formset, 'deletion_field_name', 'DELETE')
        for form in formset.forms:
            data = getattr(form, 'cleaned_data', None) or {}
            if data.get(delete_field):
                continue
            if data.get('athlete_name'):
                return True
            raw_name = form.data.get(f"{form.prefix}-athlete_name") if hasattr(form, 'data') else None
            if raw_name:
                return True
        return False



class BulkRegistrationSuccessView(DetailView):
    model = Event
    template_name = 'events/registration_bulk_success.html'
    context_object_name = 'event'
    slug_field = 'slug'
    slug_url_kwarg = 'slug'

    def get_queryset(self):
        return Event.objects.filter(is_published=True)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        session = self.request.session
        registration_ids = session.pop('recent_bulk_registration_ids', []) or []
        registrations = list(
            self.object.registrations
            .filter(pk__in=registration_ids)
            .select_related('academy', 'coach', 'payment')
            .order_by('athlete_name')
        )
        context['registrations'] = registrations
        context['total_count'] = len(registrations)
        amount_raw = session.pop('recent_bulk_total_amount', None)
        if amount_raw is not None:
            context['total_amount'] = Decimal(amount_raw).quantize(Decimal('0.01'))
        else:
            fallback = (self.object.registration_fee or Decimal('0')) * len(registrations)
            context['total_amount'] = fallback.quantize(Decimal('0.01')) if len(registrations) else Decimal('0.00')
        return context



class EventCreateView(LoginRequiredMixin, UserPassesTestMixin, CreateView):
    template_name = 'events/event_form.html'
    form_class = EventForm
    success_url = reverse_lazy('core:dashboard')
    login_url = 'admin:login'

    def test_func(self):
        return bool(self.request.user and self.request.user.is_staff)

    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            return HttpResponseRedirect(reverse('core:dashboard'))
        return super().handle_no_permission()

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, 'Evento criado com sucesso!')
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Criar novo evento'
        return context


class EventUpdateView(LoginRequiredMixin, UserPassesTestMixin, UpdateView):
    model = Event
    template_name = 'events/event_form.html'
    form_class = EventForm
    success_url = reverse_lazy('core:dashboard')
    login_url = 'admin:login'
    slug_field = 'slug'
    slug_url_kwarg = 'slug'

    def test_func(self):
        return bool(self.request.user and self.request.user.is_staff)

    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            return HttpResponseRedirect(reverse('core:dashboard'))
        return super().handle_no_permission()

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, 'Evento atualizado com sucesso!')
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Editar evento'
        context['header_title'] = 'Atualizar dados do campeonato'
        context['header_subtitle'] = 'Revise informacoes de cronograma, local e inscricoes antes de salvar.'
        return context



class RegistrationSuccessView(DetailView):
    model = Event
    template_name = 'events/registration_success.html'
    context_object_name = 'event'
    slug_field = 'slug'
    slug_url_kwarg = 'slug'

    def get_queryset(self):
        return Event.objects.filter(is_published=True)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        registration = None
        payment = None
        session_key = 'recent_registration_id'
        registration_id = self.request.session.pop(session_key, None)
        if registration_id:
            registration = (
                self.object.registrations.select_related('payment', 'academy', 'coach')
                .filter(pk=registration_id)
                .first()
            )
            if registration:
                payment = getattr(registration, 'payment', None)
        context['registration'] = registration
        context['payment'] = payment
        return context
