#  This file is part of wger Workout Manager <https://github.com/wger-project>.
#  Copyright (C) wger Team
#
#  wger Workout Manager is free software: you can redistribute it and/or modify
#  it under the terms of the GNU Affero General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  wger Workout Manager is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Affero General Public License for more details.
#
#  You should have received a copy of the GNU Affero General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""
Read-model aggregation layer for workout analytics (H1).

Turns the raw workout log stream into the series a chart draws: tonnage
(volume) and estimated one rep max per exercise, bucketed by calendar unit
or by routine iteration. The condensing happens here, in one query pass,
not per point in the client — same rationale as the measurement chart
aggregates in ``wger.measurements.api.aggregates``.

Weight units are never mixed inside a row: a sum over kg and lb values is a
number in neither unit, so rows are grouped per stored unit and the client
converts each row through its own helper.
"""

# Standard Library
import datetime
from decimal import (
    ROUND_HALF_UP,
    Decimal,
)

# Django
from django.db.models import (
    Count,
    DecimalField,
    F,
    Max,
    Q,
    Sum,
)
from django.db.models.functions import (
    Coalesce,
    TruncDay,
    TruncMonth,
    TruncWeek,
)

# wger
from wger.manager.models import WorkoutLog


#: Calendar units the series can be bucketed into, finest first
GROUP_UNITS = ('day', 'week', 'month', 'iteration')

_TRUNC = {
    'day': TruncDay,
    'week': TruncWeek,
    'month': TruncMonth,
}

#: One-rep-max formulas supported by the estimation endpoint
ONE_RM_FORMULAS = ('epley', 'brzycki')


class InvalidGroupUnit(ValueError):
    """The client asked for a bucket unit that does not exist"""


def _bucket_expression(unit: str):
    """The annotation that assigns each log to its bucket"""
    if unit == 'iteration':
        return 'iteration'
    return _TRUNC[unit]('date')


def _bucket_key(unit: str, row) -> str | int | None:
    """The python-side value of a row's bucket"""
    if unit == 'iteration':
        return row['iteration']
    value = row['bucket']
    return value.date() if isinstance(value, datetime.datetime) else value


def _group_out(value) -> str | int | None:
    """
    The wire form of a bucket key: ISO date strings for calendar buckets,
    plain ints for iteration numbers — one shape per `group_by`, never a
    datetime the client would have to guess the timezone of.
    """
    if isinstance(value, datetime.date):
        return value.isoformat()
    return value


def _scoped_logs(user, filters: dict):
    """
    The owner's logs, narrowed by the shared filter set.

    Every analytics endpoint funnels through this so ownership filtering
    can't be forgotten on a new metric.
    """
    qs = WorkoutLog.objects.filter(user=user)
    if exercise_id := filters.get('exercise'):
        qs = qs.filter(exercise_id=exercise_id)
    if routine_id := filters.get('routine'):
        qs = qs.filter(routine_id=routine_id)
    if start := filters.get('start'):
        # Range on the raw timestamp (not a ::date cast) so the (user, date)
        # index stays usable
        qs = qs.filter(date__gte=start)
    if end := filters.get('end'):
        qs = qs.filter(date__lt=end + datetime.timedelta(days=1))
    return qs


def volume_rows(user, filters: dict, group_by: str = 'day') -> list[dict]:
    """
    Tonnage (weight x repetitions) per exercise and bucket, oldest first.

    One aggregated query per call; rows carry the stored weight unit so
    mixed-unit histories stay convertible. Logs without a weight or
    repetition value (e.g. timed entries) contribute no volume but still
    count towards the set total.
    """
    if group_by not in GROUP_UNITS:
        raise InvalidGroupUnit(f'Unknown bucket: {group_by}')

    qs = _scoped_logs(user, filters)
    if group_by == 'iteration':
        rows_qs = (
            qs.values('iteration', 'exercise_id', 'weight_unit_id')
            .annotate(
                volume=Coalesce(
                    Sum(
                        F('weight') * F('repetitions'),
                        filter=Q(weight__isnull=False, repetitions__isnull=False),
                    ),
                    Decimal(0),
                    output_field=DecimalField(max_digits=12, decimal_places=2),
                ),
                sets=Count('id'),
                sessions=Count('session', distinct=True),
                best_weight=Max('weight'),
            )
            .order_by('iteration', 'exercise_id', 'weight_unit_id')
        )
    else:
        rows_qs = (
            qs.annotate(bucket=_TRUNC[group_by]('date'))
            .values('bucket', 'exercise_id', 'weight_unit_id')
            .annotate(
                volume=Coalesce(
                    Sum(
                        F('weight') * F('repetitions'),
                        filter=Q(weight__isnull=False, repetitions__isnull=False),
                    ),
                    Decimal(0),
                    output_field=DecimalField(max_digits=12, decimal_places=2),
                ),
                sets=Count('id'),
                sessions=Count('session', distinct=True),
                best_weight=Max('weight'),
            )
            .order_by('bucket', 'exercise_id', 'weight_unit_id')
        )

    return [
        {
            'group': _group_out(_bucket_key(group_by, row)),
            'exercise': row['exercise_id'],
            'weight_unit': row['weight_unit_id'],
            'volume': row['volume'],
            'sets': row['sets'],
            'sessions': row['sessions'],
            'best_weight': row['best_weight'],
        }
        for row in rows_qs
    ]


def estimate_one_rm(
    weight: Decimal,
    repetitions: Decimal,
    formula: str = 'epley',
) -> Decimal | None:
    """
    The estimated one rep max of a single set, in the set's own weight unit.

    Epley: w * (1 + r / 30). Brzycki: w * 36 / (37 - r), undefined from 37
    reps up — those sets return None instead of a negative or infinite
    estimate. A set without weight or reps has no estimate either.
    """
    if weight is None or repetitions is None:
        return None

    # Callers hand in whatever the ORM or an int literal produced; ints go
    # through float math on `repetitions / 30` otherwise
    weight = Decimal(str(weight))
    repetitions = Decimal(str(repetitions))
    if weight <= 0 or repetitions <= 0:
        return None

    if formula == 'epley':
        return (weight * (1 + repetitions / 30)).quantize(Decimal('0.01'), ROUND_HALF_UP)

    if formula == 'brzycki':
        if repetitions >= 37:
            return None
        return (weight * 36 / (37 - repetitions)).quantize(Decimal('0.01'), ROUND_HALF_UP)

    raise ValueError(f'Unknown formula: {formula}')


def one_rm_rows(user, filters: dict, group_by: str = 'day', formula: str = 'epley') -> list[dict]:
    """
    Best estimated 1RM per exercise and bucket, oldest first.

    Computed per log in python and reduced to the maximum: the estimate is
    a non-linear function of the pair (weight, repetitions), so no SQL
    aggregate over a single column can find the best set. Personal log
    volumes make the one pass over values rows the cheaper and simpler
    side of the trade-off.
    """
    if group_by not in GROUP_UNITS:
        raise InvalidGroupUnit(f'Unknown bucket: {group_by}')

    qs = _scoped_logs(user, filters).filter(
        weight__isnull=False,
        repetitions__isnull=False,
    )
    if group_by == 'iteration':
        qs = qs.order_by('iteration')
    else:
        qs = qs.annotate(bucket=_TRUNC[group_by]('date')).order_by('bucket')

    best: dict[tuple, dict] = {}
    for log in qs:
        estimate = estimate_one_rm(log.weight, log.repetitions, formula)
        if estimate is None:
            continue

        # The annotated bucket, not the raw timestamp: two logs of the same
        # week must land in the same week bucket
        if group_by == 'iteration':
            bucket = log.iteration
        else:
            bucket_value = log.bucket
            bucket = (
                bucket_value.date() if isinstance(bucket_value, datetime.datetime) else bucket_value
            )

        key = (bucket, log.exercise_id, log.weight_unit_id)
        current = best.get(key)
        if current is None or estimate > current['est_1rm']:
            best[key] = {
                'group': _group_out(bucket),
                'exercise': log.exercise_id,
                'weight_unit': log.weight_unit_id,
                'est_1rm': estimate,
                'weight': log.weight,
                'repetitions': log.repetitions,
                'date': log.date.date() if isinstance(log.date, datetime.datetime) else log.date,
            }

    return sorted(
        best.values(),
        key=lambda r: (str(r['group']), r['exercise'], r['weight_unit'] or 0),
    )
