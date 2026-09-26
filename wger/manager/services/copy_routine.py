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

# Standard Library
import copy
import datetime
from typing import List

# Django
from django.contrib.auth.models import User
from django.db import transaction

# wger
from wger.manager.models import (
    AbstractChangeConfig,
    Routine,
    SlotEntry,
)


def copy_routine(routine: Routine, user: User) -> Routine:
    """
    Make a copy of a routine for the given user.

    The copy starts today, is neither a template nor public, and carries
    copies of all days, slots, slot entries and their change configs.

    The whole copy is one transaction: a failure halfway through must not
    leave a half-built routine behind.
    """
    with transaction.atomic():
        return _copy_routine(routine, user)


def _copy_routine(routine: Routine, user: User) -> Routine:
    routine_copy: Routine = copy.copy(routine)
    routine_copy.pk = None
    routine_copy.created = None
    routine_copy.user = user
    routine_copy.is_template = False
    routine_copy.is_public = False

    # Update the start and end date
    routine_copy.start = datetime.date.today()
    routine_copy.end = routine_copy.start + routine.duration

    routine_copy.save()

    # Copy the days
    for day in routine.days.all():
        day_copy = copy.copy(day)
        day_copy.pk = None
        day_copy.routine = routine_copy
        day_copy.save()

        # Copy the slots
        for current_slot in day.slots.all():
            slot_copy = copy.copy(current_slot)
            slot_copy.pk = None
            slot_copy.day = day_copy
            slot_copy.save()

            # Copy the slot entries
            for current_entry in current_slot.entries.all():
                slot_entry_copy = copy.copy(current_entry)
                slot_entry_copy.pk = None
                slot_entry_copy.slot = slot_copy
                slot_entry_copy.save()

                copy_config(current_entry.weightconfig_set.all(), slot_entry_copy)
                copy_config(current_entry.maxweightconfig_set.all(), slot_entry_copy)

                copy_config(current_entry.repetitionsconfig_set.all(), slot_entry_copy)
                copy_config(current_entry.maxrepetitionsconfig_set.all(), slot_entry_copy)

                copy_config(current_entry.rirconfig_set.all(), slot_entry_copy)
                copy_config(current_entry.maxrirconfig_set.all(), slot_entry_copy)

                copy_config(current_entry.restconfig_set.all(), slot_entry_copy)
                copy_config(current_entry.maxrestconfig_set.all(), slot_entry_copy)

                copy_config(current_entry.setsconfig_set.all(), slot_entry_copy)
                copy_config(current_entry.maxsetsconfig_set.all(), slot_entry_copy)

    return routine_copy


def copy_config(configs: List[AbstractChangeConfig], slot_entry: SlotEntry):
    for config in configs:
        config_copy = copy.copy(config)
        config_copy.pk = None
        config_copy.slot_entry = slot_entry
        config_copy.save()
