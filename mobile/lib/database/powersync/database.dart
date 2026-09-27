/*
 * This file is part of wger Workout Manager <https://github.com/wger-project>.
 * Copyright (c) 2020 - 2026 wger Team
 *
 * wger Workout Manager is free software: you can redistribute it and/or modify
 * it under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU Affero General Public License for more details.
 *
 * You should have received a copy of the GNU Affero General Public License
 * along with this program.  If not, see <http://www.gnu.org/licenses/>.
 */

import 'package:drift/drift.dart';
import 'package:drift_sqlite_async/drift_sqlite_async.dart';
import 'package:fitgains/core/language.dart';
import 'package:fitgains/core/license.dart';
import 'package:fitgains/database/converters/date_only_text_converter.dart';
import 'package:fitgains/database/converters/exercise_image_style_converter.dart';
import 'package:fitgains/database/converters/json_map_converter.dart';
import 'package:fitgains/database/converters/measurement_chart_type_converter.dart';
import 'package:fitgains/database/converters/measurement_metric_type_converter.dart';
import 'package:fitgains/database/converters/time_of_day_converter.dart';
import 'package:fitgains/database/converters/utc_datetime_converter.dart';
import 'package:fitgains/database/converters/workout_impression_converter.dart';
import 'package:fitgains/features/account/models/user_profile.dart';
import 'package:fitgains/features/exercises/models/alias.dart';
import 'package:fitgains/features/exercises/models/category.dart';
import 'package:fitgains/features/exercises/models/comment.dart';
import 'package:fitgains/features/exercises/models/equipment.dart';
import 'package:fitgains/features/exercises/models/image.dart';
import 'package:fitgains/features/exercises/models/muscle.dart';
import 'package:fitgains/features/exercises/models/video.dart';
import 'package:fitgains/features/gallery/models/image.dart';
import 'package:fitgains/features/measurements/models/measurement_category.dart';
import 'package:fitgains/features/measurements/models/measurement_entry.dart';
import 'package:fitgains/features/nutrition/models/ingredient.dart';
import 'package:fitgains/features/nutrition/models/ingredient_image.dart';
import 'package:fitgains/features/nutrition/models/ingredient_weight_unit.dart';
import 'package:fitgains/features/nutrition/models/log.dart';
import 'package:fitgains/features/nutrition/models/meal.dart';
import 'package:fitgains/features/nutrition/models/meal_item.dart';
import 'package:fitgains/features/nutrition/models/nutritional_plan.dart';
import 'package:fitgains/features/routines/models/log.dart';
import 'package:fitgains/features/routines/models/repetition_unit.dart';
import 'package:fitgains/features/routines/models/routine.dart';
import 'package:fitgains/features/routines/models/session.dart';
import 'package:fitgains/features/routines/models/weight_unit.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:material_ui/material_ui.dart' show TimeOfDay;
import 'package:powersync/powersync.dart' as ps;

import 'powersync.dart';
import 'tables/exercise.dart';
import 'tables/gallery.dart';
import 'tables/ingredient.dart';
import 'tables/language.dart';
import 'tables/license.dart';
import 'tables/measurements.dart';
import 'tables/nutrition.dart';
import 'tables/routines.dart';
import 'tables/user_profile.dart';

part 'database.g.dart';

@DriftDatabase(
  tables: [
    // Core
    LanguageTable,
    LicenseTable,
    UserProfileTable,

    // Exercises
    ExerciseTable,
    ExerciseTranslationTable,
    ExerciseAliasTable,
    ExerciseCommentTable,
    MuscleTable,
    ExerciseMuscleM2N,
    ExerciseSecondaryMuscleM2N,
    EquipmentTable,
    ExerciseEquipmentM2N,
    ExerciseCategoryTable,
    ExerciseImageTable,
    ExerciseVideoTable,

    // Measurements
    MeasurementCategoryTable,
    MeasurementEntryTable,

    // Routines
    RoutineTable,
    WorkoutLogTable,
    WorkoutSessionTable,
    RoutineRepetitionUnitTable,
    RoutineWeightUnitTable,

    // Nutrition
    NutritionalPlanTable,
    IngredientTable,
    IngredientImageTable,
    IngredientWeightUnitTable,
    MealTable,
    MealItemTable,
    LogItemTable,

    // Gallery
    GalleryImageTable,
  ],
  //include: {'queries.drift'},
)
class DriftPowersyncDatabase extends _$DriftPowersyncDatabase {
  DriftPowersyncDatabase(super.e);

  @override
  int get schemaVersion => 1;

  @override
  MigrationStrategy get migration {
    return MigrationStrategy(
      onCreate: (m) async {
        // We don't have to call createAll(), PowerSync instantiates the schema
        // for us. We can use the opportunity to create fts5 indexes though.
      },
      onUpgrade: (m, from, to) async {
        if (from == 1) {
          // await createFts5Tables(
          //   db: this,
          //   tableName: 'todos',
          //   columns: ['description', 'list_id'],
          // );
        }
      },
    );
  }
}

final driftPowerSyncDatabase = Provider((ref) {
  return DriftPowersyncDatabase(
    DatabaseConnection.delayed(
      Future(() async {
        final database = await ref.read(powerSyncInstanceProvider.future);
        return SqliteAsyncDriftConnection(database);
      }),
    ),
  );
});
