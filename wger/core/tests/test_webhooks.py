# This file is part of wger Workout Manager.
#
# wger Workout Manager is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# wger Workout Manager is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with Workout Manager.  If not, see <http://www.gnu.org/licenses/>.

# Standard Library
import hashlib
import hmac
import json
from unittest import mock

# Django
from django.contrib.auth.models import User
from django.urls import reverse

# Third Party
from rest_framework import status

# wger
from wger.core.models import Webhook
from wger.core.services.webhooks import (
    build_signature,
    deliver_webhook,
    dispatch_event,
)
from wger.core.tests.base_testcase import WgerTestCase


class WebhookSignatureTestCase(WgerTestCase):
    """
    Test the HMAC payload signing
    """

    def test_signature_is_hmac_sha256(self):
        secret = 'secret'
        body = b'{"a": 1}'
        expected = hmac.new(secret.encode('utf-8'), body, hashlib.sha256).hexdigest()
        self.assertEqual(build_signature(secret, body), f'sha256={expected}')


class WebhookDispatchTestCase(WgerTestCase):
    """
    Test the event fan-out
    """

    def test_dispatch_enqueues_matching_webhooks(self):
        user = User.objects.get(username='test')
        subscribed = Webhook.objects.create(
            user=user, url='https://example.com/hook', events=['workoutlog.created']
        )
        Webhook.objects.create(
            user=user, url='https://example.com/other', events=['weight.created']
        )
        Webhook.objects.create(
            user=user,
            url='https://example.com/inactive',
            events=['workoutlog.created'],
            is_active=False,
        )

        with mock.patch('wger.core.tasks.deliver_webhook_task.delay') as delay:
            dispatch_event(user.id, 'workoutlog.created', {'id': '1'})

        self.assertEqual(delay.call_count, 1)
        args = delay.call_args.args
        self.assertEqual(args[0], subscribed.id)
        self.assertEqual(args[1], 'workoutlog.created')

    def test_dispatch_unknown_event_is_noop(self):
        user = User.objects.get(username='test')
        with mock.patch('wger.core.tasks.deliver_webhook_task.delay') as delay:
            dispatch_event(user.id, 'not.an.event', {})
        delay.assert_not_called()

    def test_deliver_webhook_posts_signed_payload(self):
        user = User.objects.get(username='test')
        webhook = Webhook.objects.create(
            user=user, url='https://example.com/hook', events=['weight.created']
        )

        with mock.patch('requests.post') as post:
            post.return_value.raise_for_status = mock.Mock()
            deliver_webhook(webhook.id, 'weight.created', {'value': '80'})

        kwargs = post.call_args.kwargs
        body = json.loads(kwargs['data'])
        self.assertEqual(body['event'], 'weight.created')
        self.assertEqual(body['data']['value'], '80')
        self.assertEqual(
            kwargs['headers']['X-Wger-Signature'],
            build_signature(webhook.secret, kwargs['data']),
        )

    def test_deliver_webhook_skips_inactive(self):
        user = User.objects.get(username='test')
        webhook = Webhook.objects.create(
            user=user, url='https://example.com/hook', events=['weight.created'], is_active=False
        )

        with mock.patch('requests.post') as post:
            deliver_webhook(webhook.id, 'weight.created', {})
        post.assert_not_called()


class WebhookApiTestCase(WgerTestCase):
    """
    Test the webhook CRUD API (auth matrix)
    """

    def test_create_requires_authentication(self):
        response = self.client.post(
            reverse('webhook-list'),
            data=json.dumps({'url': 'https://example.com/hook', 'events': ['weight.created']}),
            content_type='application/json',
        )
        self.assertIn(
            response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
        )

    def test_create_and_secret_not_returned(self):
        user = User.objects.get(username='test')
        self.client.force_login(user)

        response = self.client.post(
            reverse('webhook-list'),
            data=json.dumps({'url': 'https://example.com/hook', 'events': ['weight.created']}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        # The secret is shown once, here; see WebhookSecretShownOnceTestCase
        self.assertIn('secret', response.data)
        self.assertTrue(Webhook.objects.filter(user=user, url='https://example.com/hook').exists())

    def test_invalid_event_rejected(self):
        user = User.objects.get(username='test')
        self.client.force_login(user)

        response = self.client.post(
            reverse('webhook-list'),
            data=json.dumps({'url': 'https://example.com/hook', 'events': ['not.an.event']}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_list_is_owner_scoped(self):
        other = User.objects.get(username='admin')
        Webhook.objects.create(
            user=other, url='https://example.com/foreign', events=['weight.created']
        )

        user = User.objects.get(username='test')
        Webhook.objects.create(user=user, url='https://example.com/mine', events=['weight.created'])
        self.client.force_login(user)

        response = self.client.get(reverse('webhook-list'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['url'], 'https://example.com/mine')


class WebhookSecretShownOnceTestCase(WgerTestCase):
    """
    The signing secret must be visible exactly once: in the create response
    """

    def test_secret_returned_on_create_only(self):
        user = User.objects.get(username='test')
        self.client.force_login(user)

        response = self.client.post(
            reverse('webhook-list'),
            data=json.dumps({'url': 'https://example.com/hook', 'events': ['weight.created']}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('secret', response.data)

        webhook_id = response.data['id']
        detail = self.client.get(reverse('webhook-detail', kwargs={'pk': webhook_id}))
        self.assertNotIn('secret', detail.data)


class WebhookUrlValidationTestCase(WgerTestCase):
    """
    Webhook URLs must not be able to reach internal infrastructure (SSRF)
    """

    def test_plain_http_rejected(self):
        user = User.objects.get(username='test')
        self.client.force_login(user)

        response = self.client.post(
            reverse('webhook-list'),
            data=json.dumps({'url': 'http://example.com/hook', 'events': ['weight.created']}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_localhost_rejected(self):
        user = User.objects.get(username='test')
        self.client.force_login(user)

        response = self.client.post(
            reverse('webhook-list'),
            data=json.dumps({'url': 'https://localhost:6379/', 'events': ['weight.created']}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
