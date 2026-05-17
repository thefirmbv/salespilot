import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

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

type DeviceRow = {
  id: string;
  ubnt_device_id: string;
  host_id: string;
  host_name: string | null;
  mac: string | null;
  name: string;
  model: string | null;
  model_short: string | null;
  product_line: string | null;
  ip_address: string | null;
  firmware_version: string | null;
  firmware_status: string | null;
  is_console: boolean;
  status: string;
  startup_time: string | null;
  halopsa_asset_id: number | null;
};

type CompanyOpt = {
  id: string;
  name: string;
  halopsa_id: number | null;
};

const fmtAgo = (s: string | null) => {
  if (!s) return "—";
  const ms = Date.now() - new Date(s).getTime();
  if (ms < 60_000) return `${Math.floor(ms / 1000)}s`;
  if (ms < 3600_000) return `${Math.floor(ms / 60_000)}m`;
  if (ms < 86400_000) return `${Math.floor(ms / 3600_000)}u`;
  return `${Math.floor(ms / 86400_000)}d`;
};

export function UnifiHostDetail() {
  const { hostId = "" } = useParams<{ hostId: string }>();
  
  const qc = useQueryClient();

  // Eén query voor alle hosts (een aparte detail-endpoint heb ik niet
  // gebouwd; voor de UI is dit goed genoeg)
  const hostsQ = useQuery<HostRow[]>({
    queryKey: ["/unifi/hosts"],
    queryFn: () => api<HostRow[]>("/unifi/hosts"),
    refetchInterval: 60_000,
  });
  const host = (hostsQ.data || []).find((h) => h.id === hostId) || null;

  const devicesQ = useQuery<DeviceRow[]>({
    queryKey: ["/unifi/hosts", hostId, "devices"],
    queryFn: () => api<DeviceRow[]>(`/unifi/hosts/${hostId}/devices`),
    enabled: !!hostId,
    refetchInterval: 60_000,
  });

  if (hostsQ.isLoading) return <div className="p-6 text-sm text-slate-500">Laden…</div>;
  if (!host) {
    return (
      <div className="rounded-md bg-rose-50 border border-rose-200 p-4 text-sm text-rose-900">
        Host niet gevonden. <Link to="/unifi?tab=hosts" className="underline">Terug naar lijst</Link>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="rounded-lg bg-white ring-1 ring-slate-200">
        <div className="border-b border-slate-200 px-4 py-3 flex items-baseline justify-between gap-3 flex-wrap">
          <div className="flex items-baseline gap-3">
            <span className={`inline-block w-2.5 h-2.5 rounded-full ${host.is_online ? "bg-emerald-500" : "bg-rose-500"}`} />
            <h1 className="text-lg font-medium">{host.name || "(geen naam)"}</h1>
            <code className="text-xs text-slate-500">{host.model_short || "?"}</code>
          </div>
          <Link to="/unifi?tab=hosts" className="text-sm text-slate-500 hover:text-slate-800">← terug</Link>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 px-4 py-3 text-sm">
          <Field label="IP" value={host.ip_address || "—"} mono />
          <Field label="Owner" value={host.owner_email || "—"} />
          <Field label="Devices" value={`${host.devices_online} / ${host.device_count} online`} />
          <Field label="Laatste change" value={fmtAgo(host.last_connection_change)} />
        </div>
      </div>

      {/* Koppeling */}
      <CompanyLinkCard host={host} onChanged={() => qc.invalidateQueries({ queryKey: ["/unifi/hosts"] })} />

      {/* Devices */}
      <div className="rounded-lg bg-white ring-1 ring-slate-200 overflow-hidden">
        <div className="border-b border-slate-200 px-4 py-2 text-xs uppercase tracking-wider text-slate-500 font-semibold">
          Devices op deze host ({devicesQ.data?.length ?? 0})
        </div>
        {devicesQ.isLoading ? (
          <div className="p-6 text-center text-sm text-slate-500">Laden…</div>
        ) : (devicesQ.data?.length ?? 0) === 0 ? (
          <div className="p-6 text-center text-sm text-slate-500">Geen devices.</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-[10px] uppercase tracking-wider text-slate-500">
                <th className="text-left px-4 py-2">Device</th>
                <th className="text-left px-4 py-2">Model</th>
                <th className="text-left px-4 py-2">IP</th>
                <th className="text-left px-4 py-2">MAC</th>
                <th className="text-left px-4 py-2">Firmware</th>
                <th className="text-right px-4 py-2">HaloPSA</th>
                <th className="text-right px-4 py-2">Status</th>
              </tr>
            </thead>
            <tbody>
              {(devicesQ.data || []).map((d) => (
                <tr key={d.id} className="border-t border-slate-100 hover:bg-slate-50">
                  <td className="px-4 py-2">
                    <div className="flex items-center gap-2">
                      <span className={`inline-block w-2 h-2 rounded-full ${d.status === "online" ? "bg-emerald-500" : "bg-rose-500"}`} />
                      <span className="truncate">{d.name || <span className="text-slate-400">{d.mac}</span>}</span>
                      {d.is_console && <span className="text-[10px] text-slate-500">[console]</span>}
                    </div>
                  </td>
                  <td className="px-4 py-2"><code className="text-[11px] text-slate-500">{d.model_short || "?"}</code></td>
                  <td className="px-4 py-2"><code className="text-[11px] text-slate-500">{d.ip_address || "—"}</code></td>
                  <td className="px-4 py-2"><code className="text-[11px] text-slate-500">{d.mac || "—"}</code></td>
                  <td className="px-4 py-2 text-[11px]">
                    <div>{d.firmware_version || "—"}</div>
                    {d.firmware_status === "updateAvailable" && (
                      <div className="text-amber-700">update</div>
                    )}
                  </td>
                  <td className="px-4 py-2 text-right text-[11px]">
                    {d.halopsa_asset_id ? (
                      <span className="text-emerald-700">asset #{d.halopsa_asset_id}</span>
                    ) : (
                      <span className="text-slate-400">niet gesynced</span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-right">
                    <span className={`inline-block px-1.5 py-0.5 rounded-full text-[10px] font-medium ${
                      d.status === "online" ? "bg-emerald-50 text-emerald-800" :
                      d.status === "offline" ? "bg-rose-50 text-rose-800" :
                      "bg-slate-100 text-slate-600"
                    }`}>{d.status}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function Field({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">{label}</div>
      <div className={`mt-0.5 ${mono ? "font-mono text-xs" : "text-sm"}`}>{value}</div>
    </div>
  );
}

function CompanyLinkCard({ host, onChanged }: { host: HostRow; onChanged: () => void }) {
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState(false);

  const companiesQ = useQuery<CompanyOpt[]>({
    queryKey: ["companies-for-unifi", search],
    queryFn: async () => {
      const r = await api<{ items: CompanyOpt[] } | CompanyOpt[]>(
        `/companies?limit=25${search ? `&q=${encodeURIComponent(search)}` : ""}`
      );
      return Array.isArray(r) ? r : r.items;
    },
    enabled: open,
  });

  const linkMut = useMutation({
    mutationFn: (companyId: string) =>
      api(`/unifi/hosts/${host.id}/link-company`, {
        method: "POST",
        body: JSON.stringify({ company_id: companyId }),
      }),
    onSuccess: () => {
      onChanged();
      setOpen(false);
      setSearch("");
      qc.invalidateQueries({ queryKey: ["/unifi/hosts"] });
    },
  });

  const unlinkMut = useMutation({
    mutationFn: () =>
      api(`/unifi/hosts/${host.id}/link-company`, { method: "DELETE" }),
    onSuccess: () => {
      onChanged();
      qc.invalidateQueries({ queryKey: ["/unifi/hosts"] });
    },
  });

  const syncAssetsMut = useMutation({
    mutationFn: () =>
      api(`/unifi/sync-halopsa-assets?company_id=${host.company_id}`, { method: "POST" }),
    onSuccess: (data: any) => {
      alert(
        data.ok
          ? `✓ ${data.devices_upserted} devices ge-sync naar HaloPSA (${data.devices_created} nieuw, ${data.devices_updated} update)`
          : `Fout: ${data.detail}`,
      );
      qc.invalidateQueries({ queryKey: ["/unifi/hosts", host.id, "devices"] });
    },
  });

  return (
    <div className="rounded-lg bg-white ring-1 ring-slate-200 p-4">
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <div>
          <div className="text-xs uppercase tracking-wider text-slate-500 font-semibold mb-1">
            Klant-koppeling
          </div>
          {host.company_id ? (
            <div className="text-sm">
              Gekoppeld aan <strong>{host.company_name}</strong>
            </div>
          ) : (
            <div className="text-sm text-slate-500 italic">
              Deze Dream Machine is nog niet aan een SalesPilot-klant gekoppeld.
              Zonder koppeling vallen z'n {host.device_count} devices buiten de
              facturatie + HaloPSA asset-sync.
            </div>
          )}
        </div>
        <div className="flex gap-2">
          {host.company_id ? (
            <>
              <button
                onClick={() => syncAssetsMut.mutate()}
                disabled={syncAssetsMut.isPending}
                className="rounded-md bg-emerald-600 hover:bg-emerald-700 text-white px-3 py-1.5 text-sm font-medium disabled:opacity-50"
              >
                {syncAssetsMut.isPending ? "Bezig…" : "Sync naar HaloPSA"}
              </button>
              <button
                onClick={() => setOpen(true)}
                className="rounded-md bg-slate-100 hover:bg-slate-200 px-3 py-1.5 text-sm font-medium"
              >
                Wijzig
              </button>
              <button
                onClick={() => {
                  if (confirm(`Koppeling met ${host.company_name} verwijderen?`)) {
                    unlinkMut.mutate();
                  }
                }}
                disabled={unlinkMut.isPending}
                className="rounded-md bg-slate-100 hover:bg-rose-100 px-3 py-1.5 text-sm text-slate-700"
              >
                Ontkoppel
              </button>
            </>
          ) : (
            <button
              onClick={() => setOpen(true)}
              className="rounded-md bg-brand-500 hover:bg-brand-600 text-white px-3 py-1.5 text-sm font-medium"
            >
              Koppel aan klant
            </button>
          )}
        </div>
      </div>

      {open && (
        <div className="mt-4 rounded-md border border-slate-200 p-3 space-y-2">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Zoek klant op naam…"
            className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm"
            autoFocus
          />
          <div className="max-h-72 overflow-y-auto space-y-1">
            {companiesQ.isLoading && <div className="text-xs text-slate-500 p-2">Zoeken…</div>}
            {(companiesQ.data || []).map((c) => (
              <button
                key={c.id}
                onClick={() => linkMut.mutate(c.id)}
                disabled={linkMut.isPending}
                className="w-full text-left rounded-md px-3 py-1.5 text-sm hover:bg-slate-100 disabled:opacity-50 flex items-baseline justify-between gap-2"
              >
                <span className="truncate">{c.name}</span>
                <span className="text-xs text-slate-500">
                  {c.halopsa_id ? `Halo #${c.halopsa_id}` : <span className="text-amber-700">geen Halo-link</span>}
                </span>
              </button>
            ))}
            {(companiesQ.data?.length ?? 0) === 0 && !companiesQ.isLoading && (
              <div className="text-xs text-slate-500 p-2">
                Geen klanten gevonden. Tip: voeg de klant eerst toe op /companies.
              </div>
            )}
          </div>
          <button
            onClick={() => { setOpen(false); setSearch(""); }}
            className="text-xs text-slate-500 hover:text-slate-800 mt-1"
          >
            Annuleren
          </button>
        </div>
      )}
    </div>
  );
}

export default UnifiHostDetail;
