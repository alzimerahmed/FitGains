# FitGains — Rules for AI Agents

## Project

FitGains = fork of wger-project/wger (upstream: https://github.com/wger-project/wger). FOSS self-hostable fitness & workout manager: custom workout routines with automatic progression rules, diet/nutrition tracking with Open Food Facts database, body weight + custom measurements, progress photo gallery, exercise wiki, gym management, powerful REST API, cross-platform Flutter clients consuming the API. Fully independent from upstream (history detached at fork; no code sync). Distribution: self-hosted Docker + GitHub Releases.

**License:** AGPL-3.0-or-later (inherited from wger) — keep it. AGPL requires preserving upstream copyright/attribution (wger-project contributors, AUTHORS.md, LICENSE.txt, source headers). Do NOT strip upstream copyright notices (license violation); project identity/rebranding elsewhere is fine. Network-use clause: if we offer FitGains as a hosted service, the full source (including our modifications) must be offered to its users.

**Scope:** Django REST backend + server-rendered web UI (primary), REST API consumed by mobile clients. Flutter mobile apps live in a separate upstream repo (wger-project/flutter) — not part of this codebase; API compatibility with them is a constraint, not a build target.

## Tech Stack & Conventions (inherited from upstream — do not fight it)

### Language & Tooling
- **Language**: Python >= 3.12, Django (Framework :: Django, 5.x), type-hinted where upstream does it.
- **Package manager**: `uv` (`uv.lock`, `pyproject.toml`). Install with `uv sync`; run tools via `uv run`.
- **Frontend (web)**: Django templates + Bootstrap, JS managed via `package.json` (npm), bundling via django-webpack-style loader in core/static.
- **Async/jobs**: Celery 5.6 + Redis (`wger/celery_configuration.py`, `wger/tasks.py`).
- **Formatter/linter**: ruff (configured in pyproject.toml). Format with `ruff format`, lint with `ruff check`.

### Architecture & Conventions
- **Apps by domain**: `wger/core` (users, auth, preferences, API infra, powersync), `wger/manager` (workout routines, schedules, logs), `wger/exercises` (exercise wiki + muscles/equipment/categories), `wger/nutrition` (plans, meals, ingredients, OFF integration), `wger/weight`, `wger/measurements`, `wger/gallery`, `wger/gym` (multi-user gym management), `wger/trophies`, `wger/mailer`, `wger/software` (changelog/about).
- **Per-app layout**: `models/` (package, one module per model), `views/`, `api/` (DRF viewsets + serializers), `migrations/`, `tests/`, `fixtures/`, `templates/`, `static/`.
- **API**: Django REST Framework, per-app `api/` with viewsets + serializers; API v2 under `/api/v2/`; OpenAPI schema generated. Any new endpoint must be added to the schema — mobile clients depend on it.
- **Auth**: django-allauth (MFA, OIDC) + django-axes (lockouts). Never bypass the auth stack.
- **Settings**: layered — `settings/main.py` + `settings_global.py`, env via django-environ; `settings/local_dev.py` and `settings/ci.py` for environments. Never hardcode env-specific values.
- **i18n**: Django i18n, translations in `wger/locale/` (Weblate-managed, 20+ languages). Never hardcode user-visible strings; wrap in gettext.
- **Background work**: anything slow (email, OFF sync, exports) goes through Celery tasks in the app's `tasks.py`.

### Database
- **Database**: PostgreSQL in production; SQLite acceptable for local dev/tests. Migrations are the data-loss hotspot — never edit an applied migration destructively; generate with `uv run python manage.py makemigrations <app>` and review.
- **Cache/queues**: Redis (cache + Celery broker).

## Build / Verify

```bash
uv sync                                          # install deps
uv run python manage.py migrate                  # apply migrations
uv run python manage.py start-server             # dev server (upstream helper)
uv run ruff check . && uv run ruff format --check .   # lint + format
uv run python manage.py test                     # full test suite
```

**Remote-first verification:** full gates on CI (GitHub Actions, `.github/workflows/ci.yml`), not local. Local tiered: targeted `manage.py test wger.<app>` while iterating → `ruff check` + scoped tests before commit → CI before merge. Do NOT run full builds/test suites locally unless debugging the build itself — we run tests in GitHub Actions when we push.

**IMPORTANT — small-batch commands:** one task per invocation; scoped tests > whole-suite runs while iterating. First `uv sync` and full test runs are slow → background + poll.

## Gotchas

- **Migrations are the data-loss hotspot**: review generated migrations, never ship destructive model edits without a data migration path.
- **AGPL-3.0 obligations**: keep LICENSE.txt + AUTHORS.md + upstream copyright. Fork must stay open-source; hosted instances owe source to users.
- **API is a public contract**: third-party apps and the Flutter clients consume `/api/v2/`. Breaking changes need a version bump strategy, not silent edits.
- **Powersync**: `wger/core/powersync.py` — offline-sync infrastructure; treat as sensitive.
- **Weblate translations**: `wger/locale/` is managed externally; don't hand-edit translation catalogs except for source string changes.
- **Docker/extras**: deployment lives in `extras/docker/`; keep self-hosting path working — it is the primary distribution.
- **Upstream demo data**: `wger/core/demo.py` + fixtures seed a demo user; keep demo flow functional.

## Agent Guidelines & Constraints

### Do's
- **Follow the per-app layout** (models/, views/, api/, tests/ per domain app) and existing naming (`*ViewSet`, `*Serializer`, model names matching upstream).
- **Wrap strings in gettext**; add new messages for translation.
- **Offload slow work to Celery tasks**, never in-request.
- **Keep ruff clean**; match upstream type-hinting style.
- **Write tests** in the app's `tests/` package for new models/endpoints.
- **Respect the settings layering**; new config goes through django-environ.

### Don'ts
- **NO breaking API changes** to `/api/v2/` without an explicit ADR in `docs/research.md`.
- **NO hardcoded strings, URLs, or credentials**; no secrets in code — env only.
- **NO destructive migrations** without a migration/backup path.
- **NO new heavy dependencies** without a decision record (license must stay AGPL-compatible).
- **NO stripping upstream attribution** (AGPL).

## Agent Guidelines & Workflow (this repo's .devin system)

### Resource Discipline (mandatory, non-trivial tasks)
Before any non-trivial task:
1. Read `docs/toolset.md` intent-map (task type → resources)
2. Invoke every skill + sub-agent in that row
3. Read every rule for that task type (`.devin/rules/`)
4. At task end: `code-reviewer` sub-agent on final diff (non-negotiable)
5. Append learnings via `/ce-compound` if durable lesson

Phase implementations (task completes a docs/plan.md row): follow `.devin/prompt/phase.md`.

Skip all this for single-line edits, pure Q&A, reading files.

### Project-Type Filter (Django fitness server)
Per `docs/toolset.md` intent-map:
- **Skip mobile/web-SPA-only:** pwa-engineer, playwright-design-clone, css-architect (Bootstrap templates only), pixel-analyst.
- **Keep universal:** code-reviewer, debugger, test-engineer, security-auditor (auth, MFA, self-hosting = security-critical), performance-engineer, git-master, migration-specialist, docs-writer, i18n-specialist, build-optimizer, caveman-compressor, vibe-coding-auditor, type-safety-engineer, database-engineer (Postgres/Django ORM), state-manager (server state/Celery), backend-architect, email-engineer (mailer app), file-handler (gallery uploads), search-architect (exercise/food search), analytics-engineer (opt-in only).
- **Quality gates:** `ruff check`, `ruff format --check`, `manage.py test` — run scoped locally, full suite in CI. No browser tooling required.

## Communication Style

Default **caveman-lite** (lightly compressed, readable, technically accurate). `/caveman` skill for full/ultra/wenyan modes.

## Quick Task Flow

Quick tasks: `.devin/prompt/quick.md` (commandments) + `.devin/prompt/rules.md` (scoping, verification, escalation). Phased work: `.devin/prompt/phase.md`.

## Key References

- `docs/toolset.md` — intent map (task type → skills, sub-agents, rules)
- `docs/plan.md` — phased plan + status
- `docs/project.md` — project state/structure
- `docs/tools-log.md` — .devin resources invoked per session
- `docs/CONCEPTS.md` — project vocabulary
- `docs/research.md` — research, ADRs, gotchas, open questions
- `docs/idea.md` — competitive analysis + Feature Gap List
- Upstream docs — https://wger.de and https://github.com/wger-project/wger for feature reference (no code sync)
