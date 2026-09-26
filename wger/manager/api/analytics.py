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
Analytics endpoints over the read-model aggregation layer (G2).

Thin views: filtering, bucketing and the math live in
``wger.manager.services.analytics`` — these viewsets only parse query
parameters and shape the response.
"""

# Django
from django.utils.dateparse import parse_date

# Third Party
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiTypes,
    extend_schema,
)
from rest_framework import (
    serializers,
    status,
    viewsets,
)
from rest_framework.decorators import action
from rest_framework.response import Response

# wger
from wger.manager.services.analytics import (
    GROUP_UNITS,
    ONE_RM_FORMULAS,
    InvalidGroupUnit,
    one_rm_rows,
    volume_rows,
)


class VolumeRowSerializer(serializers.Serializer):
    """One tonnage row: an exercise's volume in a bucket"""

    group = serializers.CharField()
    exercise = serializers.IntegerField()
    weight_unit = serializers.IntegerField(allow_null=True)
    volume = serializers.DecimalField(max_digits=12, decimal_places=2)
    sets = serializers.IntegerField()
    sessions = serializers.IntegerField()
    best_weight = serializers.DecimalField(max_digits=6, decimal_places=2, allow_null=True)


class OneRmRowSerializer(serializers.Serializer):
    """One 1RM row: an exercise's best estimated 1RM in a bucket"""

    group = serializers.CharField()
    exercise = serializers.IntegerField()
    weight_unit = serializers.IntegerField(allow_null=True)
    est_1rm = serializers.DecimalField(max_digits=8, decimal_places=2)
    weight = serializers.DecimalField(max_digits=6, decimal_places=2)
    repetitions = serializers.DecimalField(max_digits=6, decimal_places=2)
    date = serializers.DateField()


def parse_filters(params) -> tuple[dict, str | None]:
    """
    The shared query parameters of the analytics endpoints.

    Returns the filter dict and an error message, if any parameter was
    invalid.
    """
    filters = {}
    if exercise := params.get('exercise'):
        if not str(exercise).isdigit():
            return {}, 'exercise must be an id'
        filters['exercise'] = int(exercise)
    if routine := params.get('routine'):
        if not str(routine).isdigit():
            return {}, 'routine must be an id'
        filters['routine'] = int(routine)
    for name in ('start', 'end'):
        if value := params.get(name):
            parsed = parse_date(value)
            if parsed is None:
                return {}, f'{name} must be an ISO date (YYYY-MM-DD)'
            filters[name] = parsed
    return filters, None


class WorkoutLogAnalyticsViewSet(viewsets.ViewSet):
    """
    Aggregated workout analytics for the requesting user.

    Both endpoints share the same parameters: `group_by` selects the bucket
    (day, week, month or routine iteration), `exercise` and `routine` narrow
    the series, `start`/`end` bound it by log date. Rows never mix weight
    units — convert per row through the unit id.
    """

    # Owner-scoped: anonymous requests must be rejected, not served an
    # (empty) public series
    is_private = True

    def _group_by(self, request) -> str | None:
        group_by = request.query_params.get('group_by', 'day')
        if group_by not in GROUP_UNITS:
            return None
        return group_by

    def _error(self, message: str) -> Response:
        return Response({'detail': message}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        summary='Tonnage (volume) per exercise and bucket',
        parameters=[
            OpenApiParameter(
                'group_by',
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                description=f'Bucket unit, one of {", ".join(GROUP_UNITS)} (day by default)',
            ),
            OpenApiParameter('exercise', OpenApiTypes.INT, OpenApiParameter.QUERY),
            OpenApiParameter('routine', OpenApiTypes.INT, OpenApiParameter.QUERY),
            OpenApiParameter('start', OpenApiTypes.DATE, OpenApiParameter.QUERY),
            OpenApiParameter('end', OpenApiTypes.DATE, OpenApiParameter.QUERY),
        ],
        responses={200: VolumeRowSerializer(many=True)},
    )
    def list(self, request, *args, **kwargs):
        group_by = self._group_by(request)
        if group_by is None:
            return self._error(f'group_by must be one of: {", ".join(GROUP_UNITS)}')

        filters, error = parse_filters(request.query_params)
        if error:
            return self._error(error)

        try:
            rows = volume_rows(request.user, filters, group_by)
        except InvalidGroupUnit as exc:
            return self._error(str(exc))

        return Response(VolumeRowSerializer(rows, many=True).data)

    @extend_schema(
        summary='Best estimated 1RM per exercise and bucket',
        parameters=[
            OpenApiParameter(
                'group_by',
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                description=f'Bucket unit, one of {", ".join(GROUP_UNITS)} (day by default)',
            ),
            OpenApiParameter(
                'formula',
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                description=(
                    f'Estimation formula, one of {", ".join(ONE_RM_FORMULAS)} (epley by default)'
                ),
            ),
            OpenApiParameter('exercise', OpenApiTypes.INT, OpenApiParameter.QUERY),
            OpenApiParameter('routine', OpenApiTypes.INT, OpenApiParameter.QUERY),
            OpenApiParameter('start', OpenApiTypes.DATE, OpenApiParameter.QUERY),
            OpenApiParameter('end', OpenApiTypes.DATE, OpenApiParameter.QUERY),
        ],
        responses={200: OneRmRowSerializer(many=True)},
    )
    @action(methods=['get'], detail=False, url_path='one-rm')
    def one_rm(self, request, *args, **kwargs):
        group_by = self._group_by(request)
        if group_by is None:
            return self._error(f'group_by must be one of: {", ".join(GROUP_UNITS)}')

        formula = request.query_params.get('formula', 'epley')
        if formula not in ONE_RM_FORMULAS:
            return self._error(f'formula must be one of: {", ".join(ONE_RM_FORMULAS)}')

        filters, error = parse_filters(request.query_params)
        if error:
            return self._error(error)

        try:
            rows = one_rm_rows(request.user, filters, group_by, formula)
        except InvalidGroupUnit as exc:
            return self._error(str(exc))

        return Response(OneRmRowSerializer(rows, many=True).data)
