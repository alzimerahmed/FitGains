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

"""
Webhook dispatch (G11)

Events are fanned out to the user's active webhooks as Celery tasks; each
delivery POSTs a JSON payload signed with the webhook's secret
(``X-Wger-Signature: sha256=<hex hmac>``) so receivers can verify it.
"""

# Standard Library
import hashlib
import hmac
import json
import logging
import uuid

# wger
from wger.core.models import (
    Webhook,
    WebhookEvent,
)


logger = logging.getLogger(__name__)

WEBHOOK_TIMEOUT_SECONDS = 10


def build_signature(secret: str, body: bytes) -> str:
    """
    The HMAC-SHA256 signature header value for a payload
    """
    digest = hmac.new(secret.encode('utf-8'), body, hashlib.sha256).hexdigest()
    return f'sha256={digest}'


def dispatch_event(user_id: int, event: str, payload: dict):
    """
    Queue a delivery task for every active webhook of the user subscribed
    to the event. Never raises: webhook problems must not break the write
    that triggered the event.
    """
    from wger.core.tasks import deliver_webhook_task

    if event not in WebhookEvent.values:
        logger.warning(f'Ignoring unknown webhook event: {event}')
        return

    # Filtered in Python, not with a JSON contains lookup: webhook counts per
    # user are tiny and the contains lookup is not portable across backends
    webhooks = [
        webhook
        for webhook in Webhook.objects.filter(user_id=user_id, is_active=True)
        if event in (webhook.events or [])
    ]
    for webhook in webhooks:
        deliver_webhook_task.delay(webhook.id, event, payload)


def deliver_webhook(webhook_id, event: str, payload: dict):
    """
    Deliver one signed payload to one webhook. Raises on failure so the
    Celery retry policy can kick in.
    """
    import requests

    webhook = Webhook.objects.get(pk=webhook_id)
    if not webhook.is_active:
        return

    body = json.dumps(
        {
            'id': str(uuid.uuid4()),
            'event': event,
            'created': payload.get('_created'),
            'data': payload,
        }
    ).encode('utf-8')

    response = requests.post(
        webhook.url,
        data=body,
        headers={
            'Content-Type': 'application/json',
            'X-Wger-Event': event,
            'X-Wger-Signature': build_signature(webhook.secret, body),
        },
        timeout=WEBHOOK_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
