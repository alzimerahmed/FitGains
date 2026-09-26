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

# Standard Library
from decimal import Decimal

# Django
from django.urls import reverse

# Third Party
from rest_framework import status

# wger
from wger.core.tests.base_testcase import WgerTestCase
from wger.manager.api.plate_calculator import calculate_plates


class PlateCalculatorLogicTestCase(WgerTestCase):
    """
    Test the pure plate calculation logic
    """

    def test_exact_match(self):
        result = calculate_plates(Decimal('100'), Decimal('20'), [Decimal('25'), Decimal('5')])
        self.assertTrue(result['exact'])
        self.assertEqual(result['plates'], [{'weight': Decimal('25'), 'count': 1}])
        self.assertEqual(result['leftover'], Decimal('0'))

    def test_greedy_uses_largest_first(self):
        result = calculate_plates(
            Decimal('60'), Decimal('20'), [Decimal('10'), Decimal('5'), Decimal('2.5')]
        )
        self.assertTrue(result['exact'])
        self.assertEqual(
            result['plates'],
            [
                {'weight': Decimal('10'), 'count': 2},
            ],
        )

    def test_leftover_when_unmatchable(self):
        result = calculate_plates(Decimal('100'), Decimal('20'), [Decimal('10')])
        # per side 40, only 10s available -> exact
        self.assertTrue(result['exact'])

        result = calculate_plates(Decimal('101'), Decimal('20'), [Decimal('10')])
        self.assertFalse(result['exact'])
        self.assertEqual(result['leftover'], Decimal('0.5'))

    def test_target_below_bar(self):
        result = calculate_plates(Decimal('10'), Decimal('20'), [Decimal('5')])
        self.assertFalse(result['exact'])
        self.assertEqual(result['plates'], [])

    def test_duplicate_denominations_ignored(self):
        result = calculate_plates(
            Decimal('100'), Decimal('20'), [Decimal('10'), Decimal('10'), Decimal('5')]
        )
        self.assertTrue(result['exact'])
        self.assertEqual(len(result['plates']), 2)


class PlateCalculatorApiTestCase(WgerTestCase):
    """
    Test the plate calculator API endpoint
    """

    def test_calculate(self):
        response = self.client.get(
            reverse('plate-calculator-list'),
            data={'weight': '100', 'bar': '20', 'available': '25,10,5'},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['exact'])
        self.assertEqual(response.data['plates'], [{'weight': '25.00', 'count': 2}])

    def test_missing_weight_is_rejected(self):
        response = self.client.get(reverse('plate-calculator-list'))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_weight_is_rejected(self):
        response = self.client.get(reverse('plate-calculator-list'), data={'weight': 'abc'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
