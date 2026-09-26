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
from decimal import Decimal

# Django
from django.conf import settings
from django.core.cache import cache
from django.db.models import Q
from django.shortcuts import get_object_or_404

# Third Party
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiParameter,
    extend_schema,
)
from rest_framework import (
    status,
    viewsets,
)
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

# wger
from wger.core.models import UserFollow
from wger.manager.api.consts import BASE_CONFIG_FILTER_FIELDS
from wger.manager.api.filtersets import (
    WorkoutLogFilterSet,
    WorkoutSessionFilterSet,
)
from wger.manager.api.permissions import RoutinePermission
from wger.manager.api.plate_calculator import calculate_plates
from wger.manager.api.serializers import (
    DaySerializer,
    LogDisplaySerializer,
    LogStatsDataSerializer,
    MaxRepetitionsConfigSerializer,
    MaxRestConfigSerializer,
    MaxRiRConfigSerializer,
    MaxSetNrConfigSerializer,
    MaxWeightConfigSerializer,
    PlateCalculatorResultSerializer,
    ProgressionSuggestionSerializer,
    RepetitionsConfigSerializer,
    RestConfigSerializer,
    RiRConfigSerializer,
    RoutineSerializer,
    RoutineShareTokenSerializer,
    RoutineStructureSerializer,
    SetNrConfigSerializer,
    SlotEntrySerializer,
    SlotSerializer,
    SocialFeedSessionSerializer,
    WeightConfigSerializer,
    WorkoutDayDataDisplayModeSerializer,
    WorkoutDayDataGymModeSerializer,
    WorkoutLogSerializer,
    WorkoutSessionSerializer,
)
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
    RoutineShareToken,
    SetsConfig,
    Slot,
    SlotEntry,
    WeightConfig,
    WorkoutLog,
    WorkoutSession,
)
from wger.manager.services.copy_routine import copy_routine
from wger.manager.services.progression_suggestions import (
    progression_suggestions as build_progression_suggestions,
)
from wger.utils.cache import CacheKeyMapper
from wger.utils.viewsets import WgerOwnerObjectModelViewSet


def request_user_or_trainer_q(request):
    """
    Helper function to build a Q object for filtering objects by user or trainer.
    """
    trainer_identity_pk = request.session.get('trainer.identity', None)
    if trainer_identity_pk:
        return Q(user=request.user) | Q(user_id=trainer_identity_pk)
    return Q(user=request.user)


def cached_routine_response(request, cache_key, produce):
    """
    Shared cache-or-compute wrapper for the routine detail actions (H2).

    The viewsets stay thin: they only pass a cache key and a producer for
    the payload; caching, TTL and response shaping happen here once.
    """
    cached_data = cache.get(cache_key)
    if cached_data is not None:
        return Response(cached_data)

    out = produce()
    cache.set(cache_key, out, settings.WGER_SETTINGS['ROUTINE_CACHE_TTL'])
    return Response(out)


class RoutineViewSet(viewsets.ModelViewSet):
    """
    API endpoint for routine objects
    """

    serializer_class = RoutineSerializer
    permission_classes = [RoutinePermission]
    ordering_fields = '__all__'
    filterset_fields = (
        'name',
        'description',
        'created',
        'start',
        'end',
        'is_public',
        'is_template',
    )

    def get_queryset(self):
        """
        Only allow access to appropriate objects
        """
        # REST API generation
        if getattr(self, 'swagger_fake_view', False):
            return Routine.objects.none()

        return Routine.objects.filter(
            request_user_or_trainer_q(request=self.request) | Q(is_public=True)
        )

    def perform_create(self, serializer):
        """
        Set the owner
        """
        serializer.save(user=self.request.user)

    @extend_schema(responses={200: WorkoutDayDataDisplayModeSerializer(many=True)})
    @action(detail=True, url_path='date-sequence-display', pagination_class=None)
    def date_sequence_display_mode(self, request, pk):
        """
        Return the day sequence of the routine
        """
        return cached_routine_response(
            request,
            CacheKeyMapper.routine_api_date_sequence_display_key(pk, request.user.id),
            lambda: (
                WorkoutDayDataDisplayModeSerializer(
                    self.get_object().date_sequence,
                    many=True,
                ).data
            ),
        )

    @extend_schema(responses={200: WorkoutDayDataGymModeSerializer(many=True)})
    @action(detail=True, url_path='date-sequence-gym', pagination_class=None)
    def date_sequence_gym_mode(self, request, pk):
        """
        Return the day sequence of the routine
        """
        return cached_routine_response(
            request,
            CacheKeyMapper.routine_api_date_sequence_gym_key(pk, request.user.id),
            lambda: (
                WorkoutDayDataGymModeSerializer(self.get_object().date_sequence, many=True).data
            ),
        )

    @extend_schema(responses={200: RoutineStructureSerializer})
    @action(detail=True)
    def structure(self, request, pk):
        """
        Return the full object structure of the routine.
        """

        def produce():
            # Prefetch the tree on the permission-scoped queryset: foreign
            # routines 404 (probing resistance) and the object permission
            # check still runs for trainer/shared visibility rules
            routine = get_object_or_404(Routine.with_structure_prefetch(self.get_queryset()), pk=pk)
            self.check_object_permissions(request, routine)
            return RoutineStructureSerializer(routine).data

        return cached_routine_response(
            request,
            CacheKeyMapper.routine_api_structure_key(pk, request.user.id),
            produce,
        )

    @extend_schema(responses={200: LogDisplaySerializer(many=True)})
    @action(detail=True, url_path='logs', pagination_class=None)
    def logs(self, request, pk):
        """
        Returns the logs for the routine
        """
        return cached_routine_response(
            request,
            CacheKeyMapper.routine_api_logs(pk, request.user.id),
            lambda: LogDisplaySerializer(self.get_object().logs_display(), many=True).data,
        )

    @extend_schema(responses={200: LogStatsDataSerializer})
    @action(detail=True, url_path='stats')
    def stats(self, request, pk):
        """
        Returns the logs for the routine
        """
        return cached_routine_response(
            request,
            CacheKeyMapper.routine_api_stats(pk, request.user.id),
            lambda: LogStatsDataSerializer(self.get_object().calculate_log_statistics()).data,
        )

    @extend_schema(
        summary='Adaptive progression suggestions for the routine',
        responses={200: ProgressionSuggestionSerializer(many=True)},
    )
    @action(detail=True, url_path='progression-suggestions', pagination_class=None)
    def progression_suggestions(self, request, pk):
        """
        Explainable next-step suggestions per logged exercise slot (G7).

        Advisory only: reads the logs against the prescription, nothing is
        written. Each suggestion carries the rule that fired, the observed
        sets and a plain-language reason.
        """
        return cached_routine_response(
            request,
            CacheKeyMapper.routine_api_progression_suggestions(pk, request.user.id),
            lambda: (
                ProgressionSuggestionSerializer(
                    build_progression_suggestions(self.get_object()), many=True
                ).data
            ),
        )

    @extend_schema(
        summary="Copy the routine into the requesting user's routines",
        responses={201: RoutineSerializer},
    )
    @action(detail=True, methods=['post'], pagination_class=None)
    def copy(self, request, pk):
        """
        Make a copy of the routine for the requesting user (G5).

        Works on the user's own routines and on public templates; anything
        else is forbidden. Resolves the object directly: the object
        permission would reject non-owner writes, but copying a public
        template is an allowed write for the copier, like the web view.
        """
        routine = get_object_or_404(Routine, pk=pk)
        if routine.user != request.user and not routine.is_public:
            raise PermissionDenied('You can only copy your own routines or public templates.')

        routine_copy = copy_routine(routine, request.user)
        return Response(RoutineSerializer(routine_copy).data, status=status.HTTP_201_CREATED)

    @staticmethod
    def get_owner_objects():
        return []


class UserRoutineTemplateViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint for routine template objects
    """

    serializer_class = RoutineSerializer
    permission_classes = [RoutinePermission]
    is_private = True
    ordering_fields = '__all__'
    filterset_fields = ('name', 'description', 'created')

    def get_queryset(self):
        """
        Only allow access to appropriate objects
        """
        # REST API generation
        if getattr(self, 'swagger_fake_view', False):
            return Routine.objects.none()

        # If the current user is a trainer, also return their templates.
        return Routine.templates.filter(request_user_or_trainer_q(request=self.request))


class PublicRoutineTemplateViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint for public routine templates objects
    """

    serializer_class = RoutineSerializer
    permission_classes = [RoutinePermission]
    is_private = True
    ordering_fields = '__all__'
    filterset_fields = ('name', 'description', 'created')

    def get_queryset(self):
        """
        Only allow access to appropriate objects
        """
        return Routine.public.all()


class WorkoutSessionViewSet(WgerOwnerObjectModelViewSet):
    """
    API endpoint for workout sessions objects
    """

    serializer_class = WorkoutSessionSerializer
    is_private = True
    ordering_fields = '__all__'
    filterset_class = WorkoutSessionFilterSet

    def get_queryset(self):
        """
        Only allow access to appropriate objects
        """

        # REST API generation
        if getattr(self, 'swagger_fake_view', False):
            return WorkoutSession.objects.none()

        return WorkoutSession.objects.filter(user=self.request.user)

    # def create(self, request, *args, **kwargs):
    #     super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        """
        Set the owner
        """
        serializer.save(user=self.request.user)

    @staticmethod
    def get_owner_objects():
        """
        Return objects to check for ownership permission
        """
        return [(Routine, 'routine'), (Day, 'day')]


class WorkoutLogViewSet(WgerOwnerObjectModelViewSet):
    """
    API endpoint for workout log objects
    """

    serializer_class = WorkoutLogSerializer
    is_private = True
    ordering_fields = '__all__'
    filterset_class = WorkoutLogFilterSet

    def get_queryset(self):
        """
        Only allow access to appropriate objects
        """
        # REST API generation
        if getattr(self, 'swagger_fake_view', False):
            return WorkoutLog.objects.none()

        return WorkoutLog.objects.filter(user=self.request.user)

    def perform_create(self, serializer: WorkoutLogSerializer):
        """
        Set the owner
        """
        serializer.save(user=self.request.user)

    @staticmethod
    def get_owner_objects():
        """
        Return objects to check for ownership permission
        """
        return [
            (Routine, 'routine'),
            (WorkoutSession, 'session'),
            (SlotEntry, 'slot_entry'),
            (WorkoutLog, 'next_log'),
        ]


class RoutineDayViewSet(WgerOwnerObjectModelViewSet):
    """
    API endpoint for routine day objects
    """

    serializer_class = DaySerializer
    is_private = True
    ordering_fields = '__all__'
    filterset_fields = (
        'id',
        'routine',
        'order',
        'name',
        'description',
        'is_rest',
        'need_logs_to_advance',
    )

    def get_queryset(self):
        """
        Only allow access to appropriate objects
        """
        # REST API generation
        if getattr(self, 'swagger_fake_view', False):
            return Day.objects.none()

        return Day.objects.filter(routine__user=self.request.user)

    @staticmethod
    def get_owner_objects():
        """
        Return objects to check for ownership permission
        """
        return [(Routine, 'routine')]


class SlotViewSet(WgerOwnerObjectModelViewSet):
    """
    API endpoint for routine slot objects
    """

    serializer_class = SlotSerializer
    is_private = True
    ordering_fields = '__all__'
    filterset_fields = (
        'day',
        'order',
        'comment',
    )

    def get_queryset(self):
        """
        Only allow access to appropriate objects
        """
        # REST API generation
        if getattr(self, 'swagger_fake_view', False):
            return Slot.objects.none()

        return Slot.objects.filter(day__routine__user=self.request.user)

    @staticmethod
    def get_owner_objects():
        """
        Return objects to check for ownership permission
        """
        return [(Day, 'day')]


class SlotEntryViewSet(WgerOwnerObjectModelViewSet):
    """
    API endpoint for routine slot entry objects
    """

    serializer_class = SlotEntrySerializer
    is_private = True
    ordering_fields = '__all__'
    filterset_fields = (
        'slot',
        'exercise',
        'type',
        'repetition_unit',
        'repetition_rounding',
        'weight_unit',
        'weight_rounding',
        'order',
        'comment',
    )

    def get_queryset(self):
        """
        Only allow access to appropriate objects
        """
        # REST API generation
        if getattr(self, 'swagger_fake_view', False):
            return SlotEntry.objects.none()

        return SlotEntry.objects.filter(slot__day__routine__user=self.request.user)

    @staticmethod
    def get_owner_objects():
        """
        Return objects to check for ownership permission
        """
        return [(Slot, 'slot')]


class AbstractConfigViewSet(WgerOwnerObjectModelViewSet):
    """
    API endpoint for weight config objects
    """

    is_private = True
    ordering_fields = '__all__'
    filterset_fields = BASE_CONFIG_FILTER_FIELDS

    @staticmethod
    def get_owner_objects():
        """
        Return objects to check for ownership permission
        """
        return [(SlotEntry, 'slot_entry')]


class WeightConfigViewSet(AbstractConfigViewSet):
    """
    API endpoint for weight config objects
    """

    serializer_class = WeightConfigSerializer

    def get_queryset(self):
        """
        Only allow access to appropriate objects
        """
        # REST API generation
        if getattr(self, 'swagger_fake_view', False):
            return WeightConfig.objects.none()

        return WeightConfig.objects.filter(slot_entry__slot__day__routine__user=self.request.user)


class MaxWeightConfigViewSet(AbstractConfigViewSet):
    """
    API endpoint for max weight config objects
    """

    serializer_class = MaxWeightConfigSerializer

    def get_queryset(self):
        """
        Only allow access to appropriate objects
        """
        # REST API generation
        if getattr(self, 'swagger_fake_view', False):
            return MaxWeightConfig.objects.none()

        return MaxWeightConfig.objects.filter(
            slot_entry__slot__day__routine__user=self.request.user
        )


class RepetitionsConfigViewSet(AbstractConfigViewSet):
    """
    API endpoint for reps config objects
    """

    serializer_class = RepetitionsConfigSerializer

    def get_queryset(self):
        """
        Only allow access to appropriate objects
        """
        # REST API generation
        if getattr(self, 'swagger_fake_view', False):
            return RepetitionsConfig.objects.none()

        return RepetitionsConfig.objects.filter(
            slot_entry__slot__day__routine__user=self.request.user
        )


class MaxRepetitionsConfigViewSet(AbstractConfigViewSet):
    """
    API endpoint for max reps config objects
    """

    serializer_class = MaxRepetitionsConfigSerializer

    def get_queryset(self):
        """
        Only allow access to appropriate objects
        """
        # REST API generation
        if getattr(self, 'swagger_fake_view', False):
            return MaxRepetitionsConfig.objects.none()

        return MaxRepetitionsConfig.objects.filter(
            slot_entry__slot__day__routine__user=self.request.user
        )


class SetsConfigViewSet(AbstractConfigViewSet):
    """
    API endpoint for set config objects
    """

    serializer_class = SetNrConfigSerializer

    def get_queryset(self):
        """
        Only allow access to appropriate objects
        """
        # REST API generation
        if getattr(self, 'swagger_fake_view', False):
            return SetsConfig.objects.none()

        return SetsConfig.objects.filter(slot_entry__slot__day__routine__user=self.request.user)


class MaxSetsConfigViewSet(AbstractConfigViewSet):
    """
    API endpoint for max set config objects
    """

    serializer_class = MaxSetNrConfigSerializer

    def get_queryset(self):
        """
        Only allow access to appropriate objects
        """
        # REST API generation
        if getattr(self, 'swagger_fake_view', False):
            return MaxSetsConfig.objects.none()

        return MaxSetsConfig.objects.filter(slot_entry__slot__day__routine__user=self.request.user)


class RestConfigViewSet(AbstractConfigViewSet):
    """
    API endpoint for set config objects
    """

    serializer_class = RestConfigSerializer

    def get_queryset(self):
        """
        Only allow access to appropriate objects
        """
        # REST API generation
        if getattr(self, 'swagger_fake_view', False):
            return RestConfig.objects.none()

        return RestConfig.objects.filter(slot_entry__slot__day__routine__user=self.request.user)


class MaxRestConfigViewSet(AbstractConfigViewSet):
    """
    API endpoint for max rest config objects
    """

    serializer_class = MaxRestConfigSerializer

    def get_queryset(self):
        """
        Only allow access to appropriate objects
        """
        # REST API generation
        if getattr(self, 'swagger_fake_view', False):
            return MaxRestConfig.objects.none()

        return MaxRestConfig.objects.filter(slot_entry__slot__day__routine__user=self.request.user)


class RiRConfigViewSet(AbstractConfigViewSet):
    """
    API endpoint for set config objects
    """

    serializer_class = RiRConfigSerializer

    def get_queryset(self):
        """
        Only allow access to appropriate objects
        """
        # REST API generation
        if getattr(self, 'swagger_fake_view', False):
            return RiRConfig.objects.none()

        return RiRConfig.objects.filter(slot_entry__slot__day__routine__user=self.request.user)


class MaxRiRConfigViewSet(AbstractConfigViewSet):
    """
    API endpoint for set config objects
    """

    serializer_class = MaxRiRConfigSerializer

    def get_queryset(self):
        """
        Only allow access to appropriate objects
        """
        # REST API generation
        if getattr(self, 'swagger_fake_view', False):
            return MaxRiRConfig.objects.none()

        return MaxRiRConfig.objects.filter(slot_entry__slot__day__routine__user=self.request.user)


class PlateCalculatorViewSet(viewsets.ViewSet):
    """
    Plate calculator: returns the plates to load for a target weight.

    Pure computation, no database access. All values are in the caller's
    unit (kg or lb), the endpoint is unit-agnostic.
    """

    serializer_class = PlateCalculatorResultSerializer

    @extend_schema(
        summary='Calculate the plate layout for a target weight',
        parameters=[
            OpenApiParameter(
                'weight',
                OpenApiTypes.DECIMAL,
                OpenApiParameter.QUERY,
                required=True,
                description='Target total weight (including the bar)',
            ),
            OpenApiParameter(
                'bar',
                OpenApiTypes.DECIMAL,
                OpenApiParameter.QUERY,
                description='Bar weight, 20 by default',
            ),
            OpenApiParameter(
                'available',
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                description=(
                    'Comma-separated available plate denominations, '
                    '"25,20,15,10,5,2.5,1.25" by default'
                ),
            ),
        ],
        responses={200: PlateCalculatorResultSerializer},
    )
    def list(self, request, *args, **kwargs):
        def to_decimal(value, default=None):
            try:
                result = Decimal(value)
            except (TypeError, ValueError, ArithmeticError):
                return default
            if not result.is_finite():
                return default
            return result

        target = to_decimal(request.query_params.get('weight'))
        if target is None or target < 0:
            return Response(
                {'detail': 'A non-negative "weight" query parameter is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        bar = to_decimal(request.query_params.get('bar'), Decimal('20'))
        if bar is None or bar < 0:
            return Response(
                {'detail': '"bar" must be a non-negative number.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        raw_available = request.query_params.get('available', '25,20,15,10,5,2.5,1.25')
        if raw_available.count(',') > 64:
            return Response(
                {'detail': '"available" accepts at most 65 plate weights.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        available = [
            value
            for value in (to_decimal(v.strip()) for v in raw_available.split(','))
            if value is not None and value > 0
        ]
        if not available:
            return Response(
                {'detail': '"available" contains no valid plate weights.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        result = calculate_plates(target, bar, available)
        return Response(PlateCalculatorResultSerializer(result).data)


class RoutineShareTokenViewSet(WgerOwnerObjectModelViewSet):
    """
    API endpoint for routine share tokens (G5)

    Tokens are managed by the routine's owner; anyone holding the token
    value can then read the routine's structure without authenticating.
    """

    serializer_class = RoutineShareTokenSerializer
    is_private = True
    ordering_fields = '__all__'
    # PATCH is allowed so a leaked link can be revoked without destroying
    # the audit row; the serializer only accepts expires_at/revoked changes
    http_method_names = ['get', 'post', 'patch', 'delete', 'head', 'options']
    filterset_fields = ('routine',)

    def get_queryset(self):
        """
        Only allow access to appropriate objects
        """
        # REST API generation
        if getattr(self, 'swagger_fake_view', False):
            return RoutineShareToken.objects.none()

        return RoutineShareToken.objects.filter(routine__user=self.request.user)

    @staticmethod
    def get_owner_objects():
        """
        Return objects to check for ownership permission
        """
        return [(Routine, 'routine')]


class RoutineShareResolveView(APIView):
    """
    Read-only access to a shared routine template via its share token (G5)

    Unauthenticated by design: the token in the URL is the credential.
    Invalid, expired or revoked tokens answer 404 so links cannot be probed.
    """

    permission_classes = [AllowAny]

    @extend_schema(
        summary='Resolve a routine share token to the routine structure',
        responses={200: RoutineStructureSerializer},
    )
    def get(self, request, token):
        # routine__is_template=True: a routine that stopped being a template
        # after the token was created must not keep resolving
        share_token = (
            RoutineShareToken.objects.filter(token=token, routine__is_template=True)
            .select_related('routine')
            .first()
        )
        if share_token is None or not share_token.is_valid():
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        # Public unauthenticated endpoint: prefetch the whole structure tree,
        # a deep N+1 here would be a per-request DoS surface
        routine = Routine.with_structure_prefetch().get(pk=share_token.routine_id)
        return Response(RoutineStructureSerializer(routine).data)


class SocialFeedViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Shared-workout feed (G6)

    Returns the workout sessions the people the user follows have explicitly
    shared. Everything is opt-in on both sides: the followee must have social
    features enabled on their profile and must have marked the session as
    shared. Sessions are annotated with the owner's username.
    """

    serializer_class = SocialFeedSessionSerializer
    # The feed is personal (follow graph) — require auth like UserFollowViewSet
    # instead of answering 200 [] to anonymous probes
    permission_classes = [IsAuthenticated]

    def get_permissions(self):
        if getattr(self, 'swagger_fake_view', False):
            return [AllowAny()]
        return [permission() for permission in self.permission_classes]

    def get_queryset(self):
        # REST API generation
        if getattr(self, 'swagger_fake_view', False):
            return WorkoutSession.objects.none()

        followed_ids = UserFollow.objects.filter(follower=self.request.user).values_list(
            'followee_id', flat=True
        )
        return (
            WorkoutSession.objects.filter(
                user_id__in=followed_ids,
                is_public=True,
                user__userprofile__social_enabled=True,
            )
            .select_related('user', 'routine')
            .order_by('-datetime_start')
        )
