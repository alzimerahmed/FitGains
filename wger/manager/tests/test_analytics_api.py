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
# along with Workout Manager.  If not, see <http://www.gnu.org/licenses/>.

"""
Tests for the analytics read-model layer (H1) and its endpoints (G2).
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
    WEIGHT_UNIT_LB,
)
from wger.manager.models import Routine, WorkoutLog
from wger.manager.services.analytics import (
    InvalidGroupUnit,
    estimate_one_rm,
    one_rm_rows,
    volume_rows,
)


def make_log(user_id, exercise_id, weight, reps, date, iteration=1, weight_unit=WEIGHT_UNIT_KG):
    return WorkoutLog(
        user_id=user_id,
        exercise_id=exercise_id,
        weight=weight,
        repetitions=reps,
        repetitions_unit_id=REP_UNIT_REPETITIONS,
        weight_unit_id=weight_unit,
        date=date,
        iteration=iteration,
    )


class EstimateOneRmTestCase(WgerTestCase):
    """Test the pure 1RM estimation"""

    def test_epley(self):
        # 100 kg x 5 -> 100 * (1 + 5/30) = 116.67
        self.assertEqual(estimate_one_rm(100, 5, 'epley'), Decimal('116.67'))

    def test_brzycki(self):
        # 100 kg x 5 -> 100 * 36 / 32 = 112.50
        self.assertEqual(estimate_one_rm(100, 5, 'brzycki'), Decimal('112.50'))

    def test_brzycki_beyond_36_reps_is_none(self):
        self.assertIsNone(estimate_one_rm(100, 40, 'brzycki'))

    def test_single_rep_is_the_weight_itself(self):
        self.assertEqual(estimate_one_rm(100, 1, 'epley'), Decimal('103.33'))
        self.assertEqual(estimate_one_rm(100, 1, 'brzycki'), Decimal('100.00'))

    def test_missing_values_are_none(self):
        self.assertIsNone(estimate_one_rm(None, 5))
        self.assertIsNone(estimate_one_rm(100, None))
        self.assertIsNone(estimate_one_rm(0, 5))

    def test_unknown_formula_raises(self):
        with self.assertRaises(ValueError):
            estimate_one_rm(100, 5, 'wathen')


class VolumeServiceTestCase(WgerTestCase):
    """Test the tonnage aggregation"""

    def setUp(self):
        super().setUp()
        self.routine = Routine.objects.create(
            user_id=1,
            name='Analytics routine',
            description='',
            start=datetime.date(2024, 1, 1),
            end=datetime.date(2024, 3, 1),
        )
        # Feb 1 2024 is a Thursday, Feb 4 the Sunday of the same ISO week
        make_log(1, 1, 10, 5, datetime.datetime(2024, 2, 1), iteration=1).save()  # 50
        make_log(1, 1, 10, 1, datetime.datetime(2024, 2, 4), iteration=2).save()  # 10
        make_log(1, 2, 20, 3, datetime.datetime(2024, 2, 4), iteration=2).save()  # 60
        # Different weight unit: own row, never summed with the kg rows
        make_log(
            1, 2, 10, 1, datetime.datetime(2024, 2, 4), iteration=2, weight_unit=WEIGHT_UNIT_LB
        ).save()  # 10 lb
        # Timed entry without reps: counts a set, no volume
        WorkoutLog(
            user_id=1,
            exercise_id=3,
            weight=0,
            repetitions=None,
            repetitions_unit_id=REP_UNIT_REPETITIONS,
            weight_unit_id=WEIGHT_UNIT_KG,
            date=datetime.datetime(2024, 2, 4),
            iteration=2,
        ).save()

    def test_daily_volume(self):
        rows = volume_rows(1, {}, 'day')
        feb1 = [r for r in rows if r['group'] == '2024-02-01']
        feb4 = [r for r in rows if r['group'] == '2024-02-04']

        self.assertEqual(len(feb1), 1)
        self.assertEqual(feb1[0]['volume'], 50)

        # Exercise 1 kg, exercise 2 kg, exercise 2 lb, exercise 3 (no volume)
        self.assertEqual(len(feb4), 4)
        volumes = sorted(r['volume'] for r in feb4)
        self.assertEqual(volumes, [0, 10, 10, 60])

    def test_weekly_volume_groups_isoweek(self):
        rows = [r for r in volume_rows(1, {}, 'week') if r['exercise'] == 1]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['volume'], 60)

    def test_iteration_volume(self):
        rows = [r for r in volume_rows(1, {}, 'iteration') if r['exercise'] == 1]
        self.assertEqual([r['group'] for r in rows], [1, 2])
        self.assertEqual(sum(r['volume'] for r in rows), 60)

    def test_exercise_filter(self):
        rows = volume_rows(1, {'exercise': 2}, 'day')
        self.assertTrue(all(r['exercise'] == 2 for r in rows))

    def test_routine_filter(self):
        rows = volume_rows(1, {'routine': self.routine.id}, 'day')
        self.assertEqual(rows, [])

    def test_other_users_logs_are_invisible(self):
        # user 2's logs exist in the fixtures; none may leak into user 1's series
        make_log(2, 1, 999, 9, datetime.datetime(2024, 2, 1), iteration=1).save()
        rows = volume_rows(1, {}, 'day')
        self.assertTrue(all(r['volume'] <= 60 for r in rows))

    def test_invalid_unit_raises(self):
        with self.assertRaises(InvalidGroupUnit):
            volume_rows(1, {}, 'century')


class OneRmServiceTestCase(WgerTestCase):
    """Test the best-1RM reduction"""

    def setUp(self):
        super().setUp()
        # Same day: the 5-rep set estimates higher than the 10-rep one
        make_log(1, 1, 100, 5, datetime.datetime(2024, 2, 1), iteration=1).save()  # 116.67
        make_log(1, 1, 80, 10, datetime.datetime(2024, 2, 1), iteration=1).save()  # 106.67
        make_log(1, 1, 90, 3, datetime.datetime(2024, 2, 10), iteration=2).save()  # 99.00

    def test_best_set_wins_per_day(self):
        rows = one_rm_rows(1, {}, 'day', 'epley')
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['est_1rm'], Decimal('116.67'))
        self.assertEqual(rows[0]['repetitions'], 5)
        self.assertEqual(rows[1]['est_1rm'], Decimal('99.00'))
        # The winning row carries the set that produced the estimate
        self.assertEqual(rows[1]['weight'], 90)
        self.assertEqual(rows[1]['repetitions'], 3)

    def test_monthly_takes_best_across_days(self):
        rows = one_rm_rows(1, {}, 'month', 'epley')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['est_1rm'], Decimal('116.67'))

    def test_weekly_buckets_use_the_truncated_week(self):
        # Feb 1 2024 is a Thursday: its week bucket is Monday Jan 29, and the
        # Feb 10 log lands in the following week's bucket
        rows = [r for r in one_rm_rows(1, {}, 'week', 'epley') if r['exercise'] == 1]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['group'], '2024-01-29')
        self.assertEqual(rows[0]['est_1rm'], Decimal('116.67'))
        self.assertEqual(rows[1]['group'], '2024-02-05')
        self.assertEqual(rows[1]['est_1rm'], Decimal('99.00'))


class AnalyticsApiTestCase(WgerTestCase):
    """Test the analytics endpoints"""

    def setUp(self):
        super().setUp()
        self.user_login('admin')
        self.user_id = get_user_model().objects.get(username='admin').pk
        make_log(self.user_id, 1, 100, 5, datetime.datetime(2024, 2, 1), iteration=1).save()

    def test_volume_endpoint(self):
        response = self.client.get(reverse('workoutlog-analytics-list'), data={'group_by': 'day'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        row = next(r for r in response.data if r['exercise'] == 1)
        self.assertEqual(row['volume'], '500.00')

    def test_volume_endpoint_iteration_grouping(self):
        response = self.client.get(
            reverse('workoutlog-analytics-list'), data={'group_by': 'iteration'}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        row = next(r for r in response.data if r['exercise'] == 1)
        self.assertEqual(row['group'], 1)

    def test_one_rm_endpoint(self):
        response = self.client.get(
            reverse('workoutlog-analytics-one-rm'), data={'formula': 'epley'}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(any(r['est_1rm'] == '500.00' for r in response.data))

    def test_invalid_group_by_rejected(self):
        response = self.client.get(
            reverse('workoutlog-analytics-list'), data={'group_by': 'century'}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_formula_rejected(self):
        response = self.client.get(
            reverse('workoutlog-analytics-one-rm'), data={'formula': 'wathen'}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_filters_rejected(self):
        for params in (
            {'exercise': 'abc'},
            {'routine': 'x'},
            {'start': '2024-13-01'},
            {'end': 'not-a-date'},
        ):
            response = self.client.get(reverse('workoutlog-analytics-list'), data=params)
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, params)

    def test_requires_authentication(self):
        self.user_logout()
        response = self.client.get(reverse('workoutlog-analytics-list'))
        self.assertIn(
            response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
        )
