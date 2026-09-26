#  This file is part of wger Workout Manager <https://github.com/wger-project>.
#  Copyright (C) 2013 - 2026 wger Team
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

# Standard Library
import importlib
import logging
from decimal import Decimal
from typing import List

# Django
from django.conf import settings
from django.core.cache import cache
from django.db import models

# wger
from wger.core.models import (
    RepetitionUnit,
    WeightUnit,
)
from wger.exercises.models import Exercise
from wger.manager.config_calculations.default import (
    PROGRESSION_FIELDS,
    DefaultSetCalculations,
    _WalkState,
)
from wger.manager.consts import (
    REP_UNIT_REPETITIONS,
    WEIGHT_UNIT_KG,
)
from wger.manager.dataclasses import SetConfigData
from wger.manager.models.abstract_config import (
    MAX_COMPOUND_VALUE,
    AbstractChangeConfig,
)
from wger.utils.cache import CacheKeyMapper


class ExerciseType(models.TextChoices):
    """
    Types of exercise (set)

    This list needs to be kept in sync with the react and flutter apps:
    * public/locales/en/translation.json, src/components/WorkoutRoutines/models/SlotEntry.ts and
    * lib/l10n/app_en.arb, lib/models/workouts/slot_entry.dart
    """

    NORMAL = 'normal'
    WARMUP = 'warmup'
    DROPSET = 'dropset'
    MYO = 'myo'
    PARTIAL = 'partial'
    FORCED = 'forced'
    TUT = 'tut'
    ISO_HOLD = 'iso'
    JUMP = 'jump'


logger = logging.getLogger(__name__)


class SlotEntry(models.Model):
    """
    Set configuration for an exercise (weight, reps, etc.)
    """

    slot = models.ForeignKey(
        'Slot',
        on_delete=models.CASCADE,
        related_name='entries',
    )

    exercise = models.ForeignKey(
        Exercise,
        on_delete=models.CASCADE,
    )

    repetition_unit = models.ForeignKey(
        RepetitionUnit,
        default=REP_UNIT_REPETITIONS,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    """
    The repetition unit of a set. This can be e.g. a repetition, a minute, etc.
    """

    repetition_rounding = models.DecimalField(
        decimal_places=2,
        max_digits=4,
        default=None,
        null=True,
    )
    """
    The amount by which the repetitions will be rounded
    """

    weight_unit = models.ForeignKey(
        WeightUnit,
        verbose_name='Unit',
        default=WEIGHT_UNIT_KG,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    """
    The weight unit of a set. This can be e.g. kg, lb, km/h, etc.
    """

    weight_rounding = models.DecimalField(
        decimal_places=2,
        max_digits=4,
        default=None,
        null=True,
    )
    """
    The amount by which the weight will be rounded
    """

    order = models.PositiveIntegerField(
        blank=True,
        db_index=True,
    )

    comment = models.CharField(
        max_length=100,
        blank=True,
    )

    type = models.CharField(
        choices=ExerciseType.choices,
        max_length=10,
        default=ExerciseType.NORMAL,
        null=False,
    )

    class_name = models.CharField(
        max_length=50,
        null=True,
        blank=True,
    )
    """
    The name of a python class that will take care of the change logic.

    If this is set, all other settings will be ignored.
    """

    config = models.JSONField(
        default=None,
        null=True,
    )
    """JSON configuration field for custom behaviour"""

    # Metaclass to set some other properties
    class Meta:
        ordering = [
            'order',
            'id',
        ]

    @property
    def has_progression(self) -> bool:
        """
        Returns true if the calculated config data can change across iterations
        """
        return any(
            config.iteration != 1
            for field in PROGRESSION_FIELDS
            for config in getattr(self, f'{field}config_set').all()
        )

    def save(self, *args, **kwargs):
        """
        Save the object to the database
        """

        # For new entries add default rounding if available
        if not self.id:
            if not self.repetition_rounding:
                self.repetition_rounding = (
                    self.slot.day.routine.user.userprofile.repetitions_rounding
                )
            if not self.weight_rounding:
                self.weight_rounding = self.slot.day.routine.user.userprofile.weight_rounding

            # Auto-calculate order if not provided
            if self.order is None:
                max_order = self.slot.entries.aggregate(models.Max('order'))['order__max']
                self.order = (max_order or 0) + 1

        return super().save(*args, **kwargs)

    def get_owner_object(self):
        """
        Returns the object that has owner information
        """
        return self.slot.day.routine

    @staticmethod
    def walk_config_values(
        configs: List[AbstractChangeConfig],
        iteration: int,
        max_value: Decimal = MAX_COMPOUND_VALUE,
    ) -> Decimal | None:
        """
        Walks the configs iteration by iteration, without requirement gating,
        and returns the value at the requested iteration.

        The ungated special case of the walk in ``get_config_data``, both
        loops build on ``_WalkState``.
        """
        target = max(iteration, 1)
        by_iteration = {c.iteration: c for c in configs if c.iteration <= target}

        state = _WalkState()
        for i in range(1, target + 1):
            candidate = state.advance(by_iteration.get(i))
            if candidate is not None:
                state.apply(candidate, True, max_value)

        return state.value

    def get_config_data(self, iteration: int) -> SetConfigData:
        """
        Calculates the configuration for a given iteration of a slot entry.

        Delegates to the default progression strategy
        (``config_calculations.default.DefaultSetCalculations``) unless a
        custom class is set on the entry.
        """

        # If there are no progressions, the value will be always the same
        key = CacheKeyMapper.slot_entry_configs_key(self.pk)
        result = cache.get(key)
        if result and not self.has_progression:
            return result

        # If there is a custom class set, pass all responsibilities to it
        if self.class_name:
            try:
                module = importlib.import_module(
                    f'wger.manager.config_calculations.{self.class_name}'
                )
            except ImportError:
                raise ImportError(f'Class {self.class_name} not found')
            custom_logic = module.SetCalculations(
                iteration=iteration,
                sets_configs=self.setsconfig_set.filter(iteration__lte=iteration),
                max_sets_configs=self.maxsetsconfig_set.filter(iteration__lte=iteration),
                weight_configs=self.weightconfig_set.filter(iteration__lte=iteration),
                max_weight_configs=self.maxweightconfig_set.filter(iteration__lte=iteration),
                repetition_configs=self.repetitionsconfig_set.filter(iteration__lte=iteration),
                max_repetition_configs=self.maxrepetitionsconfig_set.filter(
                    iteration__lte=iteration
                ),
                rir_configs=self.rirconfig_set.filter(iteration__lte=iteration),
                max_rir_configs=self.maxrirconfig_set.filter(iteration__lte=iteration),
                rest_configs=self.restconfig_set.filter(iteration__lte=iteration),
                max_rest_configs=self.maxrestconfig_set.filter(iteration__lte=iteration),
                logs=self.workoutlog_set.filter(iteration__lte=iteration),
            )

            return custom_logic.calculate()

        result = DefaultSetCalculations(self, iteration).calculate()

        cache.set(
            key,
            result,
            settings.WGER_SETTINGS['ROUTINE_CACHE_TTL'],
        )

        return result
