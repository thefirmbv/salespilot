import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

type Server = {
  id: string;
  name: string;
  base_url: string;
  verify_tls: boolean;
  is_enabled: boolean;
  has_api_key: boolean;
  last_sync_at: string | null;
  last_sync_status: string | null;
  last_sync_message: string | null;
  notes: string | null;
  subscriptions_count: number;
};

const fmtAgo = (s: string | null) => {
  if (!s) return "nooit";
  const ms = Date.now() - new Date(s).getTime();
  if (ms < 60_000) return `${Math.floor(ms / 1000)}s`;
  if (ms < 3600_000) return `${Math.floor(ms / 60_000)}m`;
  if (ms < 86400_000) return `${Math.floor(ms / 3600_000)}u`;
  return `${Math.floor(ms / 86400_000)}d`;
};

export function PleskServers() {
  const qc = useQueryClient();
  const sq = useQuery<Server[]>({
    queryKey: ["/plesk/servers"],
    queryFn: () => api<Server[]>("/plesk/servers"),
    refetchInterval: 30_000,
  });
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<Server | null>(null);

  return (
    <div className="space-y-4">
      <div className="rounded-lg bg-white ring-1 ring-slate-200 p-4">
        <div className="flex items-baseline justify-between gap-3 flex-wrap">
          <div>
            <h1 className="text-lg font-medium">Plesk servers</h1>
            <p className="mt-1 text-sm text-slate-600">
              Beheer je 4-5 Plesk-servers. Bij elke sync worden alle ingeschakelde
              servers afgelopen. Een subscription wordt automatisch gekoppeld
              aan z'n server.
            </p>
          </div>
          <div className="flex gap-2">
            <Link to="/settings/integrations/plesk" className="rounded-md bg-slate-100 hover:bg-slate-200 px-3 py-1.5 text-sm">
              ← Integratie-defaults
            </Link>
            <button onClick={() => setAdding(true)}
              className="rounded-md bg-brand-500 hover:bg-brand-600 text-white px-3 py-1.5 text-sm">
              + Server toevoegen
            </button>
          </div>
        </div>
      </div>

      {adding && <ServerForm onClose={() => { setAdding(false); qc.invalidateQueries({ queryKey: ["/plesk/servers"] }); }} />}
      {editing && <ServerForm server={editing} onClose={() => { setEditing(null); qc.invalidateQueries({ queryKey: ["/plesk/servers"] }); }} />}

      <div className="rounded-lg bg-white ring-1 ring-slate-200 overflow-hidden">
        <div className="grid grid-cols-[1.2fr_1.8fr_120px_120px_140px_140px] gap-3 border-b border-slate-200 px-4 py-2 text-[10px] uppercase tracking-wider text-slate-500">
          <div>Naam</div>
          <div>URL</div>
          <div>Subscriptions</div>
          <div>Status</div>
          <div>Laatste sync</div>
          <div className="text-right">Acties</div>
        </div>
        {sq.isLoading ? (
          <div className="p-6 text-sm text-slate-500">Laden…</div>
        ) : (sq.data?.length ?? 0) === 0 ? (
          <div className="p-8 text-center text-sm text-slate-500">
            Nog geen servers. Klik <strong>+ Server toevoegen</strong>.
          </div>
        ) : (sq.data || []).map((s) => (
          <ServerRow key={s.id} server={s} onEdit={() => setEditing(s)} />
        ))}
      </div>
    </div>
  );
}

function ServerRow({ server, onEdit }: { server: Server; onEdit: () => void }) {
  const qc = useQueryClient();
  const testMut = useMutation({
    mutationFn: () => api<{ ok: boolean; detail: string }>(`/plesk/servers/${server.id}/test`, { method: "POST" }),
    onSuccess: (r) => alert((r.ok ? "✓ " : "✗ ") + r.detail),
  });
  const delMut = useMutation({
    mutationFn: () => api(`/plesk/servers/${server.id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["/plesk/servers"] }),
    onError: (e: Error) => alert(e.message),
  });

  const statusColor =
    server.last_sync_status === "ok" ? "bg-emerald-500" :
    server.last_sync_status === "error" ? "bg-rose-500" :
    server.last_sync_status === "partial" ? "bg-amber-500" :
    "bg-slate-300";

  return (
    <div className="grid grid-cols-[1.2fr_1.8fr_120px_120px_140px_140px] items-center gap-3 border-b border-slate-100 px-4 py-2 text-sm hover:bg-slate-50">
      <div className="font-medium truncate">{server.name}</div>
      <code className="text-[11px] text-slate-500 truncate">{server.base_url}</code>
      <div className="tabular-nums">{server.subscriptions_count}</div>
      <div className="flex items-center gap-1.5 text-xs">
        <span className={`inline-block w-1.5 h-1.5 rounded-full ${statusColor}`} />
        <span>{server.is_enabled ? (server.last_sync_status || "—") : "uit"}</span>
      </div>
      <div className="text-xs text-slate-500">{fmtAgo(server.last_sync_at)}</div>
      <div className="flex gap-1 justify-end">
        <button onClick={() => testMut.mutate()} disabled={testMut.isPending}
          className="rounded bg-slate-100 hover:bg-slate-200 px-2 py-1 text-xs disabled:opacity-50">
          Test
        </button>
        <button onClick={onEdit}
          className="rounded bg-slate-100 hover:bg-slate-200 px-2 py-1 text-xs">
          Bewerken
        </button>
        <button onClick={() => { if (confirm(`Verwijder ${server.name}?`)) delMut.mutate(); }}
          className="rounded bg-slate-100 hover:bg-rose-100 px-2 py-1 text-xs text-slate-700">
          ✗
        </button>
      </div>
    </div>
  );
}

function ServerForm({ server, onClose }: { server?: Server; onClose: () => void }) {
  const [name, setName] = useState(server?.name || "");
  const [baseUrl, setBaseUrl] = useState(server?.base_url || "https://plesk.it-gemak.nl:8443");
  const [apiKey, setApiKey] = useState("");
  const [verifyTls, setVerifyTls] = useState(server?.verify_tls ?? true);
  const [isEnabled, setIsEnabled] = useState(server?.is_enabled ?? true);
  const [notes, setNotes] = useState(server?.notes || "");

  const saveMut = useMutation({
    mutationFn: () => {
      const body: any = { name, base_url: baseUrl, verify_tls: verifyTls, is_enabled: isEnabled, notes: notes || null };
      if (apiKey) body.api_key = apiKey;
      else if (!server) body.api_key = "";
      if (server) {
        return api(`/plesk/servers/${server.id}`, { method: "PUT", body: JSON.stringify(body) });
      }
      return api("/plesk/servers", { method: "POST", body: JSON.stringify(body) });
    },
    onSuccess: onClose,
    onError: (e: Error) => alert(e.message),
  });

  return (
    <div className="rounded-lg bg-blue-50 border border-blue-200 p-4 space-y-3">
      <div className="text-sm font-medium">{server ? "Server bewerken" : "Nieuwe server"}</div>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Naam *" value={name} onChange={setName} placeholder="Plesk-server-1" />
        <Field label="Base URL *" value={baseUrl} onChange={setBaseUrl} placeholder="https://plesk.host:8443" />
        <div className="col-span-2">
          <label className="block text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-1">
            API key {server && <span className="text-slate-400">(leeg laten om huidige te behouden)</span>}{!server && " *"}
          </label>
          <input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)}
            placeholder={server ? "•••••" : "X-API-Key uit Plesk admin"}
            className="w-full rounded border border-slate-300 px-2 py-1.5 text-sm font-mono" />
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={verifyTls} onChange={(e) => setVerifyTls(e.target.checked)} />
          TLS verificeren
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={isEnabled} onChange={(e) => setIsEnabled(e.target.checked)} />
          Ingeschakeld (meedoen aan sync)
        </label>
        <div className="col-span-2">
          <label className="block text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-1">Notities</label>
          <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2}
            className="w-full rounded border border-slate-300 px-2 py-1.5 text-sm" />
        </div>
      </div>
      <div className="flex gap-2 justify-end">
        <button onClick={onClose} className="rounded-md bg-white border border-slate-300 px-3 py-1.5 text-sm">Annuleren</button>
        <button onClick={() => saveMut.mutate()} disabled={!name || !baseUrl || (!server && !apiKey) || saveMut.isPending}
          className="rounded-md bg-brand-500 hover:bg-brand-600 text-white px-3 py-1.5 text-sm disabled:opacity-50">
          {saveMut.isPending ? "Bezig…" : "Opslaan"}
        </button>
      </div>
    </div>
  );
}

function Field({ label, value, onChange, placeholder }: any) {
  return (
    <div>
      <label className="block text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-1">{label}</label>
      <input value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder}
        className="w-full rounded border border-slate-300 px-2 py-1.5 text-sm" />
    </div>
  );
}

export default PleskServers;
