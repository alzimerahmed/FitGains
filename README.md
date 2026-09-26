# FitGains — Self-hosted fitness and workout manager

<div align="center">

<img src="FitGains%20icon.png" alt="FitGains" width="160">

[![CI](https://github.com/alzimerahmed/FitGains/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/alzimerahmed/FitGains/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)](https://www.python.org)
[![Django](https://img.shields.io/badge/Django-5.x-092E20?logo=django&logoColor=white)](https://www.djangoproject.com)
[![Docker](https://img.shields.io/badge/Docker-self--hosted-2496ED?logo=docker&logoColor=white)](https://github.com/alzimerahmed/FitGains/pkgs/container/fitgains)
[![License](https://img.shields.io/badge/License-AGPL--3.0-blue.svg)](LICENSE.txt)

*A FOSS workout, nutrition and body-tracking server you host yourself — built on the wger codebase.*

[Quick Start](#quick-start) • [Features](#features) • [Tech Stack](#tech-stack)

</div>

---

## Features

- **Custom workout routines** — flexible routines with automatic weight/rep progression rules and explainable adaptive progression suggestions.
- **Analytics** — tonnage, volume and estimated 1RM endpoints computed server-side from your workout logs.
- **Nutrition tracking** — meal plans and calorie logging backed by the [Open Food Facts](https://openfoodfacts.org) database, with barcode lookup.
- **Body weight and measurements** — daily weigh-ins, custom measurement categories, and idempotent bulk sync from Health Connect / Apple Health.
- **Progress gallery** — photo-based progress tracking.
- **Exercise wiki** — built-in, editable exercise database with muscles, equipment and categories.
- **Sharing** — routine templates, share links, and opt-in social feeds with per-session visibility.
- **Webhooks** — HMAC-signed event notifications for workout, session and weight events.
- **REST API** — versioned API (`/api/v2/`) with an OpenAPI schema, consumed by the wger Flutter mobile clients.
- **Multi-user gyms** — gym management features for trainers and gym operators.
- **Multilingual** — 20+ languages via Weblate translations.
- **Self-hostable** — one `docker compose up -d` for the full stack (server, PostgreSQL, Redis, Celery).

## Screenshots

Not yet published. Run it locally and see for yourself — the web UI is mobile-first with dark mode.

## Tech Stack

| Layer | Technology |
| --- | --- |
| Backend | Python 3.12+, Django 5.x, Django REST Framework |
| Auth | django-allauth (MFA, OIDC) + django-axes |
| Background jobs | Celery + Redis |
| Database | PostgreSQL (production), SQLite (dev) |
| Web UI | Django templates + Bootstrap 5, dark mode |
| Packaging | uv, ruff, Docker (multi-arch images) |

## Project Structure

```text
wger/
  core/          users, auth, preferences, API infra
  manager/       workout routines, schedules, logs, analytics services
  exercises/     exercise wiki + muscles/equipment/categories
  nutrition/     plans, meals, ingredients, Open Food Facts sync
  weight/        body weight log
  measurements/  custom measurements + health sync
  gallery/       progress photos
  gym/           multi-user gym management
  trophies/      achievements
  mailer/        newsletter/emails
  software/      changelog, about, API docs pages
extras/docker/   Dockerfiles (base, production, demo, development)
```

## Quick Start

```bash
git clone https://github.com/alzimerahmed/FitGains.git
cd FitGains
echo "SECRET_KEY=$(python -c 'import secrets; print(secrets.token_urlsafe(50))')" > .env
docker compose up -d
```

The web UI is then available at `http://localhost:8000` (default admin: `admin` / `adminadmin` — change it immediately).

<details>
<summary>Local development without Docker</summary>

```bash
uv sync
uv run python manage.py migrate
uv run python manage.py start-server
```

Redis is required for Celery; SQLite is used by default in development.
</details>

## Usage

Create a routine, add days and exercises with progression rules, then log your workouts —
FitGains computes tonnage and 1RM trends and suggests progression adjustments you can accept
or dismiss. Everything is also available programmatically:

```bash
curl -H "Authorization: Token <your-token>" http://localhost:8000/api/v2/workoutlog-analytics/<routine-id>/
```

## Install as an App (PWA)

FitGains is a Progressive Web App — no app store needed:

- **Android (Chrome)**: open your instance → browser menu → *Add to Home screen* / *Install app*
- **iOS (Safari)**: Share → *Add to Home Screen*
- **Desktop (Chrome/Edge)**: install icon in the address bar

### Build a real APK (optional)

Self-hosters can wrap their own instance as a Trusted Web Activity with
[Bubblewrap](https://github.com/GoogleChromeLabs/bubblewrap):

```bash
bubblewrap init --manifest https://<your-domain>/manifest.webmanifest
bubblewrap build
```

Then configure the Digital Asset Links verification by adding to your `.env`:

```bash
ANDROID_APP_PACKAGE=com.yourname.fitgains
ANDROID_APP_SHA256_FINGERPRINTS=AA:BB:CC:...   # from `bubblewrap fingerprint`
```

The server will serve it at `/.well-known/assetlinks.json`.

## FAQ / Troubleshooting

**Is this wger?** FitGains is a hard fork of [wger](https://github.com/wger-project/wger) (AGPL-3.0). It is developed independently and does not track upstream. All credit for the original codebase belongs to the wger contributors.

**Can I use the mobile apps?** Yes — FitGains is installable as a PWA from the browser (see above). The official wger Flutter apps also speak the same `/api/v2/` API and work against a FitGains instance.

## Contributing

Fork the repo, create a branch, and open a pull request. Run `ruff check` and the test suite before submitting. Translations are managed via Weblate.

## Roadmap

- [x] Analytics and adaptive progression
- [x] Routine sharing and opt-in social feed
- [x] Health Connect / Apple Health sync surface
- [x] Webhooks
- [ ] Wearables / watch apps
- [ ] AI meal-photo recognition

## Changelog

See [GitHub Releases](https://github.com/alzimerahmed/FitGains/releases).

## License

- Application Code: [AGPL-3.0-or-later](LICENSE.txt)
- Exercise/Ingredient Data: Creative Commons (see individual entries)
- Documentation: [CC-BY-SA-4.0](https://creativecommons.org/licenses/by-sa/4.0/)

FitGains is a fork of wger — copyright remains with the wger-project contributors per AGPL-3.0.
