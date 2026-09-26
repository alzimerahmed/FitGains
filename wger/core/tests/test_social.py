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

# Django
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

# Third Party
from rest_framework import status

# wger
from wger.core.models import UserFollow
from wger.core.tests.base_testcase import WgerTestCase
from wger.manager.models import Routine, WorkoutSession


class UserFollowApiTestCase(WgerTestCase):
    """
    Test the follow endpoints (G6)
    """

    def test_follow_user_with_social_enabled(self):
        follower = User.objects.get(username='test')
        followee = User.objects.get(username='admin')
        followee.userprofile.social_enabled = True
        followee.userprofile.save()

        self.client.force_login(follower)
        response = self.client.post(
            reverse('userfollow-list'),
            data=json.dumps({'followee': followee.pk}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(UserFollow.objects.filter(follower=follower, followee=followee).exists())

    def test_follow_user_with_social_disabled_rejected(self):
        follower = User.objects.get(username='test')
        followee = User.objects.get(username='admin')
        followee.userprofile.social_enabled = False
        followee.userprofile.save()

        self.client.force_login(follower)
        response = self.client.post(
            reverse('userfollow-list'),
            data=json.dumps({'followee': followee.pk}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_self_follow_rejected(self):
        user = User.objects.get(username='test')
        user.userprofile.social_enabled = True
        user.userprofile.save()

        self.client.force_login(user)
        response = self.client.post(
            reverse('userfollow-list'),
            data=json.dumps({'followee': user.pk}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_duplicate_follow_rejected(self):
        follower = User.objects.get(username='test')
        followee = User.objects.get(username='admin')
        followee.userprofile.social_enabled = True
        followee.userprofile.save()
        UserFollow.objects.create(follower=follower, followee=followee)

        self.client.force_login(follower)
        response = self.client.post(
            reverse('userfollow-list'),
            data=json.dumps({'followee': followee.pk}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unfollow(self):
        follower = User.objects.get(username='test')
        followee = User.objects.get(username='admin')
        follow = UserFollow.objects.create(follower=follower, followee=followee)

        self.client.force_login(follower)
        response = self.client.delete(reverse('userfollow-detail', kwargs={'pk': follow.pk}))
        self.assertIn(response.status_code, (status.HTTP_204_NO_CONTENT, status.HTTP_200_OK))
        self.assertFalse(UserFollow.objects.filter(pk=follow.pk).exists())

    def test_cannot_delete_foreign_follow(self):
        follower = User.objects.get(username='admin')
        followee = User.objects.get(username='test')
        follow = UserFollow.objects.create(follower=follower, followee=followee)

        self.client.force_login(User.objects.get(username='test'))
        response = self.client.delete(reverse('userfollow-detail', kwargs={'pk': follow.pk}))
        self.assertIn(response.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND))


class SocialFeedTestCase(WgerTestCase):
    """
    Test the shared-workout feed (G6)
    """

    def make_shared_session(self, user: User, is_public: bool) -> WorkoutSession:
        routine = Routine.objects.filter(user=user).first()
        return WorkoutSession.objects.create(
            user=user, routine=routine, datetime_start=timezone.now(), is_public=is_public
        )

    def test_feed_shows_only_opted_in_shared_sessions(self):
        follower = User.objects.get(username='test')
        followee = User.objects.get(username='admin')
        followee.userprofile.social_enabled = True
        followee.userprofile.save()
        UserFollow.objects.create(follower=follower, followee=followee)

        shared = self.make_shared_session(followee, is_public=True)
        self.make_shared_session(followee, is_public=False)

        self.client.force_login(follower)
        response = self.client.get(reverse('social-feed-list'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [item['id'] for item in response.data['results']]
        self.assertIn(str(shared.pk), ids)
        self.assertEqual(len(ids), 1)

    def test_feed_hides_sessions_when_social_disabled(self):
        follower = User.objects.get(username='test')
        followee = User.objects.get(username='admin')
        followee.userprofile.social_enabled = False
        followee.userprofile.save()
        UserFollow.objects.create(follower=follower, followee=followee)

        self.make_shared_session(followee, is_public=True)

        self.client.force_login(follower)
        response = self.client.get(reverse('social-feed-list'))
        self.assertEqual(response.data['count'], 0)

    def test_feed_empty_without_follows(self):
        user = User.objects.get(username='test')
        self.client.force_login(user)
        response = self.client.get(reverse('social-feed-list'))
        self.assertEqual(response.data['count'], 0)

    def test_feed_requires_authentication(self):
        response = self.client.get(reverse('social-feed-list'))
        self.assertEqual(response.data['count'], 0)

    def test_feed_includes_username(self):
        follower = User.objects.get(username='test')
        followee = User.objects.get(username='admin')
        followee.userprofile.social_enabled = True
        followee.userprofile.save()
        UserFollow.objects.create(follower=follower, followee=followee)

        self.make_shared_session(followee, is_public=True)

        self.client.force_login(follower)
        response = self.client.get(reverse('social-feed-list'))
        self.assertEqual(response.data['results'][0]['username'], 'admin')
