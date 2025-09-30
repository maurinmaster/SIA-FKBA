from datetime import timedelta

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from django.test import TestCase

from events.models import Event


class EventCreateViewTests(TestCase):
    def setUp(self):
        self.url = reverse('events:create')
        self.staff_user = get_user_model().objects.create_user(
            username='organizador',
            password='senha-forte',
            is_staff=True,
        )

    def test_login_required(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('admin:login'), response.url)

    def test_non_staff_redirected(self):
        user = get_user_model().objects.create_user(username='academia', password='123456')
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('core:dashboard'))

    def test_create_event_success(self):
        self.client.force_login(self.staff_user)
        start_at = (timezone.now() + timedelta(days=10)).replace(second=0, microsecond=0)
        deadline = start_at - timedelta(days=3)
        payload = {
            'title': 'Copa Nacional',
            'location': 'Ginásio Central',
            'description': 'Edição especial do circuito.',
            'start_at': start_at.strftime('%Y-%m-%dT%H:%M'),
            'registration_deadline': deadline.strftime('%Y-%m-%dT%H:%M'),
            'registration_fee': '150.00',
            'is_published': True,
        }
        response = self.client.post(self.url, payload, follow=True)
        self.assertRedirects(response, reverse('core:dashboard'))
        self.assertTrue(Event.objects.filter(title='Copa Nacional').exists())
