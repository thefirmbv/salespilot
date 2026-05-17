import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

type Dashboard = {
  subscriptions_total: number;
  subscriptions_active: number;
  subscriptions_suspended: number;
  subscriptions_disabled: number;
  linked_count: number;
  unlinked_count: number;
  halopsa_synced_count: number;
  last_polled: string | null;
  state_events_24h: number;
};

type SubRow = {
  id: string;
  plesk_id: string;
  name: string;
  main_domain: string | null;
  plan_name: string | null;
  status: string;
  owner_email: string | null;
  disk_used_mb: number;
  mailboxes_count: number;
  company_id: string | null;
  company_name: string | null;
  halopsa_asset_id: number | null;
  halopsa_product_id: number | null;
  halopsa_synced_at: string | null;
  last_polled: string | null;
};

type CompanyOpt = { id: string; name: string; halopsa_id: number | null };
type LinkSummary = {
  company_id: string;
  company_name: string;
  halopsa_id: number | null;
  subscriptions: { subscription_id: string; name: string; main_domain: string | null; plan_name: string | null; status: string; halopsa_asset_id: number | null }[];
  subscriptions_count: number;
  synced_count: number;
};

const fmtAgo = (s: string | null) => {
  if (!s) return "nooit";
  const ms = Date.now() - new Date(s).getTime();
  if (ms < 60_000) return `${Math.floor(ms / 1000)}s`;
  if (ms < 3600_000) return `${Math.floor(ms / 60_000)}m`;
  if (ms < 86400_000) return `${Math.floor(ms / 3600_000)}u`;
  return `${Math.floor(ms / 86400_000)}d`;
};

export function Plesk() {
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
        <div className="border-b border-slate-200 px-4 py-3 flex items-baseline justify-between gap-3 flex-wrap">
          <div>
            <h1 className="text-lg font-medium">🌐 Plesk hosting</h1>
            <div className="mt-0.5 text-xs text-slate-500">
              1 subscription = 1 website = 1 factuurregel · klant-koppeling + HaloPSA asset-sync
            </div>
          </div>
          <Link to="/settings/integrations/plesk/servers"
            className="rounded-md bg-slate-100 hover:bg-slate-200 px-3 py-1.5 text-sm">
            ⚙ Servers beheren
          </Link>
        </div>
        <div className="flex gap-4 border-b border-slate-200 px-4">
          {[
            ["dashboard", "Dashboard"],
            ["subs", "Subscriptions"],
            ["links", "Koppelingen"],
          ].map(([id, label]) => (
            <button key={id} onClick={() => setTab(id)}
              className={`py-2.5 text-sm border-b-2 -mb-px ${tab === id ? "border-brand-500 text-slate-900" : "border-transparent text-slate-500 hover:text-slate-800"}`}>
              {label}
            </button>
          ))}
        </div>
        <div className="p-4">
          {tab === "dashboard" && <DashboardTab />}
          {tab === "subs" && <SubsTab />}
          {tab === "links" && <LinksTab />}
        </div>
      </div>
    </div>
  );
}

function DashboardTab() {
  const qc = useQueryClient();
  const dq = useQuery<Dashboard>({
    queryKey: ["/plesk/dashboard"],
    queryFn: () => api<Dashboard>("/plesk/dashboard"),
    refetchInterval: 60_000,
  });
  const syncMut = useMutation({
    mutationFn: () => api("/integrations/plesk/sync", { method: "POST" }),
    onSuccess: () => qc.invalidateQueries(),
  });
  if (dq.isLoading) return <div className="text-sm text-slate-500">Laden…</div>;
  const d = dq.data!;
  return (
    <div className="space-y-4">
      <div className="flex items-baseline justify-between flex-wrap gap-2">
        <div className="text-xs text-slate-500">
          Laatst gepoll: <strong>{fmtAgo(d.last_polled)}</strong>
        </div>
        <button onClick={() => syncMut.mutate()} disabled={syncMut.isPending}
          className="rounded-md bg-slate-100 hover:bg-slate-200 px-3 py-1.5 text-sm disabled:opacity-50">
          {syncMut.isPending ? "Bezig…" : "Sync nu"}
        </button>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <KPI label="Subscriptions" value={d.subscriptions_total} sub={`${d.subscriptions_active} actief`} />
        <KPI label="Gekoppeld" value={d.linked_count} sub={`van ${d.subscriptions_total}`} tone={d.linked_count === d.subscriptions_total ? "emerald" : "amber"} />
        <KPI label="Niet gekoppeld" value={d.unlinked_count} sub="niet gefactureerd!" tone={d.unlinked_count > 0 ? "rose" : "emerald"} />
        <KPI label="Naar HaloPSA" value={d.halopsa_synced_count} sub="als asset" />
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <KPI label="Actief" value={d.subscriptions_active} tone="emerald" />
        <KPI label="Suspended" value={d.subscriptions_suspended} tone={d.subscriptions_suspended > 0 ? "amber" : "slate"} />
        <KPI label="Disabled" value={d.subscriptions_disabled} tone={d.subscriptions_disabled > 0 ? "rose" : "slate"} />
        <KPI label="State-events 24u" value={d.state_events_24h} />
      </div>
    </div>
  );
}

function SubsTab() {
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<"all" | "linked" | "unlinked">("all");
  const [showManual, setShowManual] = useState(false);

  const sq = useQuery<SubRow[]>({
    queryKey: ["/plesk/subscriptions", filter],
    queryFn: () => api<SubRow[]>(
      `/plesk/subscriptions${filter === "linked" ? "?linked=true" : filter === "unlinked" ? "?linked=false" : ""}`
    ),
    refetchInterval: 60_000,
  });
  const rows = (sq.data || []).filter(s =>
    !search ||
    s.name.toLowerCase().includes(search.toLowerCase()) ||
    (s.main_domain || "").toLowerCase().includes(search.toLowerCase()) ||
    (s.company_name || "").toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="space-y-3">
      <SyncAllBar />
      <div className="flex items-center gap-2 flex-wrap">
        <div className="inline-flex rounded-md border border-slate-300 overflow-hidden text-sm">
          {(["all", "linked", "unlinked"] as const).map(f => (
            <button key={f} onClick={() => setFilter(f)}
              className={`px-3 py-1.5 ${filter === f ? "bg-brand-500 text-white" : "bg-white hover:bg-slate-50"}`}>
              {f === "all" ? "Alle" : f === "linked" ? "Gekoppeld" : "Niet gekoppeld"}
            </button>
          ))}
        </div>
        <input value={search} onChange={(e) => setSearch(e.target.value)}
          placeholder="Zoek subscription, domein, klant…"
          className="min-w-[260px] rounded-md border border-slate-300 px-2 py-1.5 text-sm flex-1" />
        <button onClick={() => setShowManual(true)}
          className="rounded-md bg-brand-500 hover:bg-brand-600 text-white px-3 py-1.5 text-sm">
          + Handmatig
        </button>
      </div>

      {showManual && <ManualForm onClose={() => { setShowManual(false); qc.invalidateQueries({ queryKey: ["/plesk/subscriptions"] }); }} />}

      <div className="rounded-lg bg-white ring-1 ring-slate-200 overflow-hidden">
        <div className="grid grid-cols-[1.4fr_1fr_100px_1fr_140px_90px_90px] gap-3 border-b border-slate-200 px-4 py-2 text-[10px] uppercase tracking-wider text-slate-500">
          <div>Subscription</div>
          <div>Hoofd-domein</div>
          <div>Plan</div>
          <div>Klant</div>
          <div>Product (tarief)</div>
          <div className="text-right">HaloPSA</div>
          <div className="text-right">Status</div>
        </div>
        {rows.length === 0 ? (
          <div className="p-8 text-center text-sm text-slate-500">
            Geen subscriptions. Klik <strong>+ Handmatig</strong> om er één toe te voegen.
          </div>
        ) : rows.map(s => (
          <div key={s.id} className="grid grid-cols-[1.4fr_1fr_100px_1fr_140px_90px_90px] items-center gap-3 border-b border-slate-100 px-4 py-2 text-sm hover:bg-slate-50">
            <div className="min-w-0 flex items-center gap-2">
              <span className={`inline-block w-2 h-2 rounded-full ${s.status === "active" ? "bg-emerald-500" : s.status === "suspended" ? "bg-amber-500" : "bg-rose-500"}`} />
              <span className="truncate font-medium">{s.name}</span>
              {s.plesk_id.startsWith("manual:") && <span className="text-[10px] text-slate-400">[handmatig]</span>}
            </div>
            <code className="text-[11px] text-slate-500 truncate">{s.main_domain || "—"}</code>
            <code className="text-[11px] text-slate-500">{s.plan_name || "—"}</code>
            <div className="text-xs">
              {s.company_id ? (
                <Link to={`/companies/${s.company_id}`} className="text-slate-700 hover:underline">{s.company_name}</Link>
              ) : (
                <CompanyPicker subId={s.id} onLinked={() => qc.invalidateQueries({ queryKey: ["/plesk/subscriptions"] })} />
              )}
            </div>
            <div className="text-xs">
              <ProductPicker
                productId={s.halopsa_product_id}
                onChange={(pid) => api(`/plesk/subscriptions/${s.id}/product`, { method: "PUT", body: JSON.stringify({ halopsa_product_id: pid }) }).then(() => qc.invalidateQueries({ queryKey: ["/plesk/subscriptions"] }))}
                listUrl="/plesk/halopsa-products"
              />
            </div>
            <div className="text-right text-[11px]">
              {s.halopsa_asset_id ? (
                <span className="text-emerald-700">asset #{s.halopsa_asset_id}</span>
              ) : (
                <span className="text-slate-400">niet gesynced</span>
              )}
            </div>
            <div className="text-right">
              <span className={`inline-block px-1.5 py-0.5 rounded-full text-[10px] font-medium ${
                s.status === "active" ? "bg-emerald-50 text-emerald-800" :
                s.status === "suspended" ? "bg-amber-50 text-amber-800" :
                "bg-rose-50 text-rose-800"
              }`}>{s.status}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function CompanyPicker({ subId, onLinked }: { subId: string; onLinked: () => void }) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const cq = useQuery<CompanyOpt[]>({
    queryKey: ["companies-picker", search],
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
      api(`/plesk/subscriptions/${subId}/link-company`, {
        method: "POST",
        body: JSON.stringify({ company_id: cid }),
      }),
    onSuccess: () => { onLinked(); setOpen(false); setSearch(""); },
  });

  if (!open) {
    return (
      <button onClick={() => setOpen(true)} className="text-brand-600 hover:underline text-xs">
        Koppel klant
      </button>
    );
  }
  return (
    <div className="rounded border border-slate-300 bg-white p-2 space-y-1">
      <input value={search} onChange={(e) => setSearch(e.target.value)}
        placeholder="Zoek klant…" autoFocus
        className="w-full rounded border border-slate-200 px-1.5 py-1 text-xs" />
      <div className="max-h-48 overflow-y-auto space-y-0.5">
        {(cq.data || []).map(c => (
          <button key={c.id} onClick={() => linkMut.mutate(c.id)}
            disabled={linkMut.isPending}
            className="w-full text-left px-2 py-1 text-xs hover:bg-slate-100 rounded">
            {c.name} {c.halopsa_id && <span className="text-slate-400">(#{c.halopsa_id})</span>}
          </button>
        ))}
      </div>
      <button onClick={() => setOpen(false)} className="text-[10px] text-slate-500">Annuleren</button>
    </div>
  );
}

function ManualForm({ onClose }: { onClose: () => void }) {
  const [name, setName] = useState("");
  const [mainDomain, setMainDomain] = useState("");
  const [planName, setPlanName] = useState("");
  const [ownerEmail, setOwnerEmail] = useState("");
  const [companyId, setCompanyId] = useState<string>("");
  const [companySearch, setCompanySearch] = useState("");

  const cq = useQuery<CompanyOpt[]>({
    queryKey: ["companies-manual", companySearch],
    queryFn: async () => {
      const r = await api<{ items: CompanyOpt[] } | CompanyOpt[]>(
        `/companies?limit=15${companySearch ? `&q=${encodeURIComponent(companySearch)}` : ""}`
      );
      return Array.isArray(r) ? r : r.items;
    },
  });

  const createMut = useMutation({
    mutationFn: () =>
      api("/plesk/subscriptions/manual", {
        method: "POST",
        body: JSON.stringify({
          name, main_domain: mainDomain || null,
          plan_name: planName || null,
          owner_email: ownerEmail || null,
          company_id: companyId || null,
        }),
      }),
    onSuccess: onClose,
  });

  return (
    <div className="rounded-lg bg-blue-50 border border-blue-200 p-4 space-y-3">
      <div className="text-sm font-medium">Handmatig Plesk subscription toevoegen</div>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Naam" value={name} onChange={setName} placeholder="bv. klantnaam-hosting" required />
        <Field label="Hoofd-domein" value={mainDomain} onChange={setMainDomain} placeholder="klant.nl" />
        <Field label="Plan-naam" value={planName} onChange={setPlanName} placeholder="Basis / Pro / …" />
        <Field label="Owner email" value={ownerEmail} onChange={setOwnerEmail} placeholder="contact@klant.nl" />
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

function LinksTab() {
  const lq = useQuery<LinkSummary[]>({
    queryKey: ["/plesk/links"],
    queryFn: () => api<LinkSummary[]>("/plesk/links"),
    refetchInterval: 60_000,
  });
  return (
    <div className="space-y-3">
      <div className="rounded-md border border-blue-200 bg-blue-50 p-3 text-sm text-blue-900">
        Eén klant kan meerdere hosting-subscriptions hebben. Hieronder per klant gegroepeerd
        met totalen voor de recurring HaloPSA-factuur.
      </div>
      {(lq.data || []).map(s => (
        <div key={s.company_id} className="rounded-lg bg-white ring-1 ring-slate-200 overflow-hidden">
          <div className="border-b border-slate-200 px-4 py-2">
            <strong className="text-sm">{s.company_name}</strong>
            <span className="ml-3 text-xs text-slate-500">
              {s.subscriptions_count} subscriptions · {s.synced_count} naar HaloPSA
              {s.halopsa_id ? <> · Halo #{s.halopsa_id}</> : <span className="text-amber-700"> · geen Halo-link</span>}
            </span>
          </div>
          <ul className="divide-y divide-slate-100">
            {s.subscriptions.map(sub => (
              <li key={sub.subscription_id} className="px-4 py-2 text-sm flex items-center gap-3">
                <span className={`inline-block w-2 h-2 rounded-full ${sub.status === "active" ? "bg-emerald-500" : "bg-rose-500"}`} />
                <span className="font-medium flex-1">{sub.name}</span>
                <code className="text-[11px] text-slate-500">{sub.main_domain}</code>
                <span className="text-xs text-slate-500">{sub.plan_name}</span>
                {sub.halopsa_asset_id && <span className="text-[10px] text-emerald-700">#{sub.halopsa_asset_id}</span>}
              </li>
            ))}
          </ul>
        </div>
      ))}
      {(lq.data?.length ?? 0) === 0 && (
        <div className="rounded-lg bg-white ring-1 ring-slate-200 p-6 text-center text-sm text-slate-500">
          Nog geen koppelingen. Ga naar tab "Subscriptions" en klik per rij op "Koppel klant".
        </div>
      )}
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

function Field({ label, value, onChange, placeholder, required }: any) {
  return (
    <div>
      <label className="block text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-1">{label}{required && " *"}</label>
      <input value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder}
        className="w-full rounded border border-slate-300 px-2 py-1.5 text-sm" />
    </div>
  );
}


function SyncAllBar() {
  const qc = useQueryClient();
  const syncMut = useMutation({
    mutationFn: () => api<any>("/plesk/sync-halopsa-assets", { method: "POST" }),
    onSuccess: (r) => {
      const lines = [
        r.ok ? "✓" : "✗",
        `Assets ge-sync: ${r.assets_upserted} (${r.assets_created} nieuw, ${r.assets_updated} update)`,
        r.errors?.length ? `${r.errors.length} fouten — zie console` : "",
        r.detail || "",
      ].filter(Boolean).join("\n");
      alert(lines);
      if (r.errors?.length) console.error("Sync errors:", r.errors);
      qc.invalidateQueries({ queryKey: ["/plesk/subscriptions"] });
    },
  });
  return (
    <div className="flex items-baseline justify-between gap-3 flex-wrap rounded-md border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900">
      <div>
        <strong>Sync naar HaloPSA</strong>
        <div className="text-xs mt-0.5">
          Maakt 1 asset per gekoppelde subscription onder AssetGroup
          "Domeinnaam en Hosting", AssetType "Plesk Subscription".
          Asset.name = subscription naam, item_id = gekozen product.
        </div>
      </div>
      <button
        onClick={() => {
          if (confirm("Sync alle gekoppelde subscriptions naar HaloPSA?\n\nVoor elke sub wordt een asset upsert met:\n - AssetGroup: Domeinnaam en Hosting\n - AssetType: Plesk Subscription\n - Naam: subscription naam\n - Tarief: het gekozen Product per asset")) {
            syncMut.mutate();
          }
        }}
        disabled={syncMut.isPending}
        className="rounded-md bg-emerald-600 hover:bg-emerald-700 text-white px-3 py-1.5 text-sm font-medium disabled:opacity-50"
      >
        {syncMut.isPending ? "Bezig…" : "Sync alles"}
      </button>
    </div>
  );
}

function ProductPicker({
  productId, onChange, listUrl,
}: {
  productId: number | null;
  onChange: (id: number | null) => void;
  listUrl: string;
}) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const pq = useQuery<{ id: number; name: string; price: number }[]>({
    queryKey: [listUrl, search],
    queryFn: () => api<any[]>(`${listUrl}${search ? `?search=${encodeURIComponent(search)}` : ""}`),
    enabled: open,
  });
  const current = (pq.data || []).find(p => p.id === productId);
  if (!open) {
    return (
      <button onClick={() => setOpen(true)}
        className={`text-xs text-left ${productId ? "text-slate-700" : "text-amber-700 hover:underline"}`}>
        {productId ? (
          <span title={current?.name || `Product #${productId}`}>
            #{productId}{current?.price ? ` (€${current.price})` : ""}
          </span>
        ) : "Kies tarief…"}
      </button>
    );
  }
  return (
    <div className="rounded border border-slate-300 bg-white p-2 space-y-1 z-10 relative">
      <input value={search} onChange={(e) => setSearch(e.target.value)} autoFocus
        placeholder="Zoek product…"
        className="w-full rounded border border-slate-200 px-1.5 py-1 text-xs" />
      <div className="max-h-48 overflow-y-auto space-y-0.5">
        {productId && (
          <button onClick={() => { onChange(null); setOpen(false); }}
            className="w-full text-left px-2 py-1 text-xs hover:bg-rose-50 rounded text-rose-700">
            ✗ Geen product (asset wordt niet gefactureerd)
          </button>
        )}
        {(pq.data || []).map(p => (
          <button key={p.id} onClick={() => { onChange(p.id); setOpen(false); }}
            className={`w-full text-left px-2 py-1 text-xs hover:bg-slate-100 rounded ${p.id === productId ? "bg-brand-100 font-semibold" : ""}`}>
            <div>{p.name}</div>
            {p.price > 0 && <div className="text-[10px] text-slate-500">€{p.price}</div>}
          </button>
        ))}
        {pq.isLoading && <div className="text-xs text-slate-500 p-2">Laden…</div>}
        {(pq.data?.length ?? 0) === 0 && !pq.isLoading && <div className="text-xs text-slate-500 p-2">Geen resultaten</div>}
      </div>
      <button onClick={() => setOpen(false)} className="text-[10px] text-slate-500">Sluiten</button>
    </div>
  );
}

export { ProductPicker };

export default Plesk;
