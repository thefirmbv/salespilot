import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

type DashboardResponse = {
  hosts_total: number;
  hosts_online: number;
  devices_total: number;
  devices_online: number;
  devices_offline: number;
  devices_with_updates: number;
  incidents_24h: number;
  last_polled: string | null;
  by_model: { model_short: string; count: number }[];
};

type HostRow = {
  id: string;
  ubnt_host_id: string;
  name: string;
  model_short: string | null;
  ip_address: string | null;
  owner_email: string | null;
  is_online: boolean;
  is_blocked: boolean;
  last_connection_change: string | null;
  last_polled: string | null;
  device_count: number;
  devices_online: number;
  devices_offline: number;
  company_id: string | null;
  company_name: string | null;
};

type IncidentRow = {
  id: string;
  entity_kind: string;
  entity_id: string;
  entity_name: string | null;
  previous_status: string | null;
  new_status: string;
  occurred_at: string;
  snapshot: Record<string, unknown>;
};

const fmtDateTime = (s: string | null) => {
  if (!s) return "—";
  try {
    return new Date(s).toLocaleString("nl-NL", {
      day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
    });
  } catch { return s; }
};

const fmtAgo = (s: string | null) => {
  if (!s) return "—";
  const ms = Date.now() - new Date(s).getTime();
  if (ms < 60_000) return `${Math.floor(ms / 1000)}s geleden`;
  if (ms < 3600_000) return `${Math.floor(ms / 60_000)}m geleden`;
  if (ms < 86400_000) return `${Math.floor(ms / 3600_000)}h geleden`;
  return `${Math.floor(ms / 86400_000)}d geleden`;
};

export function Unifi() {
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
          <h1 className="text-lg font-medium">📡 UniFi monitoring</h1>
          <div className="mt-0.5 text-xs text-slate-500">
            Live status van alle Dream Machines, sites en devices · poll elke 2 min
          </div>
        </div>
        <div className="flex gap-4 border-b border-slate-200 px-4">
          {[
            ["dashboard", "Dashboard"],
            ["hosts", "Hosts"],
            ["devices", "Devices"],
            ["incidents", "Incidents"],
          ].map(([id, label]) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              className={`py-2.5 text-sm border-b-2 -mb-px ${
                tab === id ? "border-brand-500 text-slate-900" : "border-transparent text-slate-500 hover:text-slate-800"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="p-4">
          {tab === "dashboard" && <DashboardTab />}
          {tab === "hosts" && <HostsTab />}
          {tab === "devices" && <DevicesTab />}
          {tab === "incidents" && <IncidentsTab />}
        </div>
      </div>
    </div>
  );
}

function DashboardTab() {
  const qc = useQueryClient();
  const dq = useQuery<DashboardResponse>({
    queryKey: ["/unifi/dashboard"],
    queryFn: () => api<DashboardResponse>("/unifi/dashboard"),
    refetchInterval: 60_000,
  });
  const syncMut = useMutation({
    mutationFn: () => api("/integrations/unifi/sync", { method: "POST" }),
    onSuccess: () => qc.invalidateQueries(),
  });

  if (dq.isLoading) return <div className="text-sm text-slate-500">Laden…</div>;
  if (dq.isError) return <div className="text-sm text-rose-700">Fout: {(dq.error as Error).message}</div>;
  const d = dq.data!;

  const hostPct = d.hosts_total > 0 ? Math.round((d.hosts_online / d.hosts_total) * 100) : 0;
  const devPct = d.devices_total > 0 ? Math.round((d.devices_online / d.devices_total) * 100) : 0;

  return (
    <div className="space-y-4">
      <div className="flex items-baseline justify-between flex-wrap gap-2">
        <div className="text-xs text-slate-500">
          Laatst gepoll: <strong>{fmtAgo(d.last_polled)}</strong> · {fmtDateTime(d.last_polled)}
        </div>
        <button
          onClick={() => syncMut.mutate()}
          disabled={syncMut.isPending}
          className="rounded-md bg-slate-100 hover:bg-slate-200 px-3 py-1.5 text-sm font-medium disabled:opacity-50"
        >
          {syncMut.isPending ? "Bezig…" : "Sync nu"}
        </button>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <KPI label="Hosts" value={d.hosts_total} sub={`${d.hosts_online} online (${hostPct}%)`} tone={hostPct === 100 ? "emerald" : "amber"} />
        <KPI label="Devices" value={d.devices_total} sub={`${d.devices_online} online (${devPct}%)`} tone={devPct >= 95 ? "emerald" : devPct >= 80 ? "amber" : "rose"} />
        <KPI label="Offline" value={d.devices_offline} sub="laatste poll" tone={d.devices_offline > 0 ? "rose" : "emerald"} />
        <KPI label="Incidents 24u" value={d.incidents_24h} sub={d.devices_with_updates > 0 ? `${d.devices_with_updates} firmware-update beschikbaar` : ""} tone={d.incidents_24h > 5 ? "rose" : d.incidents_24h > 0 ? "amber" : "emerald"} />
      </div>

      <div className="rounded-lg bg-white ring-1 ring-slate-200 p-4">
        <div className="text-xs uppercase tracking-wider text-slate-500 font-semibold mb-3">
          Devices per model
        </div>
        <div className="space-y-1.5">
          {d.by_model.map((m) => {
            const w = (m.count / d.devices_total) * 100;
            return (
              <div key={m.model_short} className="grid grid-cols-[120px_minmax(0,1fr)_60px] gap-2 items-center">
                <code className="text-xs">{m.model_short}</code>
                <div className="h-4 bg-slate-100 rounded overflow-hidden">
                  <div className="h-full bg-brand-500" style={{ width: `${w}%` }} />
                </div>
                <div className="text-right text-sm tabular-nums">{m.count}</div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function HostsTab() {
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<"all" | "online" | "offline">("all");
  const hq = useQuery<HostRow[]>({
    queryKey: ["/unifi/hosts", filter],
    queryFn: () => api<HostRow[]>(`/unifi/hosts${filter !== "all" ? `?status=${filter}` : ""}`),
    refetchInterval: 60_000,
  });
  const rows = (hq.data || []).filter(h =>
    !search || h.name.toLowerCase().includes(search.toLowerCase())
    || (h.company_name || "").toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 flex-wrap">
        <div className="inline-flex rounded-md border border-slate-300 overflow-hidden text-sm">
          {(["all", "online", "offline"] as const).map(f => (
            <button key={f} onClick={() => setFilter(f)}
              className={`px-3 py-1.5 ${filter === f ? "bg-brand-500 text-white" : "bg-white hover:bg-slate-50"}`}>
              {f === "all" ? "Alle" : f === "online" ? "Online" : "Offline"}
            </button>
          ))}
        </div>
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Zoek host…"
          className="ml-auto min-w-[240px] rounded-md border border-slate-300 px-2 py-1.5 text-sm"
        />
      </div>

      <div className="rounded-lg bg-white ring-1 ring-slate-200 overflow-hidden">
        <div className="grid grid-cols-[1.6fr_90px_80px_80px_1fr_120px] gap-3 border-b border-slate-200 px-4 py-2 text-[10px] uppercase tracking-wider text-slate-500">
          <div>Host</div>
          <div>Model</div>
          <div className="text-right">Devices</div>
          <div className="text-right">Online</div>
          <div>Klant</div>
          <div className="text-right">Laatste change</div>
        </div>
        {rows.map(h => (
          <Link
            key={h.id}
            to={`/unifi/hosts/${h.id}`}
            className="grid grid-cols-[1.6fr_90px_80px_80px_1fr_120px] items-center gap-3 border-b border-slate-100 px-4 py-2.5 text-sm hover:bg-slate-50"
          >
            <div className="min-w-0 flex items-center gap-2">
              <span className={`inline-block w-2 h-2 rounded-full ${h.is_online ? "bg-emerald-500" : "bg-rose-500"}`} />
              <span className="truncate font-medium">{h.name || "(geen naam)"}</span>
            </div>
            <code className="text-[11px] text-slate-500">{h.model_short || "?"}</code>
            <div className="text-right tabular-nums">{h.device_count}</div>
            <div className={`text-right tabular-nums ${h.devices_offline > 0 ? "text-amber-700" : "text-emerald-700"}`}>
              {h.devices_online}/{h.device_count}
            </div>
            <div className="text-slate-600 truncate text-xs">{h.company_name || <span className="text-slate-400 italic">niet gekoppeld</span>}</div>
            <div className="text-right text-[11px] text-slate-500">{fmtAgo(h.last_connection_change)}</div>
          </Link>
        ))}
        {rows.length === 0 && (
          <div className="p-8 text-center text-sm text-slate-500">
            Geen hosts gevonden.
          </div>
        )}
      </div>
    </div>
  );
}

type DeviceRow = {
  id: string;
  host_id: string;
  host_name: string | null;
  mac: string | null;
  name: string;
  model: string | null;
  model_short: string | null;
  product_line: string | null;
  ip_address: string | null;
  firmware_status: string | null;
  status: string;
};

function DevicesTab() {
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<"all" | "online" | "offline">("all");
  const dq = useQuery<DeviceRow[]>({
    queryKey: ["/unifi/devices", filter],
    queryFn: () => api<DeviceRow[]>(`/unifi/devices?limit=2000${filter !== "all" ? `&status=${filter}` : ""}`),
    refetchInterval: 60_000,
  });
  const rows = (dq.data || []).filter(d =>
    !search ||
    d.name.toLowerCase().includes(search.toLowerCase()) ||
    (d.model_short || "").toLowerCase().includes(search.toLowerCase()) ||
    (d.host_name || "").toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 flex-wrap">
        <div className="inline-flex rounded-md border border-slate-300 overflow-hidden text-sm">
          {(["all", "online", "offline"] as const).map(f => (
            <button key={f} onClick={() => setFilter(f)}
              className={`px-3 py-1.5 ${filter === f ? "bg-brand-500 text-white" : "bg-white hover:bg-slate-50"}`}>
              {f === "all" ? "Alle" : f === "online" ? "Online" : "Offline"}
            </button>
          ))}
        </div>
        <div className="text-xs text-slate-500">{rows.length} devices</div>
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Zoek device, model of host…"
          className="ml-auto min-w-[280px] rounded-md border border-slate-300 px-2 py-1.5 text-sm"
        />
      </div>

      <div className="rounded-lg bg-white ring-1 ring-slate-200 overflow-hidden">
        <div className="grid grid-cols-[1.6fr_1fr_80px_110px_110px_80px] gap-3 border-b border-slate-200 px-4 py-2 text-[10px] uppercase tracking-wider text-slate-500">
          <div>Device</div>
          <div>Host</div>
          <div>Model</div>
          <div>IP</div>
          <div>Firmware</div>
          <div className="text-right">Status</div>
        </div>
        {rows.slice(0, 1000).map(d => (
          <div key={d.id} className="grid grid-cols-[1.6fr_1fr_80px_110px_110px_80px] items-center gap-3 border-b border-slate-100 px-4 py-1.5 text-sm hover:bg-slate-50">
            <div className="min-w-0 flex items-center gap-2">
              <span className={`inline-block w-2 h-2 rounded-full ${d.status === "online" ? "bg-emerald-500" : "bg-rose-500"}`} />
              <span className="truncate">{d.name || <span className="text-slate-400">{d.mac}</span>}</span>
            </div>
            <Link to={`/unifi/hosts/${d.host_id}`} className="truncate text-xs text-slate-600 hover:underline">
              {d.host_name || "?"}
            </Link>
            <code className="text-[11px] text-slate-500">{d.model_short || "?"}</code>
            <code className="text-[11px] text-slate-500">{d.ip_address || "—"}</code>
            <div className="text-[11px]">
              {d.firmware_status === "updateAvailable" ? (
                <span className="text-amber-700">update</span>
              ) : (
                <span className="text-slate-400">up-to-date</span>
              )}
            </div>
            <div className="text-right">
              <span className={`inline-block px-1.5 py-0.5 rounded-full text-[10px] font-medium ${
                d.status === "online" ? "bg-emerald-50 text-emerald-800" :
                d.status === "offline" ? "bg-rose-50 text-rose-800" :
                "bg-slate-100 text-slate-600"
              }`}>{d.status}</span>
            </div>
          </div>
        ))}
        {rows.length > 1000 && (
          <div className="px-4 py-2 text-xs text-slate-500 italic">
            … nog {rows.length - 1000} verborgen. Verfijn de zoekopdracht.
          </div>
        )}
        {rows.length === 0 && (
          <div className="p-8 text-center text-sm text-slate-500">Geen devices gevonden.</div>
        )}
      </div>
    </div>
  );
}

function IncidentsTab() {
  const [hours, setHours] = useState(72);
  const iq = useQuery<IncidentRow[]>({
    queryKey: ["/unifi/incidents", hours],
    queryFn: () => api<IncidentRow[]>(`/unifi/incidents?hours=${hours}&limit=500`),
    refetchInterval: 60_000,
  });
  const rows = iq.data || [];
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 flex-wrap">
        <div className="inline-flex rounded-md border border-slate-300 overflow-hidden text-sm">
          {([24, 72, 168, 720] as const).map(h => (
            <button key={h} onClick={() => setHours(h)}
              className={`px-3 py-1.5 ${hours === h ? "bg-brand-500 text-white" : "bg-white hover:bg-slate-50"}`}>
              {h === 24 ? "24u" : h === 72 ? "3d" : h === 168 ? "7d" : "30d"}
            </button>
          ))}
        </div>
        <div className="text-xs text-slate-500">{rows.length} events</div>
      </div>
      <div className="rounded-lg bg-white ring-1 ring-slate-200">
        {rows.length === 0 ? (
          <div className="p-8 text-center text-sm text-slate-500">
            Geen state-changes in deze periode 🎉
          </div>
        ) : (
          <ul className="divide-y divide-slate-100">
            {rows.map(r => (
              <li key={r.id} className="px-4 py-2.5 text-sm">
                <div className="flex items-baseline justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <span className={`inline-block w-2 h-2 rounded-full ${
                      r.new_status === "online" ? "bg-emerald-500" : "bg-rose-500"
                    }`} />
                    <span className="font-medium">{r.entity_name || r.entity_id}</span>
                    <span className="text-xs text-slate-500">[{r.entity_kind}]</span>
                  </div>
                  <div className="text-xs text-slate-500">{fmtAgo(r.occurred_at)}</div>
                </div>
                <div className="mt-0.5 text-xs text-slate-600">
                  {r.previous_status || "?"} → <strong>{r.new_status}</strong>
                  {(r.snapshot as any).model_short && <span className="text-slate-500"> · {(r.snapshot as any).model_short}</span>}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function KPI({ label, value, sub, tone }: { label: string; value: number; sub?: string; tone?: string }) {
  const toneClass: Record<string, string> = {
    emerald: "text-emerald-700",
    amber: "text-amber-700",
    rose: "text-rose-700",
    slate: "text-slate-900",
  };
  return (
    <div className="rounded-lg bg-white ring-1 ring-slate-200 p-3">
      <div className="text-xs uppercase tracking-wider text-slate-500 font-semibold">{label}</div>
      <div className={`mt-1 text-2xl font-medium tabular-nums ${toneClass[tone || "slate"]}`}>
        {value.toLocaleString("nl-NL")}
      </div>
      {sub && <div className="text-[11px] text-slate-500 mt-0.5">{sub}</div>}
    </div>
  );
}

export default Unifi;
