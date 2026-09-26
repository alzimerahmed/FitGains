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

# Django
from django.db import transaction

# Third Party
from drf_spectacular.utils import extend_schema
from rest_framework import (
    status,
    viewsets,
)
from rest_framework.decorators import action
from rest_framework.response import Response

# wger
from wger.measurements.models import (
    Category,
    Measurement,
)
from wger.weight.api.filtersets import WeightEntryFilterSet
from wger.weight.api.serializers import (
    HealthSyncItemSerializer,
    HealthSyncResultSerializer,
    WeightEntrySerializer,
)


class WeightEntryViewSet(viewsets.ModelViewSet):
    """
    API endpoint for weight entry objects
    """

    serializer_class = WeightEntrySerializer

    is_private = True
    ordering_fields = '__all__'
    filterset_class = WeightEntryFilterSet

    def get_queryset(self):
        """
        Only allow access to appropriate objects
        """
        # REST API generation
        if getattr(self, 'swagger_fake_view', False):
            return Measurement.objects.none()

        # Measurement orders by -date, the historic weight endpoint by date.
        # The id breaks ties so that paging through the entries is stable
        return Measurement.body_weight_for(self.request.user).order_by('date', 'id')

    def perform_create(self, serializer):
        """
        Route the new entry into the user's official body-weight category.
        The value is interpreted in the user's preferred weight unit.
        """
        profile = self.request.user.userprofile
        category = Category.get_or_create_body_weight(self.request.user, unit=profile.weight_unit)
        serializer.save(category=category, extra_data={'unit': profile.weight_unit})

    def perform_update(self, serializer):
        """
        A new value is interpreted in the user's current weight unit, updates
        without a value keep the stored unit.

        Only the unit key is replaced, the rest of extra_data is the provenance
        an import left there.
        """
        if 'value' in serializer.validated_data:
            unit = self.request.user.userprofile.weight_unit
            serializer.save(extra_data={**serializer.instance.extra_data, 'unit': unit})
        else:
            serializer.save()

    @extend_schema(
        summary='Bulk-upsert body-weight samples from a health platform sync',
        request=HealthSyncItemSerializer(many=True),
        responses={200: HealthSyncResultSerializer},
    )
    @action(detail=False, methods=['post'], pagination_class=None)
    def sync(self, request):
        """
        Health-platform sync surface (G3).

        Mobile clients (Health Connect / Apple Health) push batches of
        body-weight samples; each sample is upserted on its (source,
        external_id) pair, so replaying a batch never duplicates entries.
        Invalid samples are rejected individually and reported, the valid
        rest of the batch still lands.
        """
        MAX_BATCH_SIZE = 500

        items = request.data if isinstance(request.data, list) else request.data.get('samples', [])
        if not isinstance(items, list):
            return Response(
                {'detail': 'Expected a list of samples.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if len(items) > MAX_BATCH_SIZE:
            return Response(
                {'detail': f'A batch may contain at most {MAX_BATCH_SIZE} samples.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        profile = request.user.userprofile
        category = Category.get_or_create_body_weight(request.user, unit=profile.weight_unit)

        created = updated = 0
        rejected = []
        with transaction.atomic():
            for index, item in enumerate(items):
                serializer = HealthSyncItemSerializer(data=item, context={'request': request})
                if not serializer.is_valid():
                    rejected.append({'index': index, 'errors': serializer.errors})
                    continue

                data = serializer.validated_data
                _, was_created = Measurement.objects.update_or_create(
                    category=category,
                    source=data['source'],
                    external_id=data['external_id'],
                    defaults={
                        'date': data['date'],
                        'value': data['weight'],
                        'notes': data.get('notes', ''),
                        'extra_data': {'unit': profile.weight_unit, 'origin': 'health-sync'},
                    },
                )
                if was_created:
                    created += 1
                else:
                    updated += 1

        return Response(
            HealthSyncResultSerializer(
                {'created': created, 'updated': updated, 'rejected': rejected}
            ).data
        )
