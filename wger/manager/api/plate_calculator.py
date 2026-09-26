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
Plate calculator: pure computation, no database access.

Given a target total weight, the bar weight and the available plate
denominations, compute a greedy per-side plate layout. The algorithm is
unit-agnostic: everything is in the caller's unit (kg or lb).
"""

# Standard Library
from decimal import Decimal


def calculate_plates(
    target: Decimal,
    bar: Decimal,
    available: list[Decimal],
) -> dict:
    """
    Compute the plates to load on each side of the bar.

    Returns a dict with:
    - ``plates``: list of ``{weight, count}`` pairs, largest first
    - ``per_side``: the weight each side must carry
    - ``leftover``: the per-side weight that could not be matched
    - ``exact``: whether the target was matched exactly
    """
    per_side = (target - bar) / 2
    if per_side < 0:
        return {
            'plates': [],
            'per_side': Decimal('0'),
            'leftover': per_side,
            'exact': False,
        }

    remaining = per_side
    plates: list[dict] = []
    for plate in sorted(set(available), reverse=True):
        if plate <= 0 or remaining < plate:
            continue
        count = int(remaining // plate)
        if count:
            plates.append({'weight': plate, 'count': count})
            remaining -= plate * count

    return {
        'plates': plates,
        'per_side': per_side,
        'leftover': remaining,
        'exact': remaining == 0,
    }
