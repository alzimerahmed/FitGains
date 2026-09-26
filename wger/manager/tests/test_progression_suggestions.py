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

"""
Test the adaptive progression suggestion service and endpoint (G7).
"""

# Standard Library
import datetime
from decimal import Decimal

# Django
from django.contrib.auth import get_user_model
from django.urls import reverse

# Third Party
from rest_framework import status

# wger
from wger.core.tests.base_testcase import WgerTestCase
from wger.manager.consts import (
    REP_UNIT_REPETITIONS,
    WEIGHT_UNIT_KG,
)
from wger.manager.models import (
    Day,
    Routine,
    Slot,
    SlotEntry,
    WorkoutLog,
)
from wger.manager.services.progression_suggestions import (
    evaluate_slot_entry,
    progression_suggestions,
)


def make_routine(user_id):
    return Routine.objects.create(
        user_id=user_id,
        name='Progression routine',
        description='',
        start=datetime.date(2024, 1, 1),
        end=datetime.date(2024, 3, 1),
    )


def make_entry(routine):
    day = Day.objects.create(routine=routine, order=1)
    slot = Slot.objects.create(day=day, order=1)
    return SlotEntry.objects.create(
        slot=slot,
        exercise_id=1,
        order=1,
        repetition_unit_id=REP_UNIT_REPETITIONS,
        weight_unit_id=WEIGHT_UNIT_KG,
    )


def prescribe(entry, weight, repetitions, sets=3, iteration=1):
    entry.weightconfig_set.create(
        slot_entry=entry,
        iteration=iteration,
        value=Decimal(weight),
        step='abs',
        operation='r',
    )
    entry.repetitionsconfig_set.create(
        slot_entry=entry,
        iteration=iteration,
        value=Decimal(repetitions),
        step='abs',
        operation='r',
    )
    entry.setsconfig_set.create(
        slot_entry=entry,
        iteration=iteration,
        value=sets,
        step='abs',
        operation='r',
    )


def log(entry, user_id, weight, repetitions, rir=None, iteration=1):
    return WorkoutLog.objects.create(
        user_id=user_id,
        routine=entry.slot.day.routine,
        slot_entry=entry,
        exercise_id=entry.exercise_id,
        date=datetime.datetime(2024, 2, 1, 10),
        iteration=iteration,
        weight=Decimal(weight),
        weight_unit_id=WEIGHT_UNIT_KG,
        repetitions=Decimal(repetitions),
        repetitions_unit_id=REP_UNIT_REPETITIONS,
        rir=Decimal(rir) if rir is not None else None,
    )


class SuggestionLogicTestCase(WgerTestCase):
    """Test the suggestion rules"""

    def setUp(self):
        super().setUp()
        self.routine = make_routine(user_id=1)
        self.entry = make_entry(self.routine)
        prescribe(self.entry, 80, 5, sets=3)

    def test_targets_beaten_suggests_increase(self):
        for rir in (3, 2, 4):
            log(self.entry, 1, 80, 5, rir=rir)

        suggestion = evaluate_slot_entry(self.entry, 1, list(self.entry.workoutlog_set.all()))
        self.assertEqual(suggestion['rule'], 'targets-beaten')
        self.assertEqual(suggestion['action'], 'increase-weight')
        self.assertEqual(suggestion['suggested']['weight'], Decimal('82.5'))
        # Explainability: observed sets and prescription are attached
        self.assertEqual(len(suggestion['observed']), 3)
        self.assertEqual(suggestion['prescription']['weight'], Decimal('80'))
        self.assertIn('reps in reserve', suggestion['reason'])

    def test_low_reserve_holds(self):
        for rir in (1, 0, 1):
            log(self.entry, 1, 80, 5, rir=rir)

        suggestion = evaluate_slot_entry(self.entry, 1, list(self.entry.workoutlog_set.all()))
        self.assertEqual(suggestion['rule'], 'low-reserve')
        self.assertEqual(suggestion['action'], 'hold')
        self.assertIsNone(suggestion['suggested'])

    def test_missed_targets_hold(self):
        log(self.entry, 1, 80, 5, rir=3)
        log(self.entry, 1, 80, 3, rir=2)
        log(self.entry, 1, 75, 5, rir=2)

        suggestion = evaluate_slot_entry(self.entry, 1, list(self.entry.workoutlog_set.all()))
        self.assertEqual(suggestion['rule'], 'targets-missed')
        self.assertEqual(suggestion['action'], 'hold')
        self.assertIn('1 of 3', suggestion['reason'])

    def test_no_logs(self):
        suggestion = evaluate_slot_entry(self.entry, 1, [])
        self.assertEqual(suggestion['rule'], 'no-logs')
        self.assertEqual(suggestion['action'], 'none')

    def test_no_prescription(self):
        entry = make_entry(make_routine(user_id=1))
        suggestion = evaluate_slot_entry(entry, 1, [])
        self.assertEqual(suggestion['rule'], 'no-prescription')


class SuggestionServiceTestCase(WgerTestCase):
    """Test the routine-level walk"""

    def test_only_entries_with_logs_get_suggestions(self):
        routine = make_routine(user_id=1)
        logged = make_entry(routine)
        prescribe(logged, 80, 5)
        log(logged, 1, 80, 5, rir=3)
        log(logged, 1, 80, 5, rir=3)
        log(logged, 1, 80, 5, rir=3)

        unlogged = make_entry(routine)
        prescribe(unlogged, 60, 8)

        suggestions = progression_suggestions(routine)
        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0]['slot_entry'], logged.pk)

    def test_other_users_logs_ignored(self):
        routine = make_routine(user_id=1)
        entry = make_entry(routine)
        prescribe(entry, 80, 5)
        log(entry, 2, 100, 10, rir=5)  # someone else's log

        self.assertEqual(progression_suggestions(routine), [])


class SuggestionApiTestCase(WgerTestCase):
    """Test the API endpoint"""

    def setUp(self):
        super().setUp()
        self.user_login('admin')
        self.user_id = get_user_model().objects.get(username='admin').pk
        self.routine = make_routine(user_id=self.user_id)
        entry = make_entry(self.routine)
        prescribe(entry, 80, 5)
        for rir in (3, 3, 2):
            log(entry, self.user_id, 80, 5, rir=rir)

    def test_endpoint_returns_suggestions(self):
        response = self.client.get(
            reverse('routine-progression-suggestions', kwargs={'pk': self.routine.pk})
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['rule'], 'targets-beaten')
        self.assertEqual(response.data[0]['suggested']['weight'], '82.50')

    def test_other_users_routine_is_404(self):
        other = make_routine(user_id=2)
        response = self.client.get(
            reverse('routine-progression-suggestions', kwargs={'pk': other.pk})
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
