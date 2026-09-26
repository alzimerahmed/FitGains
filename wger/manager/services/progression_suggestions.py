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
Rule-based adaptive progression suggestions (G7).

Reads what the user actually lifted against what the routine prescribed
and proposes the next step for each exercise slot. Every suggestion is
explainable: it carries the rule that fired, the observed sets, the
prescription they were measured against and a plain-language reason —
the client can show *why* a suggestion was made, not just *what*.

The suggestions are advisory only: nothing here writes configs, the user
(or their client) applies a suggestion explicitly.
"""

# Standard Library
from decimal import Decimal
from typing import TYPE_CHECKING

# wger
from wger.manager.config_calculations.default import display_rounding
from wger.manager.dataclasses import round_value

if TYPE_CHECKING:
    # wger
    from wger.manager.models import Routine

#: RiR a completed set must still leave for the weight to be raised
RIR_THRESHOLD = Decimal(2)

#: Default weight step when the entry defines no rounding
DEFAULT_WEIGHT_STEP = Decimal('2.5')


def _weight_step(slot_entry) -> Decimal:
    """The smallest weight increment the entry is rounded to"""
    step = slot_entry.weight_rounding
    return Decimal(step) if step else DEFAULT_WEIGHT_STEP


def evaluate_slot_entry(slot_entry, iteration: int, logs) -> dict:
    """
    One suggestion for one slot entry, with the full explanation attached.

    ``logs`` are the entry's logs of ``iteration`` — the last iteration the
    user actually trained this exercise.
    """
    config = slot_entry.get_config_data(iteration)
    observed = [
        {
            'weight': log.weight,
            'repetitions': log.repetitions,
            'rir': log.rir,
        }
        for log in logs
    ]

    base = {
        'slot_entry': slot_entry.pk,
        'exercise': slot_entry.exercise_id,
        'iteration': iteration,
        'observed': observed,
        'prescription': {
            'weight': config.weight,
            'repetitions': config.repetitions,
            'rir': config.rir,
            'sets': config.sets,
        },
        'suggested': None,
    }

    if config.weight is None or config.repetitions is None or config.sets is None:
        return {
            **base,
            'rule': 'no-prescription',
            'action': 'none',
            'reason': 'The prescription for this exercise has no weight and repetitions '
            'to measure the logs against.',
        }

    if not logs:
        return {
            **base,
            'rule': 'no-logs',
            'action': 'none',
            'reason': f'No logs for iteration {iteration} — train the exercise once '
            'to get a suggestion.',
        }

    target_weight = round_value(config.weight, display_rounding(slot_entry, 'weight'))
    target_reps = round_value(config.repetitions, display_rounding(slot_entry, 'repetitions'))

    met = [
        log
        for log in logs
        if log.weight is not None
        and log.repetitions is not None
        and log.weight >= target_weight
        and log.repetitions >= target_reps
    ]
    max_rir = max((log.rir for log in met if log.rir is not None), default=None)

    if len(met) < config.sets:
        return {
            **base,
            'rule': 'targets-missed',
            'action': 'hold',
            'reason': f'{len(met)} of {config.sets} prescribed sets reached '
            f'{target_weight} kg x {target_reps} — repeat the same load until '
            'all sets hit the targets.',
        }

    if max_rir is not None and max_rir < RIR_THRESHOLD:
        return {
            **base,
            'rule': 'low-reserve',
            'action': 'hold',
            'reason': f'All sets hit the targets but at most {max_rir} reps in '
            'reserve were left — consolidate this load before increasing.',
        }

    step = _weight_step(slot_entry)
    return {
        **base,
        'rule': 'targets-beaten',
        'action': 'increase-weight',
        'reason': f'All {config.sets} sets reached {target_weight} kg x {target_reps} '
        f'with {max_rir if max_rir is not None else RIR_THRESHOLD}+ reps in reserve '
        f'— add {step} kg.',
        'suggested': {'weight': config.weight + step, 'repetitions': config.repetitions},
    }


def progression_suggestions(routine: 'Routine') -> list[dict]:
    """
    Suggestions for every logged exercise slot of the routine, newest first.
    """
    # wger
    from wger.manager.models import SlotEntry

    out = []
    entries = (
        SlotEntry.objects.filter(slot__day__routine=routine)
        .select_related('slot__day__routine')
        .iterator()
    )

    for slot_entry in entries:
        logs = slot_entry.workoutlog_set.filter(
            user=routine.user,
            routine=routine,
            iteration__isnull=False,
        )
        latest = logs.order_by('-iteration').values_list('iteration', flat=True).first()
        if latest is None:
            continue

        out.append(evaluate_slot_entry(slot_entry, latest, list(logs.filter(iteration=latest))))

    return out
