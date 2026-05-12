# SalesPilot — STATUS

Last updated: 2026-05-12, end of session "prospects + AI callscript build"

## Live

- URL: https://sales.hostingportal.org
- Login: `founder@hostingportal.org` / `replace-me-immediately-pls` *(placeholder — change!)*
- Demo org: `demo@example.com` / `demo-pw-long-enough`
- Brand colour: IT-Gemak cyan `#128ece` (Tailwind `brand-500`)

## What works end-to-end

- Multi-tenant CRM (RLS, app role `salespilot_app`)
- Auth, registration auto-creates a default Sales pipeline
- Companies / Contacts / Deals / Activities CRUD with search/filter/sort/pagination
- Kanban board for deals
- Dashboard with KPIs
- HaloPSA integration: read clients (421 synced), push prospect → HaloPSA, fetch quotations
- New: **Prospects** page with lead scoring, mail-platform icons, ICP-fit badges, filters
- New: **Customers** page (HaloPSA-synced + halopsa-pushed companies, baseQuery filtered)
- New: **Settings → Integrations** connector grid (HaloPSA, ProspectPRO, Anthropic + 2 coming-soon placeholders)
- New: Per-integration configure page with Save / Test / Sync now
- New: **ProspectPanel** on company detail — KPI strip, AI callscript, page-visit list, score breakdown, MX-refresh button
- New: Sidebar restructured into Overview / Pipeline / External + Settings, with live counts and brand-500 active items

## What needs operator action

1. **Plak ProspectPRO API token** in Settings → Integrations → ProspectPRO → Configure → API token. Save → Test connection → Sync now.
2. **Plak Anthropic API key** in Settings → Integrations → Anthropic (Claude) → Configure → API key. Save → Test connection. Model defaults to `claude-sonnet-4-5-20250929`.
3. **Wijzig founder-wachtwoord** (`founder@hostingportal.org`) — staat nu op een placeholder.

## Architectuur-notities

- Companies-tabel: `source ∈ {salespilot, halopsa, halopsa_pushed}`
  - `salespilot` = prospect, editable
  - `halopsa` = read-only (synced from HaloPSA)
  - `halopsa_pushed` = was prospect, geupload naar HaloPSA, editable
- Lead scoring is deterministisch transparant in `salespilot/integrations/scoring.py`; max 100, bucket hot≥80 / warm≥50 / cold. Score breakdown wordt on-demand opnieuw berekend in de ProspectPanel zodat de UI kan tonen *waarom* een score is wat 'ie is.
- Mail-platform detectie via MX-records (`dnspython`), cached in `companies.mail_platform` + `mail_platform_checked_at`. Refresh-knop op company detail.
- AI callscript via Anthropic Messages API met JSON-only output. Fallback template als key ontbreekt of call faalt → UI blijft werken. Cached in `companies.callscript_json` + `callscript_generated_at`.
- Visitor events tabel (`visitor_events`) is bron-onafhankelijk: ProspectPRO nu, Leadinfo / Google Analytics later. RLS aan, grant aan `salespilot_app`.
- ProspectPRO REST API: base `https://api.prospectpro.nl/v1`, auth via `X-Token-Auth` header. Sync trekt prospects + (per visitor-prospect) pageviews binnen.

## TODO (volgende sessie kandidaten)

- [ ] Encryptie-at-rest voor `integrations.config_json` secrets (nu plain JSONB)
- [ ] Cron-sync voor HaloPSA + ProspectPRO (nu handmatig via knop)
- [ ] `/quotations` top-level pagina (cross-company HaloPSA quotations)
- [ ] Auto-refresh lead score na nieuwe pageview-insert (nu alleen tijdens sync)
- [ ] Mailgun integratie (outbound mail vanaf prospect-detail)
- [ ] LinkedIn integratie (decision-maker enrichment)
- [ ] Pipeline-management UI, Custom fields UI, CSV import, forgot-password flow
- [ ] Postgres-backups cron
- [ ] Image pinning in compose
- [ ] Verwijder oude `/companies` route na bevestiging dat Customers+Prospects volledig dekken
