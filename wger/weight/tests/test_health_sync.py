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
import json
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

# Django
from django.contrib.auth.models import User
from django.urls import reverse

# Third Party
from rest_framework import status

# wger
from wger.core.tests.base_testcase import WgerTestCase
from wger.measurements.models import Measurement


class HealthSyncApiTestCase(WgerTestCase):
    """
    Test the health-platform weight sync endpoint (G3)
    """

    def sample(self, external_id=None, weight='82.5'):
        return {
            'external_id': str(external_id or uuid.uuid4()),
            'date': datetime(2026, 9, 1, 8, 0, tzinfo=ZoneInfo('UTC')).isoformat(),
            'weight': weight,
            'source': 'google',
        }

    def test_sync_requires_authentication(self):
        response = self.client.post(
            reverse('weightentry-sync'),
            data=json.dumps([self.sample()]),
            content_type='application/json',
        )
        self.assertIn(
            response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
        )

    def test_sync_creates_entries(self):
        user = User.objects.get(username='test')
        self.client.force_login(user)

        response = self.client.post(
            reverse('weightentry-sync'),
            data=json.dumps([self.sample(), self.sample()]),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['created'], 2)
        self.assertEqual(response.data['updated'], 0)
        self.assertEqual(Measurement.objects.filter(category__user=user).count() >= 2, True)

    def test_sync_is_idempotent(self):
        user = User.objects.get(username='test')
        external_id = uuid.uuid4()
        self.client.force_login(user)

        self.client.post(
            reverse('weightentry-sync'),
            data=json.dumps([self.sample(external_id)]),
            content_type='application/json',
        )
        response = self.client.post(
            reverse('weightentry-sync'),
            data=json.dumps([self.sample(external_id, weight='83.0')]),
            content_type='application/json',
        )
        self.assertEqual(response.data['created'], 0)
        self.assertEqual(response.data['updated'], 1)

        entries = Measurement.objects.filter(external_id=external_id)
        self.assertEqual(entries.count(), 1)
        self.assertEqual(entries.first().value, __import__('decimal').Decimal('83.0'))

    def test_sync_rejects_invalid_samples_individually(self):
        user = User.objects.get(username='test')
        self.client.force_login(user)

        response = self.client.post(
            reverse('weightentry-sync'),
            data=json.dumps([self.sample(), self.sample(weight='99999')]),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['created'], 1)
        self.assertEqual(len(response.data['rejected']), 1)
        self.assertEqual(response.data['rejected'][0]['index'], 1)

    def test_sync_rejects_unknown_source(self):
        user = User.objects.get(username='test')
        self.client.force_login(user)
        sample = self.sample()
        sample['source'] = 'fitbit'

        response = self.client.post(
            reverse('weightentry-sync'), data=json.dumps([sample]), content_type='application/json'
        )
        self.assertEqual(response.data['created'], 0)
        self.assertEqual(len(response.data['rejected']), 1)
