# SalesPilot — STATUS

Last updated: 2026-05-12 (autopilot sessie)

## Live

- URL: https://sales.hostingportal.org
- Login: `founder@hostingportal.org` / `replace-me-immediately-pls` *(placeholder — wijzigen!)*
- Demo org: `demo@example.com` / `demo-pw-long-enough`
- Brand: IT-Gemak cyan `#128ece` (Tailwind `brand-500`)

## Werkt end-to-end

- Multi-tenant CRM met RLS, app role `salespilot_app`
- Auth + registratie auto-creates default Sales pipeline
- Companies / Contacts / Deals / Activities CRUD, search/filter/sort/pagination
- Kanban board voor deals
- Dashboard met KPIs
- **HaloPSA**: read clients (421 synced), push prospect → HaloPSA, fetch quotations
- **ProspectPRO**: connected, sync werkt
- **Prospects**: lead scoring, mail-platform icons, ICP-fit badges, filters
- **Customers**: HaloPSA-synced + halopsa-pushed companies
- **Settings → Integrations** connector grid (HaloPSA, ProspectPRO, Anthropic, Mailgun, LinkedIn)
- **ProspectPanel** op company detail: KPI strip, AI callscript, page-visit list, score breakdown, MX-refresh
- **Sidebar** secties: Overview / Pipeline / Outreach / External + Settings
- **Sequences (NEW)**: drie default campaigns geseed:
  - Hot — 24h personal outreach (1 mail, status=draft)
  - Warm — 3-step drip (mail → 5d → mail 2 → 7d → mail 3, status=draft)
  - Cold — slow nurture (1 mail, status=draft)
- **LinkedIn (NEW)**: outreach-kanban (To do / Sent / Connected / Replied), Posts tab skelet
- **Autopilot tick (NEW)**: cron `*/5 * * * *` op host roept `/internal/autopilot/tick` aan met internal token. Token in `/opt/salespilot/secrets/autopilot.env` (chmod 600)
- **Mailgun webhooks (NEW)**: `/api/v1/webhooks/mailgun` (events) + `/api/v1/webhooks/mailgun-inbound` (replies) — signature-verified, geen auth-header

## Wat jij nu doet

1. **Mailgun-account** opzetten + sending-domain `mail.it-gemak.nl` verifieren (SPF, DKIM, DMARC)
2. **MX-record** voor inbound: route `mail.it-gemak.nl` MX naar Mailgun's mxa.mailgun.org / mxb.mailgun.org als je replies wil ontvangen
3. **Webhooks koppelen in Mailgun**:
   - Events: `https://sales.hostingportal.org/api/v1/webhooks/mailgun` (delivered, opened, bounced, complained, unsubscribed)
   - Inbound route → `https://sales.hostingportal.org/api/v1/webhooks/mailgun-inbound` met match recipient `^.*@mail\.it-gemak\.nl$`
4. **Mailgun-key** plakken in Settings → Integrations → Mailgun → Configure
   - Domain: `mail.it-gemak.nl`
   - API key: jouw Mailgun Domain Sending key
   - Webhook signing key: jouw Mailgun HTTP webhook signing key
   - Default from name + email naar de virtuele naam die je gebruikt
5. **Sequence activeren**: ga naar Sequences → kies een (begin met Warm) → Save met status `active`
6. **Anthropic-key** plakken (Settings → Integrations → Anthropic) zodra je een account hebt — nodig voor de AI callscript

## Architectuur-notities

- Companies-tabel: `source ∈ {salespilot, halopsa, halopsa_pushed}`
- Lead scoring: deterministisch transparant in `integrations/scoring.py`, max 100, bucket hot≥80 / warm≥50 / cold
- Mail-platform: MX-lookup via dnspython, cached + refresh-knop
- AI callscript: Anthropic Messages API, JSON-only, fallback template als key ontbreekt
- Visitor events: bron-onafhankelijk, RLS aan
- Sequences:
  - Tabellen `sequences`, `sequence_steps`, `enrollments`, `messages`, `linkedin_tasks`, `mail_suppression`, `linkedin_posts`
  - Auto-enrollment loopt enkel voor sequences met `status='active'` en `auto_enroll_bucket` gevuld
  - `score_at_enroll` + `bucket_at_enroll` worden opgeslagen — bucket-evaluatie staat stil zodra geenrolleerd ("frozen")
  - Stopt op reply, unsubscribe, of handmatige stop
  - `send_window_json`: `{days: [1-7], slots: [{start, end}], timezone}` — di-do default 09-11 en 14-16
  - Cooldown 48u tussen acties; daily_limit 25 mails per dag per sequence
  - Bij missende Mailgun-config: enrollment wordt 1h vertraagd (niet definitief gestopt)
- Mailgun integratie:
  - Sending domain configureerbaar (jouw `mail.it-gemak.nl`)
  - Default from-name/email/reply-to configureerbaar in integratie
  - Per-sequence overrides mogelijk in editor
  - Signature-verified webhooks voor events + inbound
- LinkedIn outreach:
  - Tasks worden door autopilot aangemaakt voor `linkedin_connect/dm/like/visit` stappen
  - Verzending niet automatisch — UI heeft Copy + Open ↗ knoppen, jij voert in LinkedIn uit
  - Status: To do / Sent / Connected / Replied / Skipped (handmatig of via webhook)
  - LinkedIn API integratie (officieel, ban-risico=nul) staat voor posts klaar maar OAuth-flow nog niet activated

## TODO (volgende sessie kandidaten)

- [ ] Mailgun webhook-validatie end-to-end testen met echte Mailgun-events
- [ ] Reply-detection: from-adres matchen tegen bestaande enrollment-recipient → status=replied
- [ ] LinkedIn OAuth-flow afmaken (callback bestaat al)
- [ ] LinkedIn posts UI volledig maken
- [ ] AI-rewrite knop in sequence editor activeren (gebruik Anthropic key)
- [ ] Per-prospect "in sequence X, stap 2/3" tonen op company detail + stop-knop
- [ ] Encryptie-at-rest voor `integrations.config_json` secrets
- [ ] `/quotations` top-level pagina
- [ ] Postgres-backups cron
- [ ] Image pinning in compose
- [ ] Founder-password wijzigen (placeholder!)
- [ ] `Daily limit` enforcer in scheduler (niet meer dan X verzendingen per 24u per sequence)
- [ ] Smart-send window in compute_next_action_at echt respecteren (niet net buiten window plannen)
