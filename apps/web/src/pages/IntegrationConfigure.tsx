import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
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
    description: "Used by the AI Callscript generator on the prospect detail page.",
    docsUrl: "https://console.anthropic.com/settings/keys",
    supportsSync: false,
    fields: [
      { name: "api_key", label: "API key", type: "password", secret: true, required: true, help: "Stored encrypted. Leave blank to keep existing." },
      { name: "model", label: "Model", placeholder: "claude-sonnet-4-5-20250929" },
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
    ],
  },
  linkedin: {
    label: "LinkedIn",
    description: "Officiele LinkedIn API — nul ban-risico. Voor post-scheduling en outreach task tracking. OAuth-flow volgt zodra je een LinkedIn-app hebt gemaakt.",
    docsUrl: "https://learn.microsoft.com/en-us/linkedin/marketing/",
    supportsSync: false,
    fields: [
      { name: "client_id", label: "Client ID", help: "From your LinkedIn Developer app." },
      { name: "client_secret", label: "Client secret", type: "password", secret: true, help: "Stored encrypted. Leave blank to keep existing." },
      { name: "person_urn", label: "Person URN (optional)", placeholder: "urn:li:person:XXXX", help: "For posting from your personal profile." },
      { name: "organization_urn", label: "Organization URN (optional)", placeholder: "urn:li:organization:NNNN", help: "For posting from your company page." },
      { name: "access_token", label: "Access token (manual until OAuth flow)", type: "password", secret: true, help: "Will be replaced by OAuth flow in a future update." },
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
};

export function IntegrationConfigure() {
  const { kind = "" } = useParams();
  const meta = KINDS[kind];
  const qc = useQueryClient();
  const [form, setForm] = useState<Record<string, string>>({});
  const [enabled, setEnabled] = useState(true);

  const integrationQ = useQuery<IntegrationPublic | null>({
    queryKey: [`/integrations/${kind}`],
    queryFn: () => api<IntegrationPublic | null>(`/integrations/${kind}`),
    enabled: !!meta,
  });

  useEffect(() => {
    if (integrationQ.data) {
      setEnabled(integrationQ.data.is_enabled);
      const cfg = integrationQ.data.config_public;
      const next: Record<string, string> = {};
      for (const f of meta?.fields ?? []) {
        const v = cfg[f.name];
        if (typeof v === "string") next[f.name] = v;
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
