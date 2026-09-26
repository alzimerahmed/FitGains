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
import datetime
import json

# Django
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

# Third Party
from rest_framework import status

# wger
from wger.core.tests.base_testcase import WgerTestCase
from wger.manager.models import Routine, RoutineShareToken


class RoutineShareTokenTestCase(WgerTestCase):
    """
    Test the routine share link endpoints (G5)
    """

    def get_own_template(self) -> Routine:
        user = User.objects.get(username='test')
        return Routine.templates.filter(user=user).first()

    def test_create_token_returns_token(self):
        user = User.objects.get(username='test')
        template = self.get_own_template()
        self.client.force_login(user)

        response = self.client.post(
            reverse('routine-share-token-list'),
            data=json.dumps({'routine': template.pk}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('token', response.data)
        self.assertEqual(RoutineShareToken.objects.filter(routine=template).count(), 1)

    def test_create_token_for_foreign_routine_rejected(self):
        user = User.objects.get(username='test')
        foreign = Routine.objects.exclude(user=user).first()
        self.client.force_login(user)

        response = self.client.post(
            reverse('routine-share-token-list'),
            data=json.dumps({'routine': foreign.pk}),
            content_type='application/json',
        )
        # The ownership permission layer answers before the serializer can
        self.assertIn(
            response.status_code, (status.HTTP_400_BAD_REQUEST, status.HTTP_403_FORBIDDEN)
        )
        self.assertEqual(RoutineShareToken.objects.count(), 0)

    def test_create_token_for_non_template_rejected(self):
        user = User.objects.get(username='test')
        routine = Routine.objects.filter(user=user, is_template=False).first()
        self.client.force_login(user)

        response = self.client.post(
            reverse('routine-share-token-list'),
            data=json.dumps({'routine': routine.pk}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_resolve_unauthenticated(self):
        template = self.get_own_template()
        token = RoutineShareToken.objects.create(routine=template)

        response = self.client.get(reverse('routine-share-resolve', kwargs={'token': token.token}))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('days', response.data)

    def test_resolve_revoked_token_404(self):
        template = self.get_own_template()
        token = RoutineShareToken.objects.create(routine=template, revoked=True)

        response = self.client.get(reverse('routine-share-resolve', kwargs={'token': token.token}))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_resolve_expired_token_404(self):
        template = self.get_own_template()
        token = RoutineShareToken.objects.create(
            routine=template, expires_at=timezone.now() - datetime.timedelta(hours=1)
        )

        response = self.client.get(reverse('routine-share-resolve', kwargs={'token': token.token}))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_token_list_is_owner_scoped(self):
        template = self.get_own_template()
        RoutineShareToken.objects.create(routine=template)
        self.client.force_login(User.objects.get(username='test'))

        response = self.client.get(reverse('routine-share-token-list'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)


class RoutineCopyApiTestCase(WgerTestCase):
    """
    Test the routine copy API action (G5)
    """

    def test_copy_public_template(self):
        user = User.objects.get(username='test')
        public = Routine.public.first()
        self.assertNotEqual(public.user, user)

        self.client.force_login(user)
        response = self.client.post(reverse('routine-copy', kwargs={'pk': public.pk}))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        copy = Routine.objects.get(pk=response.data['id'])
        self.assertEqual(copy.user, user)
        self.assertFalse(copy.is_template)
        self.assertFalse(copy.is_public)
        self.assertEqual(copy.days.count(), public.days.count())

    def test_copy_own_routine(self):
        user = User.objects.get(username='test')
        routine = Routine.objects.filter(user=user, is_template=False).first()
        count_before = Routine.objects.filter(user=user).count()

        self.client.force_login(user)
        response = self.client.post(reverse('routine-copy', kwargs={'pk': routine.pk}))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Routine.objects.filter(user=user).count(), count_before + 1)

    def test_copy_foreign_private_routine_forbidden(self):
        user = User.objects.get(username='test')
        foreign = (
            Routine.objects.filter(is_public=False, is_template=False).exclude(user=user).first()
        )
        if foreign is None:
            self.skipTest('No foreign private routine in fixtures')

        self.client.force_login(user)
        response = self.client.post(reverse('routine-copy', kwargs={'pk': foreign.pk}))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
