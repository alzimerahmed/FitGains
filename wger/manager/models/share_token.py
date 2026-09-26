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
import uuid

# Django
from django.db import models
from django.utils import timezone

# wger
from wger.utils.uuid import uuid7


class RoutineShareToken(models.Model):
    """
    A share link for a routine template

    Anyone holding the token can read the routine's structure (G5). The
    routine must be a template for a token to be created; revoking or
    deleting the token immediately invalidates the link.
    """

    id = models.UUIDField(
        default=uuid7,
        primary_key=True,
    )

    routine = models.ForeignKey(
        'Routine',
        on_delete=models.CASCADE,
        related_name='share_tokens',
    )

    token = models.UUIDField(
        verbose_name='Token',
        default=uuid.uuid4,
        unique=True,
        editable=False,
    )

    created = models.DateTimeField(
        verbose_name='Creation date',
        auto_now_add=True,
    )

    expires_at = models.DateTimeField(
        verbose_name='Expiry date',
        null=True,
        blank=True,
        help_text='After this point the link stops resolving. Empty means it never expires.',
    )

    revoked = models.BooleanField(
        verbose_name='Revoked',
        default=False,
        help_text='Revoked links stop resolving but are kept for auditing.',
    )

    def get_owner_object(self):
        """
        Returns the object that has owner information
        """
        return self.routine

    def is_valid(self) -> bool:
        """
        Whether the link can currently be used to read the routine
        """
        if self.revoked:
            return False
        if self.expires_at is not None and self.expires_at <= timezone.now():
            return False
        return True

    def __str__(self):
        return f'Share token for {self.routine}'
