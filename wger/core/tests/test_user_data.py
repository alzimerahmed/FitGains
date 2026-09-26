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
from django.contrib.auth.models import User

# wger
from wger.core.tests.base_testcase import WgerTestCase
from wger.core.user_data import (
    export_user_data,
    import_user_data,
)
from wger.manager.models import (
    Routine,
    WorkoutLog,
)


class UserDataExportImportTestCase(WgerTestCase):
    """
    Round-trip test: export a user's data, import it for another user,
    and verify the rows were recreated with ownership and FK remapping.
    """

    def test_round_trip(self):
        source = User.objects.get(username='admin')
        target = User.objects.get(username='test')

        payload = export_user_data(source)
        self.assertEqual(payload['version'], 1)

        before_routines = Routine.objects.filter(user=source).count()
        before_logs = WorkoutLog.objects.filter(user=source).count()

        counts = import_user_data(target, payload)

        self.assertEqual(counts['manager.routine'], before_routines)
        self.assertEqual(counts['manager.workoutlog'], before_logs)

        # All imported routines belong to the target user
        imported = Routine.objects.filter(user=target).order_by('pk')
        self.assertEqual(imported.count(), before_routines)
        for routine in imported:
            self.assertEqual(routine.user, target)

        # The new rows must not collide with the source pks
        source_pks = set(Routine.objects.filter(user=source).values_list('pk', flat=True))
        for routine in imported:
            self.assertNotIn(routine.pk, source_pks)

        # FK remapping: imported days point at the new routines, not the source's
        # wger
        from wger.manager.models import Day

        imported_day_routine_pks = set(
            Day.objects.filter(routine__user=target).values_list('routine_id', flat=True)
        )
        self.assertTrue(imported_day_routine_pks.issubset({r.pk for r in imported}))
        self.assertFalse(imported_day_routine_pks & source_pks)

    def test_import_rejects_unknown_version(self):
        user = User.objects.get(username='test')
        with self.assertRaises(ValueError):
            import_user_data(user, {'version': 999})
