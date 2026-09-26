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
Default progression strategy.

The rule-walk that was historically inline in ``SlotEntry.get_config_data``
lives here as a pluggable strategy class: custom progression logics subclass
``AbstractSetCalculations`` (see ``dummy.py``), and this module implements the
built-in behaviour so new strategies (e.g. adaptive suggestions) have a
reference implementation to build on.
"""

# Standard Library
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import (
    TYPE_CHECKING,
    List,
)

# wger
from wger.manager.consts import REQUIREMENTS_RULES_KEYS
from wger.manager.dataclasses import (
    SetConfigData,
    round_value,
)
from wger.manager.models.abstract_config import (
    MAX_COMPOUND_RIR,
    MAX_COMPOUND_VALUE,
    AbstractChangeConfig,
    OperationChoices,
    StepChoices,
)


if TYPE_CHECKING:
    # wger
    from wger.manager.models import (
        SlotEntry,
        WorkoutLog,
    )


PROGRESSION_FIELDS = [
    'weight',
    'maxweight',
    'repetitions',
    'maxrepetitions',
    'rir',
    'maxrir',
    'rest',
    'maxrest',
    'sets',
    'maxsets',
]
"""Fields with progression configs"""

BASE_FIELD = {
    'maxweight': 'weight',
    'maxrepetitions': 'repetitions',
    'maxrir': 'rir',
    'maxrest': 'rest',
    'maxsets': 'sets',
}
"""Maps max fields to their base field, both advance together"""

FIELD_CAPS = {
    field: MAX_COMPOUND_RIR if field in ('rir', 'maxrir') else MAX_COMPOUND_VALUE
    for field in PROGRESSION_FIELDS
}
"""Caps per field, mirror the limits of the display serializer fields"""


def _apply_config_value(
    value: Decimal | None,
    config: AbstractChangeConfig,
    max_value: Decimal,
) -> Decimal:
    """
    Applies a single config step to the running value.

    ``max_value`` clamps the result so e.g. repeated percent progressions
    can't overflow the display field's ``max_digits``.
    """
    out = value if value is not None else Decimal(0)

    if config.replace:
        out = config.value
    else:
        step = config.value if config.step == StepChoices.ABSOLUTE else out * config.value / 100

        if config.operation == OperationChoices.PLUS:
            out += step
        else:
            out -= step

    # Safety net
    if out > max_value:
        out = max_value

    return out


@dataclass(slots=True)
class _WalkState:
    """
    Walk state of a single progression field.

    ``value`` is the running value after all applied configs, ``active`` the
    config whose run covers the current iteration and ``armed`` a gated
    non-repeating config waiting for a qualifying iteration.

    ``advance`` must run for every field of an iteration before any ``apply``,
    the requirement gates of max fields read the candidate of their base field.
    """

    value: Decimal | None = None
    active: AbstractChangeConfig | None = None
    armed: AbstractChangeConfig | None = None

    def advance(self, config: AbstractChangeConfig | None) -> AbstractChangeConfig | None:
        """
        Moves to the next iteration and returns the config that wants to apply.

        A config owns its own iteration, a repeating config also owns every
        following iteration until another config takes over. A non-repeating
        gated config that couldn't apply yet stays armed until it fires or a
        newer config takes over.
        """
        if config is not None:
            self.active = config
            self.armed = None
            return config

        if self.active is not None and self.active.repeat:
            return self.active

        return self.armed

    def apply(
        self,
        candidate: AbstractChangeConfig,
        is_open: bool,
        max_value: Decimal,
    ) -> None:
        """Applies the candidate or arms it for a later qualifying iteration"""
        if is_open:
            self.value = _apply_config_value(self.value, candidate, max_value)
            self.armed = None
        elif not candidate.repeat:
            self.armed = candidate


def display_rounding(slot_entry: 'SlotEntry', field: str) -> Decimal | int | None:
    """Rounding applied to a field for display and requirement thresholds"""
    return {
        'weight': slot_entry.weight_rounding,
        'repetitions': slot_entry.repetition_rounding,
        'rir': Decimal('0.5'),
        'rest': 1,
    }.get(field)


def requirements_met(requirements, log_data: List['WorkoutLog'], thresholds: dict) -> bool:
    """True if any single log reaches the thresholds of all required fields"""

    def rule_met(log: 'WorkoutLog', rule: str) -> bool:
        log_value = getattr(log, rule, None)
        threshold = thresholds.get(rule)
        return log_value is not None and threshold is not None and log_value >= threshold

    return any(all(rule_met(log, rule) for rule in requirements.rules) for log in log_data)


class DefaultSetCalculations:
    """
    The built-in progression strategy.

    The configs of every field are walked iteration by iteration. Configs
    without requirements apply on their calendar schedule. Configs with
    requirements only apply on iterations where a log of the previous
    iteration reaches the displayed prescription of all required fields,
    earning one application per qualifying iteration.
    """

    def __init__(self, slot_entry: 'SlotEntry', iteration: int):
        self.slot_entry = slot_entry
        self.iteration = max(iteration, 1)

    def calculate(self) -> SetConfigData:
        slot_entry = self.slot_entry
        target = self.iteration

        configs_by_field = {
            field: {
                config.iteration: config
                for config in getattr(slot_entry, f'{field}config_set').all()
                if config.iteration <= target
            }
            for field in PROGRESSION_FIELDS
        }
        states = {field: _WalkState() for field in PROGRESSION_FIELDS}

        logs_by_iteration = defaultdict(list)
        for log in slot_entry.workoutlog_set.filter(user=slot_entry.slot.day.routine.user):
            logs_by_iteration[log.iteration].append(log)

        for i in range(1, target + 1):
            # Thresholds are the displayed prescriptions of the previous iteration
            thresholds = {
                rule: round_value(states[rule].value, display_rounding(slot_entry, rule))
                for rule in REQUIREMENTS_RULES_KEYS
            }
            log_data = logs_by_iteration.get(i - 1, [])

            # All fields advance first, the gates below read the candidates
            # of their base fields
            candidates = {
                field: states[field].advance(configs_by_field[field].get(i))
                for field in PROGRESSION_FIELDS
            }

            for field in PROGRESSION_FIELDS:
                candidate = candidates[field]
                if candidate is None:
                    continue

                # Min and max configs advance together, gated by the base config
                gate_config = candidate
                base_field = BASE_FIELD.get(field)
                if base_field and configs_by_field[base_field]:
                    gate_config = candidates[base_field] or states[base_field].active or candidate

                requirements = gate_config.requirements_object
                # Iteration 1 is the baseline and always applies
                is_open = (
                    i == 1
                    or not requirements
                    or requirements_met(requirements, log_data, thresholds)
                )
                states[field].apply(candidate, is_open, FIELD_CAPS[field])

        sets = states['sets'].value
        max_sets = states['maxsets'].value

        weight = states['weight'].value
        max_weight = states['maxweight'].value

        repetitions = states['repetitions'].value
        max_repetitions = states['maxrepetitions'].value

        rir = states['rir'].value
        max_rir = states['maxrir'].value

        rest = states['rest'].value
        max_rest = states['maxrest'].value

        return SetConfigData(
            slot_entry_id=slot_entry.id,
            exercise=slot_entry.exercise_id,
            type=str(slot_entry.type),
            comment=slot_entry.comment,
            sets=sets if sets is not None else 1,
            max_sets=round_value(max_sets, 1),
            weight=round_value(weight, display_rounding(slot_entry, 'weight')),
            max_weight=round_value(max_weight, display_rounding(slot_entry, 'weight'))
            if max_weight and weight and max_weight > weight
            else None,
            weight_rounding=slot_entry.weight_rounding if weight is not None else None,
            weight_unit=slot_entry.weight_unit_id if weight is not None else None,
            weight_unit_name=slot_entry.weight_unit.name
            if weight is not None and slot_entry.weight_unit is not None
            else None,
            repetitions=round_value(repetitions, display_rounding(slot_entry, 'repetitions')),
            max_repetitions=round_value(
                max_repetitions, display_rounding(slot_entry, 'repetitions')
            )
            if max_repetitions and repetitions and max_repetitions > repetitions
            else None,
            repetitions_rounding=slot_entry.repetition_rounding
            if repetitions is not None
            else None,
            repetitions_unit=slot_entry.repetition_unit_id if repetitions is not None else None,
            repetitions_unit_name=slot_entry.repetition_unit.name
            if repetitions is not None and slot_entry.repetition_unit is not None
            else None,
            rir=round_value(rir, display_rounding(slot_entry, 'rir')),
            max_rir=round_value(max_rir, display_rounding(slot_entry, 'rir'))
            if max_rir and rir and max_rir > rir
            else None,
            rest=round_value(rest, display_rounding(slot_entry, 'rest')),
            max_rest=round_value(max_rest, display_rounding(slot_entry, 'rest'))
            if max_rest and rest and max_rest > rest
            else None,
        )
