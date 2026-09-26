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
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with Workout Manager. If not, see <http://www.gnu.org/licenses/>.

# Django
from django.urls import reverse

# wger
from wger.core.tests.base_testcase import WgerTestCase


class WebAppShellTestCase(WgerTestCase):
    """
    Mobile-first web shell (G9): bottom tab bar for logged-in users only
    """

    def test_bottom_nav_absent_for_anonymous(self):
        response = self.client.get(reverse('software:about-us'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'bottom-nav')
        self.assertNotContains(response, 'has-bottom-nav')

    def test_bottom_nav_present_for_authenticated(self):
        self.user_login()
        response = self.client.get(reverse('software:about-us'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'bottom-nav')
        self.assertContains(response, 'has-bottom-nav')

        # The three primary destinations are reachable from the tab bar
        self.assertContains(response, reverse('manager:routine:overview'))
        self.assertContains(response, reverse('nutrition:plan:overview'))
        self.assertContains(response, reverse('weight:overview'))

    def test_bottom_nav_marks_active_tab(self):
        self.user_login()
        response = self.client.get(reverse('manager:routine:overview'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'nav-link active')
