# SalesPilot

A lean, multi-tenant sales platform. Inspired by HubSpot, stripped of bloat.

## Stack

- **Backend:** Python 3.13 + FastAPI + SQLAlchemy 2.x (async) + Alembic
- **Frontend:** React 19 + Vite + TypeScript + TanStack Query + Tailwind
- **Data:** PostgreSQL 17 (Row Level Security for tenant isolation), Redis 7
- **Reverse proxy / TLS:** Caddy with Let's Encrypt
- **Container runtime:** Docker + Docker Compose

## Architecture

Multi-tenant **shared schema** model: all tenants share the same tables, every
row carries an `org_id`. Postgres Row Level Security (RLS) enforces tenant
isolation at the database level as a defence-in-depth second layer on top of
application-level filtering. See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Repo layout

```
apps/
  api/    FastAPI service (the backend)
  web/    React + Vite SPA (the frontend)
docs/     Architecture and operational notes
```

## Local development

```bash
cp .env.example .env
# edit .env with your local values

docker compose up -d
# api:   http://localhost:8000
# web:   http://localhost:5173
# db:    localhost:5432 (only when override exposes it)
```

The `docker-compose.override.yml` adds dev-only conveniences (hot reload,
exposed DB port, debug logs). It is loaded automatically by `docker compose`.

## Production deployment

This repo runs on a host where supporting infrastructure (Postgres, Redis,
Caddy) is managed in separate compose stacks under `/opt/salespilot/compose/`.
The application stack here connects to those over the external Docker network
`salespilot`. See `docs/DEPLOY.md` for the host setup.

## License

TBD.
