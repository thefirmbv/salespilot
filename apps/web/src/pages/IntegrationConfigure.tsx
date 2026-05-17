import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";

type IntegrationPublic = {
  id: string;
  kind: string;
  is_enabled: boolean;
  config_public: Record<string, unknown>;
  last_sync_at: string | null;
  last_sync_status: string | null;
  last_sync_message: string | null;
  updated_at: string;
};

type TestResult = { ok: boolean; detail: string; token_present?: boolean };
type SyncResult = { ok: boolean; detail: string; fetched?: number; created?: number; updated?: number };

type FieldDef = {
  name: string;
  label: string;
  type?: "text" | "password" | "url";
  placeholder?: string;
  required?: boolean;
  help?: string;
  secret?: boolean;
};

type KindMeta = {
  label: string;
  description: string;
  docsUrl?: string;
  fields: FieldDef[];
  supportsSync: boolean;
};

const KINDS: Record<string, KindMeta> = {
  halopsa: {
    label: "HaloPSA",
    description: "OAuth2 client-credentials. Create an Integration application in HaloPSA → Configuration → Integrations.",
    docsUrl: "https://halo.haloservicedesk.com/apidoc/info",
    supportsSync: true,
    fields: [
      { name: "base_url", label: "Base URL", placeholder: "halo.example.com", required: true, help: "Your HaloPSA host without https://" },
      { name: "client_id", label: "Client ID", required: true },
      { name: "client_secret", label: "Client secret", type: "password", secret: true, required: true, help: "Stored encrypted. Leave blank to keep existing." },
      { name: "tenant", label: "Tenant (optional)", placeholder: "for shared HaloPSA instances" },
      { name: "scopes", label: "Scopes", placeholder: "all" },
    ],
  },
  prospectpro: {
    label: "ProspectPRO",
    description: "API token authentication. Generate a token in ProspectPRO → Instellingen → API.",
    docsUrl: "https://docs.prospectpro.nl/",
    supportsSync: true,
    fields: [
      { name: "base_url", label: "Base URL", placeholder: "api.prospectpro.nl", help: "Leave default unless instructed otherwise." },
      { name: "api_key", label: "API token", type: "password", secret: true, required: true, help: "Stored encrypted. Leave blank to keep existing." },
    ],
  },
  anthropic: {
    label: "Anthropic (Claude)",
    description: "AI-classifier voor de overname-monitor + callscript-generatie. Vereist API key + losse credits (apart van OpenAI).",
    docsUrl: "https://console.anthropic.com/settings/keys",
    supportsSync: false,
    fields: [
      { name: "api_key", label: "API key", type: "password", secret: true, required: true, help: "Stored encrypted. Leave blank to keep existing." },
      { name: "model", label: "Model", placeholder: "claude-haiku-4-5-20251001" },
    ],
  },
  openai: {
    label: "OpenAI (GPT)",
    description: "AI-classifier en tekst-generatie via OpenAI. Aanbevolen voor IT-gemak: jullie hebben al een OpenAI-account zonder losse credit-tracking.",
    docsUrl: "https://platform.openai.com/api-keys",
    supportsSync: false,
    fields: [
      { name: "api_key", label: "API key", type: "password", secret: true, required: true, help: "Begint met sk-... Stored encrypted. Leave blank to keep existing." },
      { name: "model", label: "Model", placeholder: "gpt-4o-mini", help: "gpt-4o-mini is goedkoop + snel; gpt-4o voor zwaardere classificatie." },
      { name: "base_url", label: "Base URL (optioneel)", placeholder: "https://api.openai.com/v1", help: "Alleen wijzigen als je een Azure OpenAI of OpenAI-compatible proxy gebruikt." },
    ],
  },
  snelstart: {
    label: "SnelStart 12",
    description: "Boekhouding (cloud). Vereist een Connect-app in SnelStart Developer Portal: developer.snelstart.nl. Daar krijg je subscription-key + client_id + client_secret.",
    docsUrl: "https://developer.snelstart.nl/",
    supportsSync: true,
    fields: [
      { name: "subscription_key", label: "Subscription key", type: "password", secret: true, required: true, help: "Ocp-Apim-Subscription-Key uit developer.snelstart.nl, je profiel → Subscriptions. Stored encrypted." },
      { name: "client_id", label: "Client ID", required: true, help: "Uit je SnelStart Connect-app." },
      { name: "client_secret", label: "Client secret", type: "password", secret: true, required: true, help: "Stored encrypted." },
      { name: "administratie_id", label: "Administratie ID (optioneel)", help: "Laat leeg en kies hieronder uit de lijst nadat de test geslaagd is." },
      { name: "base_url", label: "Base URL (optioneel)", placeholder: "https://b2bapi.snelstart.nl", help: "Alleen wijzigen voor sandbox/test." },
    ],
  },
  unifi: {
    label: "UniFi Site Manager",
    description: "Monitoring van alle Dream Machines + devices via api.ui.com. Genereer een API key op unifi.ui.com profiel -> API.",
    docsUrl: "https://developer.ui.com/",
    supportsSync: true,
    fields: [
      { name: "api_key", label: "API key", type: "password", secret: true, required: true, help: "X-API-KEY van unifi.ui.com -> profiel -> API. Stored encrypted." },
      { name: "poll_interval_seconds", label: "Poll-interval (seconden)", placeholder: "120", help: "Default 120 (= elke 2 min). Minimum 60s. Verhoog naar 300 als je dicht bij de rate-limit zit." },
      { name: "asset_type", label: "HaloPSA asset-type naam", placeholder: "UniFi Devices", help: "Onder welke asset-type alle devices in HaloPSA komen te staan." },
      { name: "halopsa_product_id", label: "HaloPSA product ID (factureren)", help: "Het recurring-product ID dat per device gefactureerd wordt. Aantal = total device-count per klant." },
      { name: "base_url", label: "Base URL (optioneel)", placeholder: "https://api.ui.com", help: "Alleen wijzigen als Ubiquiti een andere endpoint introduceert." },
    ],
  },
  plesk: {
    label: "Plesk Hosting",
    description: "Plesk REST API v2 met X-API-Key header. Genereer key onder Tools & Settings -> Remote API (REST) -> API Keys.",
    docsUrl: "https://docs.plesk.com/en-US/obsidian/api-rpc/about-rest-api.79358/",
    supportsSync: true,
    fields: [
      { name: "base_url", label: "Plesk URL", placeholder: "https://plesk.host:8443", required: true, help: "Inclusief https:// en :8443 poort." },
      { name: "api_key", label: "API key", type: "password", secret: true, required: true, help: "X-API-Key. Stored encrypted." },
      { name: "poll_interval_seconds", label: "Poll-interval (sec)", placeholder: "300", help: "Default 300 (5 min)." },
      { name: "verify_tls", label: "TLS verificatie (1/0)", placeholder: "1", help: "Op 0 zetten als Plesk self-signed cert heeft." },
      { name: "asset_type", label: "HaloPSA asset-type", placeholder: "Plesk Hosting" },
      { name: "halopsa_product_id", label: "HaloPSA product ID (recurring)", help: "Product dat per subscription wordt gefactureerd." },
    ],
  },
  openprovider: {
    label: "Openprovider",
    description: "Domain registrar. JWT auth via user/password. Aangeraden: dedicated read-only API-user in Openprovider met IP-allowlist.",
    docsUrl: "https://docs.openprovider.com/doc/all",
    supportsSync: true,
    fields: [
      { name: "username", label: "Username", required: true },
      { name: "password", label: "Password", type: "password", secret: true, required: true, help: "Stored encrypted." },
      { name: "bound_ip", label: "Bound IP (optioneel)", placeholder: "10.20.1.152", help: "Beperk token tot dit IP voor extra veiligheid." },
      { name: "poll_interval_seconds", label: "Poll-interval (sec)", placeholder: "3600", help: "Default 3600 (1u). Domeinen wijzigen niet vaak." },
      { name: "asset_type", label: "HaloPSA asset-type", placeholder: "Domain Registration" },
      { name: "halopsa_product_id", label: "HaloPSA product ID (recurring)" },
    ],
  },
  mailgun: {
    label: "Mailgun",
    description: "Outbound mail for sequences and inbound reply detection. Sending domain must be verified in Mailgun first (SPF/DKIM/DMARC).",
    docsUrl: "https://documentation.mailgun.com/en/latest/",
    supportsSync: false,
    fields: [
      { name: "base_url", label: "API base URL", placeholder: "api.eu.mailgun.net", help: "Use api.eu.mailgun.net for EU region, api.mailgun.net for US." },
      { name: "domain", label: "Sending domain", required: true, placeholder: "mail.it-gemak.nl", help: "The verified Mailgun sending domain. Visible 'from' address is set per-sequence." },
      { name: "default_from_name", label: "Default from name", placeholder: "Jan de Boer" },
      { name: "default_from_email", label: "Default from email", placeholder: "jan@it-gemak.nl", help: "Used as default in new sequences. Per-sequence overrides possible." },
      { name: "default_reply_to", label: "Default reply-to", placeholder: "jan@it-gemak.nl" },
      { name: "api_key", label: "API key (Domain Sending key)", type: "password", secret: true, required: true, help: "Stored encrypted. Leave blank to keep existing." },
      { name: "webhook_signing_key", label: "HTTP webhook signing key", type: "password", secret: true, help: "From Mailgun → Sending → Webhooks. Used to verify event + inbound webhooks." },
      // ---- Sender-reputation throttle ----
      { name: "limits.max_per_day", label: "Max berichten per dag (24u glijdend)", placeholder: "30", help: "Conservatief voor warm-up van een nieuw (sub)domein. Bump na 2 weken zonder bounces." },
      { name: "limits.max_per_hour", label: "Max berichten per uur", placeholder: "6", help: "Spreidt belasting over de dag voor goede sender-reputatie." },
      { name: "limits.min_seconds_gap", label: "Minimum seconden tussen mails", placeholder: "90", help: "Voorkomt dat twee mails binnen X seconden achter elkaar verstuurd worden." },
    ],
  },
  linkedin: {
    label: "LinkedIn",
    description: "Officiele LinkedIn API voor post-scheduling en analytics. Eerst je app aanmaken in de LinkedIn Developer console, dan client_id + secret hier invullen, dan de Verbind-knop hieronder.",
    docsUrl: "https://www.linkedin.com/developers/apps",
    supportsSync: false,
    fields: [
      { name: "client_id", label: "Client ID", required: true, help: "Uit je LinkedIn Developer app (Auth tab)." },
      { name: "client_secret", label: "Client secret", type: "password", secret: true, required: true, help: "Stored encrypted." },
    ],
  },

  // ---- Wespennest data sources ----

  kvk: {
    label: "KVK (officieel)",
    description: "Officiële KVK API. Best for bestuurder-namen (Functionarissen) en geverifieerde fte. Vereist abonnement (€6,40/mnd + €0,05/call) en handmatige goedkeuring van ±5 werkdagen.",
    docsUrl: "https://developers.kvk.nl/",
    supportsSync: false,
    fields: [
      { name: "base_url", label: "Base URL", placeholder: "https://api.kvk.nl/api", help: "Laat default tenzij anders geïnstrueerd." },
      { name: "api_key", label: "Basisprofiel API-key", type: "password", secret: true, help: "Voor bedrijfs-zoek + basisprofiel. Stored encrypted." },
      { name: "functionarissen_key", label: "Functionarissen API-key (optioneel)", type: "password", secret: true, help: "Aparte key voor bestuurder-data. Vraag deze los aan bij KVK." },
    ],
  },

  openkvk: {
    label: "OpenKVK",
    description: "Gratis open KVK-data via overheid.io. Werkt direct zonder key (rate-limited). Met een gratis key zijn er veel meer requests beschikbaar. Onze aanbeveling om mee te starten terwijl je op de officiële KVK wacht.",
    docsUrl: "https://overheid.io/documentatie/openkvk",
    supportsSync: false,
    fields: [
      { name: "base_url", label: "Base URL", placeholder: "https://api.overheid.io/openkvk", help: "Laat default." },
      { name: "api_key", label: "ovio-api-key (optioneel)", type: "password", secret: true, help: "Vraag een gratis key aan op overheid.io voor hogere rate-limits." },
    ],
  },

  pdok: {
    label: "PDOK Geocoder",
    description: "Gratis Nederlandse geocoder voor postcodes en adressen → coördinaten. Vereist voor het 40 km-filter. Geen account nodig.",
    docsUrl: "https://www.pdok.nl/restful-api/-/article/pdok-locatieserver",
    supportsSync: false,
    fields: [
      { name: "base_url", label: "Base URL", placeholder: "https://api.pdok.nl", help: "Laat default." },
      { name: "hq_label", label: "HQ locatie label", placeholder: "Breukelen", help: "Naam van de plaats waarvandaan afstand gemeten wordt." },
      { name: "hq_lat", label: "HQ latitude", placeholder: "52.1719", help: "Default = Breukelen." },
      { name: "hq_lon", label: "HQ longitude", placeholder: "4.9994", help: "Default = Breukelen." },
    ],
  },

  crtsh: {
    label: "crt.sh",
    description: "Certificate Transparency log search. Vindt klant-domeinen die onder dezelfde wildcard-certificaten van een MSP zitten. Gratis, geen account.",
    docsUrl: "https://crt.sh/",
    supportsSync: false,
    fields: [
      { name: "base_url", label: "Base URL", placeholder: "https://crt.sh", help: "Laat default." },
    ],
  },

  hunter: {
    label: "Hunter.io",
    description: "Optionele commerciële bron voor email-pattern discovery en email verificatie. 25 zoekopdrachten/mnd gratis, daarna $34+/mnd. Voor NL-MKB kunnen we vaak al met patroon-rules + SMTP-probe.",
    docsUrl: "https://hunter.io/api",
    supportsSync: false,
    fields: [
      { name: "base_url", label: "Base URL", placeholder: "https://api.hunter.io/v2", help: "Laat default." },
      { name: "api_key", label: "Hunter API-key", type: "password", secret: true, help: "Stored encrypted." },
    ],
  },

  apollo: {
    label: "Apollo.io",
    description: "Optionele commerciële bron voor internationale decision-maker enrichment. $49+/mnd. Voor NL-MKB minder geschikt — gebruik KVK Functionarissen + LinkedIn.",
    docsUrl: "https://apolloio.github.io/apollo-api-docs/",
    supportsSync: false,
    fields: [
      { name: "base_url", label: "Base URL", placeholder: "https://api.apollo.io/v1", help: "Laat default." },
      { name: "api_key", label: "Apollo API-key", type: "password", secret: true, help: "Stored encrypted." },
    ],
  },

  m365_sso: {
    label: "Microsoft 365 SSO",
    description: "Laat gebruikers inloggen met hun M365-account in plaats van een SalesPilot-wachtwoord. Vereist een Azure AD app-registratie. Redirect URL bij Azure: https://sales.hostingportal.org/api/v1/auth/m365/callback",
    docsUrl: "https://learn.microsoft.com/en-us/azure/active-directory/develop/quickstart-register-app",
    supportsSync: false,
    fields: [
      { name: "tenant_id", label: "Tenant ID", placeholder: "common of jullie-tenant-guid", help: "Gebruik 'common' om alle Microsoft-accounts toe te staan, of jullie eigen tenant-GUID voor strikte beveiliging." },
      { name: "client_id", label: "Client ID", placeholder: "Azure app Application (client) ID", help: "Van de Azure portal." },
      { name: "client_secret", label: "Client secret", type: "password", secret: true, help: "Stored encrypted." },
      { name: "allowed_email_domains", label: "Toegestane email-domeinen", placeholder: "it-gemak.nl,hostingportal.org", help: "Komma-gescheiden lijst. Leeg = alle domeinen toegestaan." },
    ],
  },

  wespennest: {
    label: "Wespennest instellingen",
    description: "Bepaal welke bron Wespennest standaard gebruikt voor KvK-lookups. Handig zolang je nog op de officiële KVK-key wacht of als de bronnen later veranderen.",
    docsUrl: "",
    supportsSync: false,
    fields: [],  // alle UI in het WespennestSettingsBlock hieronder
  },

  pbx_3cx: {
    label: "3CX telefooncentrale",
    description: "Klik op een telefoonnummer in het portaal en bel direct via je 3CX-toestel. Werkt met de 3CX desktop/web-app of de mobiele app op je telefoon.",
    docsUrl: "https://www.3cx.com/docs/click-to-call-extension/",
    supportsSync: false,
    fields: [
      { name: "pbx_fqdn", label: "3CX hostnaam", placeholder: "pbx.it-gemak.nl of mybedrijf.3cx.eu", help: "De hostnaam van je 3CX centrale, zonder https://. Voor 3CX-protocol-handlers nodig." },
      { name: "extension", label: "Doorkiesnummer (extension, optioneel)", placeholder: "bv. 100", help: "Jouw 3CX-toestelnummer. Wordt meegestuurd zodat 3CX weet vanaf welk toestel te bellen." },
      { name: "country_code", label: "Landcode (zonder +)", placeholder: "31", help: "Wordt automatisch toegevoegd aan nummers die met 0 beginnen. Default: 31 (NL)." },
      { name: "default_outbound_prefix", label: "Uitbelprefix (optioneel)", placeholder: "9 of 0", help: "Sommige 3CX-installaties vereisen een prefix om naar buiten te bellen. Leeg laten als je geen prefix gebruikt." },
      { name: "click_mode", label: "Belmethode", help: "tel:// = werkt overal, opent je standaard telefoon-app. 3cx:// = opent direct de 3CX-app als die geïnstalleerd is.", placeholder: "tel" },
    ],
  },
};

export function IntegrationConfigure() {
  const { kind = "" } = useParams();
  const meta = KINDS[kind];
  const qc = useQueryClient();
  const [form, setForm] = useState<Record<string, string>>({});
  const [searchParams, setSearchParams] = useSearchParams();
  const [enabled, setEnabled] = useState(true);

  const integrationQ = useQuery<IntegrationPublic | null>({
    queryKey: [`/integrations/${kind}`],
    queryFn: () => api<IntegrationPublic | null>(`/integrations/${kind}`),
    enabled: !!meta,
  });

  useEffect(() => {
    if (integrationQ.data) {
      setEnabled(integrationQ.data.is_enabled);
      const cfg = integrationQ.data.config_public as Record<string, unknown>;
      const next: Record<string, string> = {};
      for (const f of meta?.fields ?? []) {
        // Support dotted field names like "limits.max_per_day" -> cfg.limits.max_per_day
        let v: unknown;
        if (f.name.includes(".")) {
          const [head, tail] = f.name.split(".", 2);
          const bucket = cfg[head];
          v = (bucket && typeof bucket === "object") ? (bucket as Record<string, unknown>)[tail] : undefined;
        } else {
          v = cfg[f.name];
        }
        if (typeof v === "string") next[f.name] = v;
        else if (typeof v === "number") next[f.name] = String(v);
      }
      setForm(next);
    }
  }, [integrationQ.data, meta]);

  const saveMut = useMutation({
    mutationFn: () =>
      api<IntegrationPublic>(`/integrations/${kind}`, {
        method: "PUT",
        body: JSON.stringify({ is_enabled: enabled, config: form }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [`/integrations/${kind}`] });
      qc.invalidateQueries({ queryKey: ["/integrations"] });
      // Clear out the secret field so we don't keep showing it.
      const next = { ...form };
      for (const f of meta?.fields ?? []) {
        if (f.secret) next[f.name] = "";
      }
      setForm(next);
    },
  });

  const testMut = useMutation({
    mutationFn: () =>
      api<TestResult>(`/integrations/${kind}/test`, { method: "POST" }),
  });

  const syncMut = useMutation({
    mutationFn: () =>
      api<SyncResult>(`/integrations/${kind}/sync`, { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["/integrations"] });
      qc.invalidateQueries({ queryKey: ["/prospects-list"] });
    },
  });

  if (!meta) {
    return (
      <div>
        <div className="text-sm text-slate-500">Unknown integration: {kind}</div>
        <Link to="/settings/integrations" className="text-xs text-brand-600 underline">
          ← Back to integrations
        </Link>
      </div>
    );
  }

  const cfg = integrationQ.data?.config_public ?? {};

  return (
    <div className="max-w-2xl">
      <div className="mb-4">
        <Link
          to="/settings/integrations"
          className="text-xs text-slate-500 hover:text-slate-900"
        >
          ← All integrations
        </Link>
        <h2 className="mt-1 text-base font-medium">{meta.label}</h2>
        <p className="mt-1 text-xs text-slate-500">{meta.description}</p>
        {meta.docsUrl && (
          <a
            href={meta.docsUrl}
            target="_blank"
            rel="noreferrer"
            className="text-xs text-brand-600 underline"
          >
            View documentation ↗
          </a>
        )}
      </div>

      <div className="rounded-md border border-slate-200 bg-white p-4">
        <label className="flex items-center gap-2 mb-4">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => setEnabled(e.target.checked)}
            className="rounded border-slate-300"
          />
          <span className="text-sm">Enabled</span>
        </label>

        <div className="space-y-3">
          {meta.fields.map((f) => {
            const fieldName = `${f.name}_set`;
            const secretSet = f.secret && Boolean(cfg[fieldName]);
            return (
              <div key={f.name}>
                <label className="block text-xs font-medium text-slate-700 mb-1">
                  {f.label}
                  {f.required && <span className="text-red-500 ml-0.5">*</span>}
                </label>
                <input
                  type={f.type ?? "text"}
                  value={form[f.name] ?? ""}
                  onChange={(e) => setForm({ ...form, [f.name]: e.target.value })}
                  placeholder={
                    f.secret && secretSet ? "•••••••• (currently set)" : f.placeholder
                  }
                  className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
                />
                {f.help && <div className="mt-1 text-[11px] text-slate-500">{f.help}</div>}
              </div>
            );
          })}
        </div>

        {kind === "linkedin" && <LinkedInOAuthBlock cfg={integrationQ.data?.config_public ?? {}} kind={kind!} searchParams={searchParams} setSearchParams={setSearchParams} />}
        {kind === "m365_sso" && <M365SsoInfoBlock cfg={integrationQ.data?.config_public ?? {}} />}
        {kind === "wespennest" && <WespennestSettingsBlock cfg={integrationQ.data?.config_public ?? {}} form={form} setForm={setForm} />}

        <div className="mt-5 flex flex-wrap items-center gap-2">
          <button
            onClick={() => saveMut.mutate()}
            disabled={saveMut.isPending}
            className="rounded-md bg-brand-500 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-600 disabled:opacity-50"
          >
            {saveMut.isPending ? "Saving…" : "Save"}
          </button>
          <button
            onClick={() => testMut.mutate()}
            disabled={!integrationQ.data || testMut.isPending}
            className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            {testMut.isPending ? "Testing…" : "Test connection"}
          </button>
          {meta.supportsSync && (
            <button
              onClick={() => syncMut.mutate()}
              disabled={!integrationQ.data || syncMut.isPending}
              className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            >
              {syncMut.isPending ? "Syncing…" : "Sync now"}
            </button>
          )}
        </div>

        {saveMut.isSuccess && (
          <div className="mt-3 rounded-md bg-emerald-50 px-3 py-1.5 text-xs text-emerald-800">
            Saved.
          </div>
        )}
        {saveMut.isError && (
          <div className="mt-3 rounded-md bg-red-50 px-3 py-1.5 text-xs text-red-800">
            {saveMut.error instanceof ApiError ? saveMut.error.detail : "Save failed"}
          </div>
        )}
        {testMut.data && (
          <div
            className={`mt-3 rounded-md px-3 py-1.5 text-xs ${
              testMut.data.ok ? "bg-emerald-50 text-emerald-800" : "bg-red-50 text-red-800"
            }`}
          >
            {testMut.data.detail}
          </div>
        )}
        {syncMut.data && (
          <div
            className={`mt-3 rounded-md px-3 py-1.5 text-xs ${
              syncMut.data.ok ? "bg-emerald-50 text-emerald-800" : "bg-red-50 text-red-800"
            }`}
          >
            {syncMut.data.detail}
          </div>
        )}
      </div>
    </div>
  );
}

// ===== LinkedIn OAuth section =====

function LinkedInOAuthBlock({
  cfg, kind, searchParams, setSearchParams,
}: {
  cfg: Record<string, unknown>;
  kind: string;
  searchParams: URLSearchParams;
  setSearchParams: (params: URLSearchParams, opts?: { replace?: boolean }) => void;
}) {
  const connected = !!cfg.connected_via_oauth;
  const connectedAt = cfg.connected_at as string | undefined;
  const expiresAt = cfg.access_token_expires_at as string | undefined;
  const scope = cfg.granted_scope as string | undefined;
  const clientIdSet = !!cfg.client_id;
  const secretSet = !!cfg.client_secret_set;

  const oauthOk = searchParams.get("oauth_ok");
  const oauthError = searchParams.get("oauth_error");

  // Clear the query params after first render so a reload doesn't keep the banner
  const dismissBanner = () => {
    const next = new URLSearchParams(searchParams);
    next.delete("oauth_ok");
    next.delete("oauth_error");
    setSearchParams(next, { replace: true });
  };

  const handleConnect = async () => {
    try {
      const r = await fetch(`/api/v1/integrations/${kind}/oauth-url`, {
        headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` },
      });
      const data = await r.json();
      if (data.authorize_url) {
        window.location.href = data.authorize_url;
      } else {
        alert("Geen OAuth URL kunnen genereren. Eerst Client ID + Secret opslaan.");
      }
    } catch (e) {
      alert("OAuth start mislukte: " + (e instanceof Error ? e.message : "onbekend"));
    }
  };

  let expiryText: string | null = null;
  let expiryTone: "default" | "warning" | "danger" = "default";
  if (expiresAt) {
    const expDate = new Date(expiresAt);
    const daysLeft = Math.round((expDate.getTime() - Date.now()) / (1000 * 60 * 60 * 24));
    if (daysLeft < 0) {
      expiryText = `Token is verlopen (${-daysLeft} dagen geleden)`;
      expiryTone = "danger";
    } else if (daysLeft < 7) {
      expiryText = `Token verloopt over ${daysLeft} dagen`;
      expiryTone = "warning";
    } else {
      expiryText = `Geldig tot ${expDate.toLocaleDateString("nl-NL")} (${daysLeft} dagen)`;
    }
  }

  return (
    <div className="mt-5 rounded-md border border-slate-200 bg-slate-50 p-4 space-y-2">
      <div className="text-[11px] uppercase tracking-wider text-slate-500">OAuth verbinding</div>

      {oauthOk && (
        <div className="rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-800 flex items-start justify-between gap-2">
          <span>✅ Verbonden met LinkedIn. Je kunt nu posten + destinations ophalen.</span>
          <button onClick={dismissBanner} className="text-emerald-700 hover:text-emerald-900">×</button>
        </div>
      )}
      {oauthError && (
        <div className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-800 flex items-start justify-between gap-2">
          <span>❌ OAuth mislukt: <code className="font-mono text-xs">{oauthError}</code></span>
          <button onClick={dismissBanner} className="text-red-700 hover:text-red-900">×</button>
        </div>
      )}

      {!clientIdSet || !secretSet ? (
        <div className="rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-900">
          Vul eerst <strong>Client ID</strong> + <strong>Client secret</strong> hierboven in en klik op <strong>Save</strong>. Daarna kun je hier verbinden.
        </div>
      ) : !connected ? (
        <div className="space-y-2">
          <div className="text-sm text-slate-700">
            Nog niet verbonden. Klik op de knop om naar LinkedIn te gaan voor authorizatie.
          </div>
          <div className="text-[11px] text-slate-500">
            Belangrijk: in de LinkedIn Developer console moet onder <strong>Auth → Authorized redirect URLs</strong> deze URL staan:<br/>
            <code className="font-mono text-[11px] block mt-1 rounded bg-white px-2 py-1">https://sales.hostingportal.org/api/v1/oauth/linkedin/callback</code>
          </div>
          <button
            type="button"
            onClick={handleConnect}
            className="rounded-md bg-[#0A66C2] px-3 py-1.5 text-sm font-medium text-white hover:bg-[#0856A6]"
          >
            🔗 Verbinden met LinkedIn
          </button>
        </div>
      ) : (
        <div className="space-y-2">
          <div className="flex items-center gap-2 text-sm">
            <span className="inline-flex h-2 w-2 rounded-full bg-emerald-500"></span>
            <span className="font-medium text-emerald-800">Verbonden</span>
            {connectedAt && (
              <span className="text-slate-500 text-xs">sinds {new Date(connectedAt).toLocaleDateString("nl-NL")}</span>
            )}
          </div>
          {expiryText && (
            <div className={`text-xs ${
              expiryTone === "danger" ? "text-red-700" :
              expiryTone === "warning" ? "text-amber-700" :
              "text-slate-600"
            }`}>
              {expiryText}
            </div>
          )}
          {scope && <div className="text-[11px] text-slate-500">Scope: <code className="font-mono">{scope}</code></div>}
          <button
            type="button"
            onClick={handleConnect}
            className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs text-slate-700 hover:bg-slate-50"
          >
            Opnieuw verbinden
          </button>
        </div>
      )}
    </div>
  );
}

// ===== Microsoft 365 SSO info block =====

function M365SsoInfoBlock({ cfg }: { cfg: Record<string, unknown> }) {
  const callbackUrl = `${window.location.origin}/api/v1/auth/m365/callback`;
  const loginUrl = `${window.location.origin}/api/v1/auth/m365/login`;
  const tenantId = (cfg.tenant_id as string) || "";
  const isStrict = tenantId && tenantId !== "common" && tenantId !== "organizations";

  return (
    <div className="mt-5 space-y-3">
      <div className="rounded-md border border-blue-200 bg-blue-50 p-4 space-y-2">
        <div className="text-[11px] uppercase tracking-wider text-blue-700 font-semibold">Belangrijke beveiligings-info</div>
        <div className="text-sm text-blue-900">
          <strong>Alleen uitgenodigde gebruikers</strong> kunnen via M365 inloggen.
          Dat wordt afgedwongen door de server, zelfs als iemand een geldig
          M365-account in jullie tenant heeft. Iemand zonder uitnodiging krijgt
          de melding <code className="font-mono text-xs bg-white px-1 py-0.5 rounded">user_not_provisioned</code> en kan niet binnen.
        </div>
        <div className="text-xs text-blue-800">
          Nieuwe collega&apos;s uitnodigen: <a href="/settings/management" className="underline">Settings → Management</a>.
        </div>
      </div>

      <div className="rounded-md border border-slate-200 bg-slate-50 p-4 space-y-2">
        <div className="text-[11px] uppercase tracking-wider text-slate-500 font-semibold">Te configureren in Entra ID</div>
        <div className="text-sm space-y-2">
          <div>
            <div className="text-xs text-slate-500 mb-0.5">Redirect URI (Authentication → Platform configurations → Web):</div>
            <div className="flex items-center gap-2">
              <code className="flex-1 font-mono text-xs bg-white px-2 py-1.5 rounded border border-slate-200 break-all">{callbackUrl}</code>
              <button
                type="button"
                onClick={() => { navigator.clipboard.writeText(callbackUrl); }}
                className="rounded border border-slate-300 bg-white px-2 py-1 text-xs hover:bg-slate-50"
                title="Copy"
              >
                Copy
              </button>
            </div>
          </div>
          <div>
            <div className="text-xs text-slate-500 mb-0.5">Login-URL (deze geven aan collega&apos;s):</div>
            <div className="flex items-center gap-2">
              <code className="flex-1 font-mono text-xs bg-white px-2 py-1.5 rounded border border-slate-200 break-all">{loginUrl}</code>
              <button
                type="button"
                onClick={() => { navigator.clipboard.writeText(loginUrl); }}
                className="rounded border border-slate-300 bg-white px-2 py-1 text-xs hover:bg-slate-50"
                title="Copy"
              >
                Copy
              </button>
            </div>
          </div>
          <div className="text-xs text-slate-500 pt-2">
            <strong>Supported account types</strong> in de Entra app moet staan op <em>&quot;Accounts in this organizational directory only (single tenant)&quot;</em> voor maximale beveiliging.
            {isStrict ? (
              <span className="ml-1 text-emerald-700">✓ Je hebt een specifieke tenant-GUID geconfigureerd.</span>
            ) : tenantId === "common" ? (
              <span className="ml-1 text-amber-700">⚠ Tenant staat op &apos;common&apos;: AAD laat élke M365-tenant binnen. Vul jullie tenant-GUID in voor strikte beveiliging.</span>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}

// ===== Wespennest preferences block =====

function WespennestSettingsBlock({
  cfg, form, setForm,
}: {
  cfg: Record<string, unknown>;
  form: Record<string, string>;
  setForm: (f: Record<string, string>) => void;
}) {
  // Read the active value from `form` if the user has changed it, else
  // from the persisted config_public.
  const current = (form.primary_kvk_source as string)
    ?? (cfg.primary_kvk_source as string)
    ?? "auto";

  const setPrimary = (v: string) => {
    setForm({ ...form, primary_kvk_source: v });
  };

  const options: { value: string; title: string; desc: string; tone: string }[] = [
    {
      value: "auto",
      title: "Automatisch (aanbevolen)",
      desc: "Gebruikt KVK officieel als die geconfigureerd is, anders OpenKVK. Beste van twee werelden.",
      tone: "border-brand-500 bg-brand-50",
    },
    {
      value: "openkvk",
      title: "OpenKVK eerst",
      desc: "Gratis bron via overheid.io. Werkt direct, geen API-key nodig. Beperkte data (vooral handelsnaam).",
      tone: "border-emerald-500 bg-emerald-50",
    },
    {
      value: "kvk",
      title: "KVK officieel eerst",
      desc: "Authoritative bron met volledige NAW + functionarissen. Vereist betaalde API-key van developers.kvk.nl.",
      tone: "border-violet-500 bg-violet-50",
    },
  ];

  return (
    <div className="mt-5 space-y-3">
      <div className="rounded-md border border-slate-200 bg-slate-50 p-4 space-y-3">
        <div>
          <div className="text-[11px] uppercase tracking-wider text-slate-500 font-semibold">Primaire bron voor KvK-lookups</div>
          <div className="text-xs text-slate-500 mt-1">
            Wespennest probeert eerst de gekozen bron; als die niets vindt valt het automatisch terug op de andere.
          </div>
        </div>

        <div className="space-y-2">
          {options.map((opt) => {
            const active = current === opt.value;
            return (
              <label
                key={opt.value}
                className={`flex items-start gap-3 rounded-md border-2 p-3 cursor-pointer transition ${
                  active ? opt.tone : "border-slate-200 bg-white hover:border-slate-300"
                }`}
              >
                <input
                  type="radio"
                  name="primary_kvk_source"
                  value={opt.value}
                  checked={active}
                  onChange={() => setPrimary(opt.value)}
                  className="mt-1 h-4 w-4 accent-brand-500"
                />
                <div className="flex-1">
                  <div className="text-sm font-medium">{opt.title}</div>
                  <div className="text-xs text-slate-600 mt-0.5">{opt.desc}</div>
                </div>
              </label>
            );
          })}
        </div>

        <div className="rounded-md bg-blue-50 px-3 py-2 text-xs text-blue-900">
          <strong>Tip:</strong> klik <strong>Save</strong> hieronder om de keuze te bewaren. Wespennest pakt het nieuwe gedrag op bij de eerstvolgende scan-tick (binnen 4 uur, of direct via een handmatige sync).
        </div>
      </div>

      <AiClassifierBlock cfg={cfg} form={form} setForm={setForm} />
    </div>
  );
}

function AiClassifierBlock({
  cfg, form, setForm,
}: {
  cfg: Record<string, unknown>;
  form: Record<string, string>;
  setForm: (f: Record<string, string>) => void;
}) {
  const current = (form.ai_classifier_source as string)
    ?? (cfg.ai_classifier_source as string)
    ?? "auto";

  const setSource = (v: string) => {
    setForm({ ...form, ai_classifier_source: v });
  };

  const options: { value: string; title: string; desc: string; tone: string }[] = [
    {
      value: "auto",
      title: "Automatisch (aanbevolen)",
      desc: "Gebruikt OpenAI als die geconfigureerd is, anders Anthropic. Beide aan: OpenAI eerst.",
      tone: "border-brand-500 bg-brand-50",
    },
    {
      value: "openai",
      title: "OpenAI eerst",
      desc: "Forceert OpenAI als primair; Anthropic alleen bij OpenAI-fouten.",
      tone: "border-emerald-500 bg-emerald-50",
    },
    {
      value: "anthropic",
      title: "Anthropic (Claude) eerst",
      desc: "Forceert Claude als primair; OpenAI alleen bij Claude-fouten.",
      tone: "border-violet-500 bg-violet-50",
    },
    {
      value: "off",
      title: "Uit",
      desc: "Geen AI. Overname-monitor valt terug op keyword-filtering zonder semantische analyse.",
      tone: "border-slate-400 bg-slate-100",
    },
  ];

  return (
    <div className="rounded-md border border-slate-200 bg-slate-50 p-4 space-y-3">
      <div>
        <div className="text-[11px] uppercase tracking-wider text-slate-500 font-semibold">AI-classifier bron</div>
        <div className="text-xs text-slate-500 mt-1">
          Welke AI gebruikt Wespennest voor de overname-monitor en toekomstige features (LinkedIn AI-content, callscripts).
        </div>
      </div>

      <div className="space-y-2">
        {options.map((opt) => {
          const active = current === opt.value;
          return (
            <label
              key={opt.value}
              className={`flex items-start gap-3 rounded-md border-2 p-3 cursor-pointer transition ${
                active ? opt.tone : "border-slate-200 bg-white hover:border-slate-300"
              }`}
            >
              <input
                type="radio"
                name="ai_classifier_source"
                value={opt.value}
                checked={active}
                onChange={() => setSource(opt.value)}
                className="mt-1 h-4 w-4 accent-brand-500"
              />
              <div className="flex-1">
                <div className="text-sm font-medium">{opt.title}</div>
                <div className="text-xs text-slate-600 mt-0.5">{opt.desc}</div>
              </div>
            </label>
          );
        })}
      </div>
    </div>
  );
}
