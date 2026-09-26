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
Full-user-data export and import (G10).

Exports every owner-scoped object of a user (routines, logs, sessions,
nutrition plans, weight entries, measurements) as a JSON document, and
imports such a document back for a (possibly different) user.

Design notes:
- Django's ``python`` serialize format is used; FKs travel as raw pks.
- References to exported models are remapped to the newly created rows;
  references to shared/catalogue models (exercises, units, languages)
  are kept as-is, so imports target the same instance or a DB with a
  compatible catalogue.
- Self-referencing FKs (WorkoutLog.next_log, Category.parent) are fixed
  in a second pass after all rows exist.
- Binary content (gallery images) is out of scope.
"""

# Standard Library
import json

# Django
from django.core import serializers
from django.db import transaction

# wger
from wger.manager.models import (
    Day,
    MaxRepetitionsConfig,
    MaxRestConfig,
    MaxRiRConfig,
    MaxSetsConfig,
    MaxWeightConfig,
    RepetitionsConfig,
    RestConfig,
    RiRConfig,
    Routine,
    SetsConfig,
    Slot,
    SlotEntry,
    WeightConfig,
    WorkoutLog,
    WorkoutSession,
)
from wger.measurements.models import (
    Category,
    Measurement,
)
from wger.nutrition.models import (
    LogItem,
    Meal,
    MealItem,
    NutritionPlan,
)


class Spec:
    """One exported model: how to filter it by owner and which field is the user FK"""

    def __init__(self, model, owner_lookup, user_field=None):
        self.model = model
        self.owner_lookup = owner_lookup
        self.user_field = user_field


EXPORT_SPEC = [
    Spec(Routine, 'user', 'user'),
    Spec(Day, 'routine__user'),
    Spec(Slot, 'day__routine__user'),
    Spec(SlotEntry, 'slot__day__routine__user'),
    Spec(WeightConfig, 'slot_entry__slot__day__routine__user'),
    Spec(MaxWeightConfig, 'slot_entry__slot__day__routine__user'),
    Spec(RepetitionsConfig, 'slot_entry__slot__day__routine__user'),
    Spec(MaxRepetitionsConfig, 'slot_entry__slot__day__routine__user'),
    Spec(SetsConfig, 'slot_entry__slot__day__routine__user'),
    Spec(MaxSetsConfig, 'slot_entry__slot__day__routine__user'),
    Spec(RestConfig, 'slot_entry__slot__day__routine__user'),
    Spec(MaxRestConfig, 'slot_entry__slot__day__routine__user'),
    Spec(RiRConfig, 'slot_entry__slot__day__routine__user'),
    Spec(MaxRiRConfig, 'slot_entry__slot__day__routine__user'),
    Spec(WorkoutSession, 'user', 'user'),
    Spec(WorkoutLog, 'user', 'user'),
    Spec(NutritionPlan, 'user', 'user'),
    Spec(Meal, 'plan__user'),
    Spec(MealItem, 'meal__plan__user'),
    Spec(LogItem, 'plan__user'),
    Spec(Category, 'user', 'user'),
    Spec(Measurement, 'category__user'),
]


def export_user_data(user) -> dict:
    """Serialize all owner-scoped rows of ``user`` into a JSON-compatible dict"""
    payload = {'version': 1, 'user': user.username, 'models': {}}
    for spec in EXPORT_SPEC:
        qs = spec.model.objects.filter(**{spec.owner_lookup: user}).order_by('pk')
        payload['models'][spec.model._meta.label] = list(serializers.serialize('python', qs))
    return payload


def _fk_fields(model):
    return {f.name: f for f in model._meta.concrete_fields if f.many_to_one}


@transaction.atomic
def import_user_data(user, payload: dict) -> dict:
    """
    Import an export payload for ``user``. Returns counts of created rows.

    Must run inside a transaction: a failure halfway leaves nothing behind.
    """
    if payload.get('version') != 1:
        raise ValueError('Unsupported export version')
    if not isinstance(payload.get('models'), dict):
        raise ValueError('Malformed export: "models" section missing')

    by_label = {spec.model._meta.label: spec for spec in EXPORT_SPEC}
    # old pk -> new instance, per model label
    pk_map: dict[str, dict] = {}
    # (model label, old pk, field name) self-FKs to fix in pass two
    deferred: list[tuple[str, object, str]] = []
    counts: dict[str, int] = {}

    for spec in EXPORT_SPEC:
        label = spec.model._meta.label
        rows = payload['models'].get(label, [])
        pk_map[label] = {}
        fk_fields = _fk_fields(spec.model)
        for row in rows:
            fields = row['fields']
            new_fields = {}
            for name, value in fields.items():
                field = fk_fields.get(name)
                if field is None:
                    new_fields[name] = value
                    continue

                if name == spec.user_field:
                    # Handled by the user_field assignment below; leaving the
                    # exported pk here would set user_id and Django's __init__
                    # would prefer the attname over the instance kwarg
                    continue

                related_label = field.related_model._meta.label
                if related_label not in by_label:
                    # Catalogue model (exercise, units, ...): keep the raw pk;
                    # assign via the concrete column so the ORM accepts an int
                    new_fields[f'{name}_id'] = value
                elif value is None:
                    new_fields[name] = None
                elif related_label == label:
                    # Self-FK, may point forward: defer to pass two
                    new_fields[name] = None
                    deferred.append((label, row['pk'], name))
                else:
                    target_map = pk_map.get(related_label, {})
                    if value not in target_map:
                        if field.null:
                            # The FK points outside the export (e.g. a session
                            # linked to a routine owned by someone else).
                            # Dangling it as NULL keeps the row; only hard-fail
                            # when the reference is required.
                            new_fields[name] = None
                            continue
                        raise ValueError(
                            f'Missing mapping for {related_label}:{value} (referenced by {label})'
                        )
                    new_fields[name] = target_map[value]

            if spec.user_field:
                new_fields[spec.user_field] = user

            # Official/typed measurement categories are unique per
            # (user, metric_type) and auto-created for users: merge into the
            # target's existing category instead of creating a duplicate.
            if spec.model is Category and fields.get('metric_type') != 'custom':
                existing = Category.objects.filter(
                    user=user, metric_type=fields.get('metric_type')
                ).first()
                if existing is not None:
                    pk_map[label][row['pk']] = existing
                    continue

            instance = spec.model(**new_fields)
            instance.save()
            pk_map[label][row['pk']] = instance

        counts[label] = len(rows)

    # Pass two: self-FKs
    rows_by_label = {
        label: {row['pk']: row for row in payload['models'].get(label, [])} for label in by_label
    }
    for label, old_pk, field_name in deferred:
        row = rows_by_label[label][old_pk]
        old_value = row['fields'][field_name]
        instance = pk_map[label][old_pk]
        setattr(instance, field_name, pk_map[label].get(old_value))
        instance.save(update_fields=[field_name])

    return counts


def export_to_json(user) -> str:
    # Django
    from django.core.serializers.json import DjangoJSONEncoder

    return json.dumps(export_user_data(user), cls=DjangoJSONEncoder)


def import_from_json(user, json_text: str) -> dict:
    return import_user_data(user, json.loads(json_text))
