import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

type IntegrationSummary = {
  kind: string;
  label: string;
  description: string;
  is_configured: boolean;
  is_enabled: boolean;
  last_sync_at: string | null;
  last_sync_status: string | null;
  extra: Record<string, unknown>;
};

type ComingSoon = {
  kind: string;
  label: string;
  description: string;
};

const COMING_SOON: ComingSoon[] = [];

// Brand colour per kind. Used for the icon tile.
const KIND_STYLES: Record<string, { bg: string; fg: string; icon: string }> = {
  halopsa:     { bg: "bg-brand-50",  fg: "text-brand-700",  icon: "🎧" },
  prospectpro: { bg: "bg-amber-50",  fg: "text-amber-700",  icon: "📡" },
  anthropic:   { bg: "bg-purple-50", fg: "text-purple-700", icon: "✨" },
  mailgun:     { bg: "bg-orange-50", fg: "text-orange-700", icon: "✉️" },
  linkedin:    { bg: "bg-sky-50",    fg: "text-sky-700",    icon: "in" },
  // Wespennest sources
  kvk:         { bg: "bg-rose-50",   fg: "text-rose-700",   icon: "🏛️" },
  openkvk:     { bg: "bg-emerald-50",fg: "text-emerald-700",icon: "🇳🇱" },
  pdok:        { bg: "bg-teal-50",   fg: "text-teal-700",   icon: "📍" },
  crtsh:       { bg: "bg-slate-100", fg: "text-slate-700",  icon: "🔐" },
  hunter:      { bg: "bg-yellow-50", fg: "text-yellow-700", icon: "🎯" },
  apollo:      { bg: "bg-violet-50", fg: "text-violet-700", icon: "🚀" },
};

function relativeShort(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const diffMs = Date.now() - d.getTime();
  const m = Math.floor(diffMs / 60000);
  if (m < 1) return "now";
  if (m < 60) return `${m} min ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} u ago`;
  const days = Math.floor(h / 24);
  if (days < 30) return `${days} d ago`;
  return d.toLocaleDateString();
}

function ConnectorRow({ i }: { i: IntegrationSummary }) {
  const style = KIND_STYLES[i.kind] ?? KIND_STYLES.halopsa;
  const status = i.is_configured && i.is_enabled ? "connected" : i.is_configured ? "paused" : "not_connected";
  const statusStyle = {
    connected:     "bg-emerald-100 text-emerald-800",
    paused:        "bg-amber-100   text-amber-800",
    not_connected: "bg-slate-100   text-slate-600",
  }[status];
  const statusLabel = { connected: "Connected", paused: "Paused", not_connected: "Not connected" }[status];

  return (
    <div className="flex items-center gap-3 rounded-md border border-slate-200 px-4 py-3 hover:bg-slate-50">
      <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-base ${style.bg} ${style.fg}`}>
        {style.icon}
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium">{i.label}</div>
        <div className="text-xs text-slate-500 truncate">
          {i.description}
          {i.last_sync_at && <> · synced {relativeShort(i.last_sync_at)}</>}
        </div>
      </div>
      <span className={`shrink-0 rounded-full px-2.5 py-0.5 text-[11px] font-medium ${statusStyle}`}>
        {statusLabel}
      </span>
      <Link
        to={`/settings/integrations/${i.kind}`}
        className="shrink-0 rounded-md border border-slate-300 px-3 py-1 text-xs text-slate-700 hover:bg-white"
      >
        {i.is_configured ? "Configure" : "Connect"}
      </Link>
    </div>
  );
}

function ComingSoonRow({ c }: { c: ComingSoon }) {
  const style = KIND_STYLES[c.kind];
  return (
    <div className="flex items-center gap-3 rounded-md border border-slate-200 px-4 py-3 opacity-70">
      <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-base ${style.bg} ${style.fg}`}>
        {style.icon}
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium">
          {c.label}{" "}
          <span className="ml-1 rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-500">
            Coming soon
          </span>
        </div>
        <div className="text-xs text-slate-500 truncate">{c.description}</div>
      </div>
      <span className="shrink-0 rounded-full px-2.5 py-0.5 text-[11px] font-medium bg-slate-100 text-slate-500">
        Not connected
      </span>
      <button
        disabled
        className="shrink-0 rounded-md border border-slate-200 px-3 py-1 text-xs text-slate-400 cursor-not-allowed"
      >
        Connect
      </button>
    </div>
  );
}

export function IntegrationsSettings() {
  const q = useQuery<IntegrationSummary[]>({
    queryKey: ["/integrations"],
    queryFn: () => api<IntegrationSummary[]>("/integrations"),
  });

  return (
    <div>
      <div className="mb-4">
        <h2 className="text-base font-medium">Integrations</h2>
        <p className="mt-1 text-xs text-slate-500">
          Connect external systems. Credentials are stored encrypted server-side
          and never sent back to the browser.
        </p>
      </div>

      {q.isLoading && <div className="text-sm text-slate-500">Loading…</div>}

      <div className="space-y-2">
        {(q.data ?? []).map((i) => (
          <ConnectorRow key={i.kind} i={i} />
        ))}
        {COMING_SOON.map((c) => (
          <ComingSoonRow key={c.kind} c={c} />
        ))}
      </div>
    </div>
  );
}
