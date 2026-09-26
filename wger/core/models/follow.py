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
from django.db import models

# wger
from wger.utils.uuid import uuid7


class UserFollow(models.Model):
    """
    A follow relationship between two users of this instance (G6)

    Both sides must opt in: the follower creates the relationship, but the
    followee only shares anything if their profile has social features
    enabled (and per-session sharing on top of that).
    """

    id = models.UUIDField(
        default=uuid7,
        primary_key=True,
    )

    follower = models.ForeignKey(
        'auth.User',
        on_delete=models.CASCADE,
        related_name='following',
    )

    followee = models.ForeignKey(
        'auth.User',
        on_delete=models.CASCADE,
        related_name='followers',
    )

    created = models.DateTimeField(
        verbose_name='Creation date',
        auto_now_add=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['follower', 'followee'],
                name='unique_user_follow',
            ),
            models.CheckConstraint(
                condition=~models.Q(follower=models.F('followee')),
                name='no_self_follow',
            ),
        ]

    def clean(self):
        # Django
        from django.core.exceptions import ValidationError

        if self.follower_id and self.followee_id and self.follower_id == self.followee_id:
            raise ValidationError('Users cannot follow themselves.')

    def __str__(self):
        return f'{self.follower} follows {self.followee}'
