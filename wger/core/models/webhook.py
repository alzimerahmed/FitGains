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
import secrets

# Django
from django.db import models

# wger
from wger.utils.uuid import uuid7


class WebhookEvent(models.TextChoices):
    """
    Events a webhook can subscribe to (G11)
    """

    WORKOUT_LOG_CREATED = 'workoutlog.created'
    WORKOUT_SESSION_CREATED = 'workoutsession.created'
    WEIGHT_CREATED = 'weight.created'


def generate_webhook_secret() -> str:
    """
    A fresh URL-safe signing secret for HMAC payloads
    """
    return secrets.token_urlsafe(32)


class Webhook(models.Model):
    """
    A user-registered HTTP endpoint that receives signed event notifications
    """

    id = models.UUIDField(
        default=uuid7,
        primary_key=True,
    )

    user = models.ForeignKey(
        'auth.User',
        on_delete=models.CASCADE,
        related_name='webhooks',
    )

    url = models.URLField(
        verbose_name='URL',
        max_length=500,
    )

    events = models.JSONField(
        verbose_name='Events',
        default=list,
        help_text='List of event names this webhook subscribes to',
    )

    secret = models.CharField(
        verbose_name='Secret',
        max_length=64,
        default=generate_webhook_secret,
        help_text='Used to sign payloads (HMAC-SHA256); shown once at creation',
    )

    is_active = models.BooleanField(
        verbose_name='Active',
        default=True,
    )

    created = models.DateTimeField(
        verbose_name='Creation date',
        auto_now_add=True,
    )

    def get_owner_object(self):
        """
        Returns the object that has owner information
        """
        return self

    def clean(self):
        from django.core.exceptions import ValidationError

        if not isinstance(self.events, list) or not self.events:
            raise ValidationError({'events': 'At least one event is required.'})
        invalid = [e for e in self.events if e not in WebhookEvent.values]
        if invalid:
            raise ValidationError({'events': f'Unknown events: {invalid}'})

    def __str__(self):
        return f'Webhook {self.url} for {self.user}'
