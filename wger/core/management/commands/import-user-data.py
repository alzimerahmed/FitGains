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

# Django
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

# wger
from wger.core.user_data import import_from_json


class Command(BaseCommand):
    help = 'Import a user data JSON export, assigning the rows to the given user'

    def add_arguments(self, parser):
        parser.add_argument('username')
        parser.add_argument('input')

    def handle(self, *args, **options):
        user_model = get_user_model()
        try:
            user = user_model.objects.get(username=options['username'])
        except user_model.DoesNotExist:
            raise CommandError(f'User "{options["username"]}" does not exist')

        with open(options['input'], encoding='utf-8') as fp:
            counts = import_from_json(user, fp.read())

        total = sum(counts.values())
        self.stdout.write(self.style.SUCCESS(f'Imported {total} rows for {user.username}'))
        for label, count in counts.items():
            if count:
                self.stdout.write(f'  {label}: {count}')
