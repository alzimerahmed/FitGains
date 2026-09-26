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
Routine log statistics (H2).

The body of ``Routine.calculate_log_statistics`` lives here so the model
stays a thin delegate and the statistics logic is testable and evolvable
independently of the ORM model.
"""

# Standard Library
import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

# wger
from wger.exercises.models import Exercise
from wger.manager.dataclasses import (
    GroupedLogData,
    LogData,
    RoutineLogData,
)
from wger.manager.helpers import brzycki_intensity


if TYPE_CHECKING:
    # wger
    from wger.manager.models import Routine


def calculate_log_statistics(routine: 'Routine') -> RoutineLogData:
    """
    Calculates various statistics for the routine based on the logged workouts.

    Returns:
        RoutineLogData: An object containing the calculated statistics.
    """
    result = RoutineLogData()
    intensity_counter = GroupedLogData()

    def update_grouped_log_data(
        entry: GroupedLogData,
        date: datetime.date,
        week_nr: int,
        iter: int,
        exercise: Exercise,
        value: Decimal | int | None,
    ):
        """
        Updates grouped log data

        This method just adds the value to the corresponding entries
        """
        if value is None:
            return

        muscles = exercise.muscles.all()

        entry.daily[date].exercises[exercise.id] += value
        entry.weekly[week_nr].exercises[exercise.id] += value
        entry.iteration[iter].exercises[exercise.id] += value
        entry.mesocycle.exercises[exercise.id] += value

        entry.daily[date].total += value
        entry.weekly[week_nr].total += value
        entry.iteration[iter].total += value
        entry.mesocycle.total += value

        for muscle in muscles:
            pk = muscle.id

            entry.daily[date].muscle[pk] += value
            entry.weekly[week_nr].muscle[pk] += value
            entry.iteration[iter].muscle[pk] += value
            entry.mesocycle.muscle[pk] += value

    def safe_divide(numerator, denominator):
        return numerator / denominator if denominator != 0 else numerator

    def avg_log_data(data: LogData, count: LogData) -> None:
        data.total = safe_divide(data.total, count.total)
        data.upper_body = safe_divide(data.upper_body, count.upper_body)
        data.lower_body = safe_divide(data.lower_body, count.lower_body)
        for k in data.muscle:
            data.muscle[k] = safe_divide(data.muscle[k], count.muscle[k])
        for k in data.exercises:
            data.exercises[k] = safe_divide(data.exercises[k], count.exercises[k])

    def calculate_average_intensity(result: GroupedLogData, counters: GroupedLogData) -> None:
        avg_log_data(result.mesocycle, counters.mesocycle)

        for res_group, cnt_group in (
            (result.daily, counters.daily),
            (result.weekly, counters.weekly),
            (result.iteration, counters.iteration),
        ):
            for key in res_group:
                avg_log_data(res_group[key], cnt_group[key])

    # Iterate over each workout session associated with the routine
    tz = routine.user.userprofile.zone_info
    for session in routine.sessions.all():
        session_date = session.local_day_in(tz)
        week_number = session_date.isocalendar().week

        # TODO: filter for lb
        for log in session.logs.kg().reps():
            iteration = log.iteration
            exercise = log.exercise
            weight = log.weight
            reps = log.repetitions

            values_not_none = reps is not None and weight is not None
            exercise_volume = weight * reps if values_not_none else 0

            update_grouped_log_data(
                entry=result.volume,
                iter=iteration,
                week_nr=week_number,
                date=session_date,
                exercise=exercise,
                value=exercise_volume,
            )

            # Each log always corresponds to one set
            update_grouped_log_data(
                entry=result.sets,
                iter=iteration,
                week_nr=week_number,
                date=session_date,
                exercise=exercise,
                value=1,
            )

            if values_not_none:
                update_grouped_log_data(
                    entry=intensity_counter,
                    iter=iteration,
                    week_nr=week_number,
                    date=session_date,
                    exercise=exercise,
                    value=1,
                )

                update_grouped_log_data(
                    entry=result.intensity,
                    iter=iteration,
                    week_nr=week_number,
                    date=session_date,
                    exercise=exercise,
                    value=brzycki_intensity(weight, reps),
                )

    calculate_average_intensity(result.intensity, intensity_counter)

    return result
