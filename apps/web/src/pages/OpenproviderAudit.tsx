import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

type AuditRow = {
  id: string;
  user_email: string | null;
  action: string;
  domain_name: string | null;
  status: string;
  error_message: string | null;
  occurred_at: string;
};

const ACTION_LABEL: Record<string, { label: string; tone: string }> = {
  register: { label: "Geregistreerd", tone: "emerald" },
  cancel: { label: "Geannuleerd", tone: "rose" },
  auto_renew_on: { label: "Auto-renew aan", tone: "blue" },
  auto_renew_off: { label: "Auto-renew uit", tone: "amber" },
  nameserver_change: { label: "DNS gewijzigd", tone: "blue" },
};

export function OpenproviderAudit() {
  const lq = useQuery<AuditRow[]>({
    queryKey: ["/openprovider/audit-log"],
    queryFn: () => api<AuditRow[]>("/openprovider/audit-log"),
  });
  return (
    <div className="space-y-4">
      <div className="rounded-lg bg-white ring-1 ring-slate-200 p-4">
        <div className="flex items-baseline justify-between">
          <h1 className="text-lg font-medium">Openprovider audit log</h1>
          <Link to="/openprovider" className="text-sm text-slate-500 hover:underline">← terug</Link>
        </div>
        <p className="mt-1 text-sm text-slate-600">
          Alle write-acties op Openprovider (registraties, cancellaties, auto-renew toggles).
          Read-only voor het paper-trail.
        </p>
      </div>

      <div className="rounded-lg bg-white ring-1 ring-slate-200 overflow-hidden">
        <div className="grid grid-cols-[140px_140px_1fr_160px_80px] gap-3 border-b border-slate-200 px-4 py-2 text-[10px] uppercase tracking-wider text-slate-500">
          <div>Wanneer</div>
          <div>Actie</div>
          <div>Domein</div>
          <div>Gebruiker</div>
          <div className="text-right">Status</div>
        </div>
        {lq.isLoading ? <div className="p-6 text-sm text-slate-500">Laden…</div>
        : (lq.data?.length ?? 0) === 0 ? <div className="p-8 text-center text-sm text-slate-500">Nog geen audit-entries.</div>
        : (lq.data || []).map(a => {
          const act = ACTION_LABEL[a.action] || { label: a.action, tone: "slate" };
          return (
            <div key={a.id} className="grid grid-cols-[140px_140px_1fr_160px_80px] items-center gap-3 border-b border-slate-100 px-4 py-2 text-sm hover:bg-slate-50">
              <div className="text-xs text-slate-500">{new Date(a.occurred_at).toLocaleString("nl-NL")}</div>
              <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium bg-${act.tone}-50 text-${act.tone}-800`}>{act.label}</span>
              <div>
                <div className="font-mono text-xs">{a.domain_name || "—"}</div>
                {a.error_message && <div className="text-[11px] text-rose-700 mt-0.5">{a.error_message}</div>}
              </div>
              <div className="text-xs text-slate-600">{a.user_email || "—"}</div>
              <div className="text-right">
                <span className={`text-[10px] ${a.status === "ok" ? "text-emerald-700" : "text-rose-700"}`}>{a.status}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default OpenproviderAudit;
