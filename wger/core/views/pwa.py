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
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License

"""
PWA endpoints: web manifest, service worker and Digital Asset Links.

All three must live at the site root (the manifest's scope defaults to its
URL path, and the service worker only controls URLs under its own path), so
they are views, not static files.
"""

# Standard Library
import json

# Django
from django.conf import settings
from django.contrib.staticfiles import finders
from django.contrib.staticfiles.storage import staticfiles_storage
from django.http import (
    FileResponse,
    Http404,
    HttpRequest,
    HttpResponse,
    JsonResponse,
)


def manifest(request: HttpRequest) -> JsonResponse:
    """Web app manifest — makes the site installable as a PWA."""

    def icon(name: str, size: int, purpose: str | None = None):
        entry = {
            'src': request.build_absolute_uri(staticfiles_storage.url(f'images/logos/pwa/{name}')),
            'sizes': f'{size}x{size}',
            'type': 'image/png',
        }
        if purpose:
            entry['purpose'] = purpose
        return entry

    data = {
        'name': 'FitGains',
        'short_name': 'FitGains',
        'description': 'Self-hosted fitness and workout manager',
        'start_url': '/',
        'scope': '/',
        'display': 'standalone',
        'background_color': '#ffffff',
        'theme_color': '#3e4762',
        'icons': [
            icon('pwa-192.png', 192),
            icon('pwa-512.png', 512),
            icon('pwa-maskable-192.png', 192, 'maskable'),
            icon('pwa-maskable-512.png', 512, 'maskable'),
        ],
    }
    return JsonResponse(data)


def service_worker(request: HttpRequest) -> FileResponse:
    """
    Serve the service worker from the root so it can control the whole site.

    The JS itself lives in core/static; serving it through a view also lets us
    send Service-Worker-Allowed without web-server config.
    """
    path = finders.find('sw.js')
    if path is None:
        raise Http404('service worker not found')
    response = FileResponse(open(path, 'rb'), content_type='application/javascript')
    response['Service-Worker-Allowed'] = '/'
    return response


def assetlinks(request: HttpRequest) -> HttpResponse:
    """
    Digital Asset Links for Trusted Web Activity (Android) verification.

    Configure via WGER_SETTINGS:

        ANDROID_APP_PACKAGE: 'com.example.fitgains'
        ANDROID_APP_SHA256_FINGERPRINTS: ['AA:BB:...']

    Returns an empty list when unconfigured — valid JSON, just unverified.
    """
    package = settings.WGER_SETTINGS.get('ANDROID_APP_PACKAGE')
    fingerprints = settings.WGER_SETTINGS.get('ANDROID_APP_SHA256_FINGERPRINTS', [])
    statements = []
    if package and fingerprints:
        statements = [
            {
                'relation': ['delegate_permission/common.handle_all_urls'],
                'target': {
                    'namespace': 'android_app',
                    'package_name': package,
                    'sha256_cert_fingerprints': fingerprints,
                },
            }
        ]
    return HttpResponse(json.dumps(statements), content_type='application/json')
