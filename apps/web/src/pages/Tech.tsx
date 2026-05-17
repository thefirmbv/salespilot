import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

type IntegrationRow = {
  id: string;
  kind: string;
  is_enabled: boolean;
  config_public: Record<string, unknown>;
  last_sync_at: string | null;
  last_sync_status: string | null;
  last_sync_message: string | null;
};

type TechLink = {
  title: string;
  description: string;
  href: string;
  status_kind: string | null;
  badge?: string;
};

// Catalog van Tech-koppelingen. Niets ingewikkelds: links naar de
// bestaande beheer-pagina's.
const TECH_LINKS: TechLink[] = [
  {
    title: "UniFi → HaloPSA asset-sync",
    description: "Spiegel alle UniFi devices als Asset onder type 'UniFi Devices' in HaloPSA voor recurring-facturatie.",
    href: "/unifi?tab=links",
    status_kind: "unifi",
    badge: "Productie",
  },
  {
    title: "UniFi monitoring (api.ui.com)",
    description: "Poll alle Dream Machines + devices elke 2 minuten. State-changes worden gelogd voor incidents-feed + Grafana.",
    href: "/settings/integrations/unifi",
    status_kind: "unifi",
  },
  {
    title: "NMBRS → MS365 Outlook",
    description: "Verlof uit NMBRS in elke eigen Outlook-agenda als 'Verlof - <Voornaam> - <type>'.",
    href: "/settings/integrations/nmbrs",
    status_kind: "nmbrs",
    badge: "In voorbereiding",
  },
  {
    title: "HaloPSA (PSA)",
    description: "Bron-systeem voor klanten, tickets, offertes, mail-campaigns. Asset-sync vereist scope read/write assets.",
    href: "/settings/integrations/halopsa",
    status_kind: "halopsa",
  },
];

const fmtAgo = (s: string | null) => {
  if (!s) return "nooit";
  const ms = Date.now() - new Date(s).getTime();
  if (ms < 60_000) return `${Math.floor(ms / 1000)}s geleden`;
  if (ms < 3600_000) return `${Math.floor(ms / 60_000)}m geleden`;
  if (ms < 86400_000) return `${Math.floor(ms / 3600_000)}u geleden`;
  return `${Math.floor(ms / 86400_000)}d geleden`;
};

export function Tech() {
  const integrationsQ = useQuery<IntegrationRow[]>({
    queryKey: ["integrations-tech"],
    queryFn: async () => {
      // Try each known tech-integration. /integrations/{kind} returns single row.
      const kinds = ["unifi", "nmbrs", "halopsa"];
      const out: IntegrationRow[] = [];
      for (const k of kinds) {
        try {
          const r = await api<IntegrationRow>(`/integrations/${k}`);
          out.push(r);
        } catch { /* row may not exist yet */ }
      }
      return out;
    },
  });

  const integrationsByKind = new Map(
    (integrationsQ.data || []).map((i) => [i.kind, i]),
  );

  return (
    <div className="space-y-4">
      <div className="rounded-lg bg-white ring-1 ring-slate-200 p-4">
        <h1 className="text-lg font-medium">Tech — koppelingen</h1>
        <p className="mt-1 text-sm text-slate-600">
          Technische data-pipelines: UniFi → HaloPSA, NMBRS → MS365, etc.
          Alleen administrators zien deze sectie.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {TECH_LINKS.map((tl) => {
          const ig = tl.status_kind ? integrationsByKind.get(tl.status_kind) : null;
          return (
            <Link
              key={tl.href}
              to={tl.href}
              className="rounded-lg bg-white ring-1 ring-slate-200 p-4 hover:ring-brand-300 hover:bg-slate-50"
            >
              <div className="flex items-baseline justify-between gap-3">
                <h3 className="text-sm font-semibold">{tl.title}</h3>
                {tl.badge && (
                  <span className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">{tl.badge}</span>
                )}
              </div>
              <p className="mt-1 text-sm text-slate-600">{tl.description}</p>
              {ig && (
                <div className="mt-2 flex items-center gap-2 text-xs">
                  <span className={`inline-block w-1.5 h-1.5 rounded-full ${ig.is_enabled ? (ig.last_sync_status === "error" ? "bg-rose-500" : "bg-emerald-500") : "bg-slate-300"}`} />
                  <span className="text-slate-500">
                    {ig.is_enabled ? (ig.last_sync_status || "actief") : "uitgeschakeld"} · laatste sync {fmtAgo(ig.last_sync_at)}
                  </span>
                </div>
              )}
            </Link>
          );
        })}
      </div>
    </div>
  );
}

export default Tech;
