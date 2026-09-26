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

User-supplied webhook URLs are an SSRF vector on multi-user instances, so
they are validated twice: at registration time and again at delivery time
(DNS can change between the two). Only https to public hosts is allowed.
"""

# Standard Library
import hashlib
import hmac
import ipaddress
import json
import logging
import socket
import uuid
from urllib.parse import urlparse

# Django
from django.core.exceptions import ValidationError
from django.utils import timezone

# wger
from wger.core.models import (
    Webhook,
    WebhookEvent,
)


logger = logging.getLogger(__name__)

WEBHOOK_TIMEOUT_SECONDS = 10


class WebhookUrlError(ValidationError):
    """
    The webhook URL points somewhere we refuse to deliver to
    """


def validate_webhook_url(url: str):
    """
    Reject webhook URLs that could reach internal infrastructure (SSRF).

    Only https is accepted, and every address the hostname resolves to must
    be public. Called at registration time and again on every delivery,
    because DNS between the two is not guaranteed to agree.
    """
    parsed = urlparse(url)
    if parsed.scheme != 'https':
        raise WebhookUrlError('Webhook URLs must use https.')
    if not parsed.hostname:
        raise WebhookUrlError('Webhook URLs need a hostname.')

    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(parsed.hostname, None)}
    except OSError as e:
        raise WebhookUrlError(f'Cannot resolve webhook host: {parsed.hostname}') from e

    for address in addresses:
        ip = ipaddress.ip_address(address)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise WebhookUrlError('Webhook hosts must resolve to public addresses.')


def build_signature(secret: str, body: bytes) -> str:
    """
    The HMAC-SHA256 signature header value for a payload
    """
    digest = hmac.new(secret.encode('utf-8'), body, hashlib.sha256).hexdigest()
    return f'sha256={digest}'


def dispatch_event(user_id: int, event: str, payload: dict):
    """
    Queue a delivery task for every active webhook of the user subscribed
    to the event.

    Callers wrap this in their own try/except: the broker connection
    (``.delay``) can be down, and webhook problems must never break the
    write that triggered the event.
    """
    # wger
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
    # Third Party
    import requests

    try:
        webhook = Webhook.objects.get(pk=webhook_id)
    except Webhook.DoesNotExist:
        # Deleted between queueing and delivery; retrying cannot bring it back
        logger.info(f'Webhook {webhook_id} vanished before delivery, skipping')
        return

    if not webhook.is_active:
        return

    # DNS may have changed since registration; re-check before every POST
    try:
        validate_webhook_url(webhook.url)
    except WebhookUrlError:
        logger.warning(f'Webhook {webhook.id} URL no longer passes the SSRF check, skipping')
        return

    body = json.dumps(
        {
            'id': str(uuid.uuid4()),
            'event': event,
            'created': timezone.now().isoformat(),
            'data': payload,
        }
    ).encode('utf-8')

    # allow_redirects=False: a redirect could bounce the signed payload to
    # an internal host that the URL check never saw
    response = requests.post(
        webhook.url,
        data=body,
        headers={
            'Content-Type': 'application/json',
            'X-Wger-Event': event,
            'X-Wger-Signature': build_signature(webhook.secret, body),
        },
        timeout=WEBHOOK_TIMEOUT_SECONDS,
        allow_redirects=False,
    )
    response.raise_for_status()
