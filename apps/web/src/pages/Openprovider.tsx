import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

type Dashboard = {
  domains_total: number;
  domains_active: number;
  expiring_30d: number;
  expiring_90d: number;
  linked_count: number;
  unlinked_count: number;
  halopsa_synced_count: number;
  last_polled: string | null;
};

type DomainRow = {
  id: string;
  op_id: string;
  name: string;
  status: string;
  auto_renew: boolean;
  registered_at: string | null;
  expires_at: string | null;
  nameservers: string[];
  company_id: string | null;
  company_name: string | null;
  halopsa_asset_id: number | null;
  halopsa_synced_at: string | null;
};

type CompanyOpt = { id: string; name: string; halopsa_id: number | null };

const fmtAgo = (s: string | null) => {
  if (!s) return "nooit";
  const ms = Date.now() - new Date(s).getTime();
  if (ms < 60_000) return `${Math.floor(ms / 1000)}s`;
  if (ms < 3600_000) return `${Math.floor(ms / 60_000)}m`;
  return `${Math.floor(ms / 3600_000)}u`;
};

const fmtDate = (s: string | null) => {
  if (!s) return "—";
  try { return new Date(s).toLocaleDateString("nl-NL", { day: "2-digit", month: "short", year: "numeric" }); }
  catch { return s; }
};

const daysUntil = (s: string | null) => {
  if (!s) return null;
  const ms = new Date(s).getTime() - Date.now();
  return Math.floor(ms / 86400_000);
};

export function Openprovider() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") ?? "dashboard";
  const setTab = (t: string) => {
    const next = new URLSearchParams(params);
    next.set("tab", t);
    setParams(next, { replace: true });
  };
  return (
    <div className="space-y-4">
      <div className="overflow-hidden rounded-lg bg-white ring-1 ring-slate-200">
        <div className="border-b border-slate-200 px-4 py-3">
          <h1 className="text-lg font-medium">🔖 Openprovider domeinen</h1>
          <div className="mt-0.5 text-xs text-slate-500">
            Domeinregistraties · vervaldatum-monitoring · klant-koppeling + HaloPSA asset
          </div>
        </div>
        <div className="flex gap-4 border-b border-slate-200 px-4">
          {[
            ["dashboard", "Dashboard"],
            ["domains", "Domeinen"],
            ["expiring", "Vervalt binnenkort"],
          ].map(([id, label]) => (
            <button key={id} onClick={() => setTab(id)}
              className={`py-2.5 text-sm border-b-2 -mb-px ${tab === id ? "border-brand-500 text-slate-900" : "border-transparent text-slate-500 hover:text-slate-800"}`}>
              {label}
            </button>
          ))}
        </div>
        <div className="p-4">
          {tab === "dashboard" && <DashboardTab />}
          {tab === "domains" && <DomainsTab />}
          {tab === "expiring" && <DomainsTab expiringOnly />}
        </div>
      </div>
    </div>
  );
}

function DashboardTab() {
  const qc = useQueryClient();
  const dq = useQuery<Dashboard>({
    queryKey: ["/openprovider/dashboard"],
    queryFn: () => api<Dashboard>("/openprovider/dashboard"),
    refetchInterval: 60_000,
  });
  const syncMut = useMutation({
    mutationFn: () => api("/integrations/openprovider/sync", { method: "POST" }),
    onSuccess: () => qc.invalidateQueries(),
  });
  if (dq.isLoading) return <div className="text-sm text-slate-500">Laden…</div>;
  const d = dq.data!;
  return (
    <div className="space-y-4">
      <div className="flex items-baseline justify-between flex-wrap gap-2">
        <div className="text-xs text-slate-500">Laatst gepoll: <strong>{fmtAgo(d.last_polled)}</strong></div>
        <button onClick={() => syncMut.mutate()} disabled={syncMut.isPending}
          className="rounded-md bg-slate-100 hover:bg-slate-200 px-3 py-1.5 text-sm disabled:opacity-50">
          {syncMut.isPending ? "Bezig…" : "Sync nu"}
        </button>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <KPI label="Domeinen" value={d.domains_total} sub={`${d.domains_active} actief`} />
        <KPI label="Gekoppeld" value={d.linked_count} sub={`van ${d.domains_total}`} tone={d.linked_count === d.domains_total ? "emerald" : "amber"} />
        <KPI label="Niet gekoppeld" value={d.unlinked_count} sub="niet gefactureerd!" tone={d.unlinked_count > 0 ? "rose" : "emerald"} />
        <KPI label="Naar HaloPSA" value={d.halopsa_synced_count} />
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <KPI label="Vervalt < 30 dagen" value={d.expiring_30d} tone={d.expiring_30d > 0 ? "rose" : "slate"} />
        <KPI label="Vervalt < 90 dagen" value={d.expiring_90d} tone={d.expiring_90d > 0 ? "amber" : "slate"} />
      </div>
    </div>
  );
}

function DomainsTab({ expiringOnly = false }: { expiringOnly?: boolean }) {
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [showManual, setShowManual] = useState(false);

  const dq = useQuery<DomainRow[]>({
    queryKey: ["/openprovider/domains", expiringOnly],
    queryFn: () => api<DomainRow[]>(
      `/openprovider/domains${expiringOnly ? "?expiring_days=90" : ""}`
    ),
    refetchInterval: 60_000,
  });
  const rows = (dq.data || []).filter(d =>
    !search || d.name.toLowerCase().includes(search.toLowerCase()) ||
    (d.company_name || "").toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 flex-wrap">
        <input value={search} onChange={(e) => setSearch(e.target.value)}
          placeholder="Zoek domein of klant…"
          className="min-w-[260px] rounded-md border border-slate-300 px-2 py-1.5 text-sm flex-1" />
        {!expiringOnly && (
          <>
            <Link to="/openprovider/register"
              className="rounded-md bg-emerald-600 hover:bg-emerald-700 text-white px-3 py-1.5 text-sm">
              + Registreer domein
            </Link>
            <button onClick={() => setShowManual(true)}
              className="rounded-md bg-brand-500 hover:bg-brand-600 text-white px-3 py-1.5 text-sm">
              + Handmatig
            </button>
            <Link to="/openprovider/audit"
              className="rounded-md bg-slate-100 hover:bg-slate-200 px-3 py-1.5 text-sm">
              Audit log
            </Link>
          </>
        )}
      </div>

      {showManual && <ManualForm onClose={() => { setShowManual(false); qc.invalidateQueries({ queryKey: ["/openprovider/domains"] }); }} />}

      <div className="rounded-lg bg-white ring-1 ring-slate-200 overflow-hidden">
        <div className="grid grid-cols-[1.4fr_110px_100px_1fr_90px_70px_90px] gap-3 border-b border-slate-200 px-4 py-2 text-[10px] uppercase tracking-wider text-slate-500">
          <div>Domein</div>
          <div>Vervalt</div>
          <div>Auto-renew</div>
          <div>Klant</div>
          <div className="text-right">HaloPSA</div>
          <div className="text-right">Status</div>
          <div className="text-right">Acties</div>
        </div>
        {rows.length === 0 ? (
          <div className="p-8 text-center text-sm text-slate-500">
            {expiringOnly ? "Geen domeinen vervallen binnen 90 dagen 🎉" : "Geen domeinen. Voeg handmatig toe of sync via API."}
          </div>
        ) : rows.map(d => {
          const days = daysUntil(d.expires_at);
          const urgent = days !== null && days <= 30;
          const warn = days !== null && days <= 90;
          return (
            <div key={d.id} className="grid grid-cols-[1.4fr_110px_100px_1fr_90px_70px_90px] items-center gap-3 border-b border-slate-100 px-4 py-2 text-sm hover:bg-slate-50">
              <div className="flex items-center gap-2 min-w-0">
                <span className={`inline-block w-2 h-2 rounded-full ${d.status === "active" ? "bg-emerald-500" : "bg-rose-500"}`} />
                <span className="truncate font-medium">{d.name}</span>
                {d.op_id.startsWith("manual:") && <span className="text-[10px] text-slate-400">[handmatig]</span>}
              </div>
              <div className={`text-xs ${urgent ? "text-rose-700 font-semibold" : warn ? "text-amber-700" : "text-slate-500"}`}>
                {fmtDate(d.expires_at)}{days !== null && <span className="ml-1">({days}d)</span>}
              </div>
              <div className="text-xs">{d.auto_renew ? "✓" : <span className="text-rose-700">✗</span>}</div>
              <div className="text-xs">
                {d.company_id ? (
                  <Link to={`/companies/${d.company_id}`} className="text-slate-700 hover:underline">{d.company_name}</Link>
                ) : (
                  <CompanyPicker domainId={d.id} onLinked={() => qc.invalidateQueries({ queryKey: ["/openprovider/domains"] })} />
                )}
              </div>
              <div className="text-right text-[11px]">
                {d.halopsa_asset_id ? <span className="text-emerald-700">#{d.halopsa_asset_id}</span> : <span className="text-slate-400">—</span>}
              </div>
              <div className="text-right">
                <span className={`inline-block px-1.5 py-0.5 rounded-full text-[10px] font-medium ${
                  d.status === "active" ? "bg-emerald-50 text-emerald-800" : "bg-rose-50 text-rose-800"
                }`}>{d.status}</span>
              </div>
              <div className="text-right">
                <DomainActions domain={d} />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function DomainActions({ domain }: { domain: DomainRow }) {
  const qc = useQueryClient();
  const isLive = !domain.op_id.startsWith("manual:") && !domain.op_id.startsWith("pending:");

  const renewMut = useMutation({
    mutationFn: () =>
      api(`/openprovider/domains/${domain.id}/autorenew`, {
        method: "PUT",
        body: JSON.stringify({ auto_renew: !domain.auto_renew }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["/openprovider/domains"] }),
    onError: (e: Error) => alert(e.message),
  });

  const cancelMut = useMutation({
    mutationFn: () =>
      api(`/openprovider/domains/${domain.id}/cancel?confirm=true&confirm_irreversible=true`, {
        method: "DELETE",
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["/openprovider/domains"] }),
    onError: (e: Error) => alert(e.message),
  });

  if (!isLive) {
    return <span className="text-[10px] text-slate-400">handmatig</span>;
  }

  return (
    <div className="flex gap-1 justify-end">
      <button
        onClick={() => {
          if (confirm(`Auto-renew ${domain.auto_renew ? "UITZETTEN" : "AANZETTEN"} voor ${domain.name}?\n\n${domain.auto_renew ? "Domein vervalt op vervaldatum als renewal niet handmatig wordt gedaan." : "Domein verlengt automatisch bij vervaldatum."}`)) {
            renewMut.mutate();
          }
        }}
        disabled={renewMut.isPending}
        className="rounded bg-slate-100 hover:bg-slate-200 px-1.5 py-0.5 text-[10px] disabled:opacity-50"
        title={domain.auto_renew ? "Auto-renew uitzetten (zachte opzegging)" : "Auto-renew weer aanzetten"}
      >
        {domain.auto_renew ? "Renew uit" : "Renew aan"}
      </button>
      <button
        onClick={() => {
          const c1 = confirm(`HARD CANCEL ${domain.name}?\n\nDit werkt alleen binnen Openprovider grace-period (~5 dagen na registratie) en is NIET reversible.`);
          if (!c1) return;
          const c2 = confirm("ZEKER WETEN? Deze actie kan niet ongedaan worden.");
          if (c2) cancelMut.mutate();
        }}
        disabled={cancelMut.isPending}
        className="rounded bg-rose-100 hover:bg-rose-200 px-1.5 py-0.5 text-[10px] text-rose-700 disabled:opacity-50"
        title="Hard cancel binnen grace-period"
      >
        ✗
      </button>
    </div>
  );
}

function CompanyPicker({ domainId, onLinked }: { domainId: string; onLinked: () => void }) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const cq = useQuery<CompanyOpt[]>({
    queryKey: ["companies-op-picker", search],
    queryFn: async () => {
      const r = await api<{ items: CompanyOpt[] } | CompanyOpt[]>(
        `/companies?limit=20${search ? `&q=${encodeURIComponent(search)}` : ""}`
      );
      return Array.isArray(r) ? r : r.items;
    },
    enabled: open,
  });
  const linkMut = useMutation({
    mutationFn: (cid: string) =>
      api(`/openprovider/domains/${domainId}/link-company`, {
        method: "POST",
        body: JSON.stringify({ company_id: cid }),
      }),
    onSuccess: () => { onLinked(); setOpen(false); setSearch(""); },
  });
  if (!open) {
    return <button onClick={() => setOpen(true)} className="text-brand-600 hover:underline text-xs">Koppel klant</button>;
  }
  return (
    <div className="rounded border border-slate-300 bg-white p-2 space-y-1">
      <input value={search} onChange={(e) => setSearch(e.target.value)}
        placeholder="Zoek klant…" autoFocus
        className="w-full rounded border border-slate-200 px-1.5 py-1 text-xs" />
      <div className="max-h-48 overflow-y-auto space-y-0.5">
        {(cq.data || []).map(c => (
          <button key={c.id} onClick={() => linkMut.mutate(c.id)} disabled={linkMut.isPending}
            className="w-full text-left px-2 py-1 text-xs hover:bg-slate-100 rounded">
            {c.name}
          </button>
        ))}
      </div>
      <button onClick={() => setOpen(false)} className="text-[10px] text-slate-500">Annuleren</button>
    </div>
  );
}

function ManualForm({ onClose }: { onClose: () => void }) {
  const [name, setName] = useState("");
  const [expiresAt, setExpiresAt] = useState("");
  const [autoRenew, setAutoRenew] = useState(true);
  const [companyId, setCompanyId] = useState<string>("");
  const [companySearch, setCompanySearch] = useState("");

  const cq = useQuery<CompanyOpt[]>({
    queryKey: ["companies-op-manual", companySearch],
    queryFn: async () => {
      const r = await api<{ items: CompanyOpt[] } | CompanyOpt[]>(
        `/companies?limit=15${companySearch ? `&q=${encodeURIComponent(companySearch)}` : ""}`
      );
      return Array.isArray(r) ? r : r.items;
    },
  });
  const createMut = useMutation({
    mutationFn: () =>
      api("/openprovider/domains/manual", {
        method: "POST",
        body: JSON.stringify({
          name, expires_at: expiresAt ? new Date(expiresAt).toISOString() : null,
          auto_renew: autoRenew, company_id: companyId || null,
        }),
      }),
    onSuccess: onClose,
  });
  return (
    <div className="rounded-lg bg-blue-50 border border-blue-200 p-4 space-y-3">
      <div className="text-sm font-medium">Handmatig domein toevoegen</div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-1">Domein *</label>
          <input value={name} onChange={(e) => setName(e.target.value.toLowerCase())} placeholder="bv. klant.nl"
            className="w-full rounded border border-slate-300 px-2 py-1.5 text-sm" />
        </div>
        <div>
          <label className="block text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-1">Vervalt op</label>
          <input type="date" value={expiresAt} onChange={(e) => setExpiresAt(e.target.value)}
            className="w-full rounded border border-slate-300 px-2 py-1.5 text-sm" />
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={autoRenew} onChange={(e) => setAutoRenew(e.target.checked)} />
          Auto-renew
        </label>
      </div>
      <div>
        <label className="block text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-1">Klant koppelen (optioneel)</label>
        <input value={companySearch} onChange={(e) => setCompanySearch(e.target.value)}
          placeholder="Zoek klant…"
          className="w-full rounded border border-slate-300 px-2 py-1.5 text-sm" />
        <div className="mt-1 max-h-32 overflow-y-auto bg-white rounded border border-slate-200">
          {(cq.data || []).map(c => (
            <button key={c.id} onClick={() => setCompanyId(c.id)}
              className={`w-full text-left px-2 py-1 text-xs hover:bg-slate-100 ${companyId === c.id ? "bg-brand-100 font-semibold" : ""}`}>
              {c.name}
            </button>
          ))}
        </div>
      </div>
      <div className="flex gap-2 justify-end">
        <button onClick={onClose} className="rounded-md bg-white border border-slate-300 px-3 py-1.5 text-sm">Annuleren</button>
        <button onClick={() => createMut.mutate()} disabled={!name || createMut.isPending}
          className="rounded-md bg-brand-500 hover:bg-brand-600 text-white px-3 py-1.5 text-sm disabled:opacity-50">
          {createMut.isPending ? "Bezig…" : "Toevoegen"}
        </button>
      </div>
    </div>
  );
}

function KPI({ label, value, sub, tone }: { label: string; value: number; sub?: string; tone?: string }) {
  const toneCls: Record<string, string> = { emerald: "text-emerald-700", amber: "text-amber-700", rose: "text-rose-700", slate: "text-slate-900" };
  return (
    <div className="rounded-lg bg-white ring-1 ring-slate-200 p-3">
      <div className="text-xs uppercase tracking-wider text-slate-500 font-semibold">{label}</div>
      <div className={`mt-1 text-2xl font-medium tabular-nums ${toneCls[tone || "slate"]}`}>{value.toLocaleString("nl-NL")}</div>
      {sub && <div className="text-[11px] text-slate-500 mt-0.5">{sub}</div>}
    </div>
  );
}

export default Openprovider;
