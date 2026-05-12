# Architecture

## Goals

- Multi-tenant SaaS sales platform.
- Strong tenant isolation without per-tenant tables.
- Fast iteration on data model (custom fields via JSONB).
- "Dev = prod" container layout: same compose schema, different overrides.

## Multi-tenancy

We use **shared schema with `org_id`** on every tenant-scoped table.

Why not schema-per-tenant or database-per-tenant?

- Migrations become operationally painful at scale (must run on every
  schema/db).
- Sharing reference data and cross-tenant features (admin, billing) becomes
  awkward.
- The shared-schema model scales fine to hundreds of thousands of tenants
  and is what HubSpot, Pipedrive, Close, and most modern CRMs do.

### Isolation, two layers

**Application layer.** Every API request that operates inside an organization
is served by a tenant-scoped SQLAlchemy session (`tenant_session(org_id)` in
`db.py`). The session sets the Postgres GUC `app.current_org_id` for the
duration of the transaction. Queries naturally filter by `org_id`.

**Database layer.** Row Level Security policies on every tenant-scoped table
restrict visible rows to those whose `org_id` matches the GUC. If a future
bug forgets the `WHERE org_id = …` clause, the database still hides the
rows.

The migration uses `ALTER TABLE ... FORCE ROW LEVEL SECURITY` so RLS applies
even to the database owner (our app connects as `salespilot`, which is the
owner).

Endpoints in `/auth` deliberately use the **non-tenant** `raw_session()` —
they need to look users up before there is an active org. They must filter
manually.

## Auth

V1 supports two flows that share infrastructure:

1. **Email + password.** Argon2id-hashed passwords stored on `users`.
2. **Magic link.** `URLSafeTimedSerializer` produces a signed token bound
   to an email and a TTL. Verification swaps it for a JWT pair.

Successful auth issues:

- An **access token** (JWT, HS256) with `sub` (user_id), `org` (current org)
  and `exp`. TTL: `JWT_TTL_MINUTES` (default 60).
- A **refresh token** (JWT, HS256) with `sub` and `type=refresh`. TTL:
  `JWT_REFRESH_TTL_DAYS` days.

SSO (Google, Microsoft) is on the roadmap but not in v1.

## Repo / runtime layout

```
salespilot/                                 ← this repo
  apps/api/    FastAPI                       ← built to salespilot-api image
  apps/web/    React + Vite                  ← built to salespilot-web image
  docker-compose.yml                         ← production stack
  docker-compose.override.yml                ← dev only (auto-merged)

Host (production):
  /opt/salespilot/
    compose/caddy/                            ← reverse proxy + TLS
    compose/data/                             ← postgres + redis
    compose/portainer/                        ← container management UI
    config/, data/, secrets/, backups/
```

The application stack (this repo) joins the host's external Docker network
`salespilot` and reaches Postgres/Redis/Caddy by container name on that
network. Compose-level dependencies between repos are deliberately loose:
each stack starts independently and the app retries DB/Redis until ready.

## Caddy routing (prod)

```
https://sales.hostingportal.org/api/*   →  reverse_proxy api:8000
https://sales.hostingportal.org/*       →  reverse_proxy web:80
```

The `web` container in production is a tiny `caddy:2-alpine` that serves
the SPA build with `try_files {path} /index.html` for client-side routing.

## What this document doesn't cover yet

- Background jobs / scheduled tasks. arq + Redis is the planned approach.
- Email sending strategy (transactional + bulk).
- Audit log / "what changed when by whom".
- File uploads (avatars, attachments).
- Webhooks out.
- Public API tokens.

These will get their own short ADR-style docs in `docs/` as they land.
