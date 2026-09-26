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

"""
N+1 regression harness for the manager list endpoints (H4).

Each test captures the query count of a list endpoint with the fixture data,
then multiplies the row count and asserts the query count did not grow.
This is deliberately environment-independent: it does not pin absolute
numbers, only that serialization issues a constant number of queries.
"""

# Django
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

# wger
from wger.core.tests.base_testcase import WgerTestCase
from wger.manager.models import (
    Day,
    Routine,
    Slot,
    SlotEntry,
    WorkoutLog,
)


class ListEndpointQueryCountTestCase(WgerTestCase):
    """
    List endpoints must issue a constant number of queries, regardless of
    how many rows they serialize.
    """

    EXTRA_ROWS = 30

    def setUp(self):
        super().setUp()
        self.user_login('admin')

    def _list_query_count(self, url):
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        return len(ctx)

    def _assert_constant_queries(self, url, make_rows):
        baseline = self._list_query_count(url)
        make_rows(self.EXTRA_ROWS)
        scaled = self._list_query_count(url)
        self.assertEqual(
            scaled,
            baseline,
            f'Query count grew with row count ({baseline} -> {scaled}); this is an N+1 regression',
        )

    def test_workoutlog_list_no_n_plus_one(self):
        slot_entry = SlotEntry.objects.get(pk=1)
        routine = Routine.objects.get(pk=1)

        def make_rows(n):
            WorkoutLog.objects.bulk_create(
                WorkoutLog(
                    user_id=1,
                    routine=routine,
                    slot_entry=slot_entry,
                    exercise_id=1,
                    repetitions_unit_id=1,
                    weight_unit_id=1,
                    repetitions=5,
                    weight=80,
                    date='2024-06-01',
                    iteration=1,
                )
                for _ in range(n)
            )

        self._assert_constant_queries(reverse('workoutlog-list'), make_rows)

    def test_day_list_no_n_plus_one(self):
        routine = Routine.objects.get(pk=1)

        def make_rows(n):
            Day.objects.bulk_create(
                Day(routine=routine, order=100 + i, name=f'day {i}') for i in range(n)
            )

        self._assert_constant_queries(reverse('day-list'), make_rows)

    def test_slot_list_no_n_plus_one(self):
        day = Day.objects.filter(routine_id=1).first()

        def make_rows(n):
            Slot.objects.bulk_create(Slot(day=day, order=100 + i) for i in range(n))

        self._assert_constant_queries(reverse('slot-list'), make_rows)

    def test_slot_entry_list_no_n_plus_one(self):
        slot = Slot.objects.filter(day__routine_id=1).first()

        def make_rows(n):
            SlotEntry.objects.bulk_create(
                SlotEntry(slot=slot, exercise_id=1, order=100 + i) for i in range(n)
            )

        self._assert_constant_queries(reverse('slot-entry-list'), make_rows)
