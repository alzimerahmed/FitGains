# -*- coding: utf-8 -*-

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

# Third Party
from rest_framework import serializers

# wger
from wger.measurements.limits import (
    VALUE_DECIMAL_PLACES,
    VALUE_MAX_DIGITS,
    limits_for,
)
from wger.measurements.models import Measurement
from wger.measurements.models.category import MetricType
from wger.measurements.models.measurement import MeasurementSource


class WeightEntrySerializer(serializers.ModelSerializer):
    """
    Weight serializer
    """

    user = serializers.PrimaryKeyRelatedField(source='category.user', read_only=True)
    weight = serializers.DecimalField(
        source='value',
        max_digits=VALUE_MAX_DIGITS,
        decimal_places=VALUE_DECIMAL_PLACES,
    )

    class Meta:
        model = Measurement
        fields = (
            'id',
            'date',
            'weight',
            'user',
        )

    def validate_weight(self, value):
        """
        The same bounds a body weight measurement has, in the profile unit.

        Values are read and written in the unit of the user profile, so that is
        the unit the bounds are resolved in: 350 kg and 770 lb are the same
        limit, a single span covering both would allow 550 kg as readily as
        550 lb (wger-project/wger#1019).
        """
        unit = self.context['request'].user.userprofile.weight_unit
        limits = limits_for(MetricType.BODY_WEIGHT, unit)

        if not limits.min <= value <= limits.max:
            raise serializers.ValidationError(
                f'Weight must be between {limits.min} and {limits.max} {unit}'
            )
        return value

    def to_representation(self, instance):
        """
        Weight values are returned in the user's preferred weight unit,
        entries themselves may be stored in other units
        """
        data = super().to_representation(instance)
        unit = self.context['request'].user.userprofile.weight_unit
        data['weight'] = self.fields['weight'].to_representation(instance.value_in(unit))
        return data


class HealthSyncItemSerializer(serializers.Serializer):
    """
    One body-weight sample pushed by a health platform sync (G3)

    ``external_id`` is the sample's identity on the source platform; resending
    the same (source, external_id) pair updates in place, making the sync
    idempotent.
    """

    external_id = serializers.UUIDField()
    date = serializers.DateTimeField()
    weight = serializers.DecimalField(
        max_digits=VALUE_MAX_DIGITS,
        decimal_places=VALUE_DECIMAL_PLACES,
    )
    source = serializers.ChoiceField(choices=(MeasurementSource.GOOGLE, MeasurementSource.APPLE))
    notes = serializers.CharField(required=False, allow_blank=True, max_length=100)

    def validate_weight(self, value):
        unit = self.context['request'].user.userprofile.weight_unit
        limits = limits_for(MetricType.BODY_WEIGHT, unit)
        if not limits.min <= value <= limits.max:
            raise serializers.ValidationError(
                f'Weight must be between {limits.min} and {limits.max} {unit}'
            )
        return value


class HealthSyncResultSerializer(serializers.Serializer):
    """
    Outcome summary of a health sync batch (G3)
    """

    created = serializers.IntegerField()
    updated = serializers.IntegerField()
    rejected = serializers.ListField(child=serializers.DictField(), required=False)
