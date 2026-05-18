import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { api } from "@/lib/api";

type NmbrsStatus = {
  configured: boolean;
  connected: boolean;
  status: string;
  granted_scopes: string[];
  access_token_expires_at: string | null;
  last_token_refresh_at: string | null;
  last_sync_at: string | null;
};

type SyncResult = {
  ok: boolean;
  employees_created?: number;
  employees_updated?: number;
  employees_unchanged?: number;
  companies_seen?: number;
  skipped_no_email?: number;
  error?: string;
};

export function NmbrsSettings() {
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const callbackResult = params.get("nmbrs");
  const callbackMsg = params.get("msg");

  // Verwijder query-params na lezen
  useEffect(() => {
    if (callbackResult) {
      const t = setTimeout(() => {
        const p = new URLSearchParams(params);
        p.delete("nmbrs");
        p.delete("msg");
        setParams(p, { replace: true });
      }, 8000);
      return () => clearTimeout(t);
    }
  }, [callbackResult, params, setParams]);

  const statusQ = useQuery<NmbrsStatus>({
    queryKey: ["/integrations/nmbrs/status"],
    queryFn: () => api<NmbrsStatus>("/integrations/nmbrs/status"),
    refetchInterval: callbackResult === "ok" ? 2000 : false,
  });

  const [syncResult, setSyncResult] = useState<SyncResult | null>(null);
  const syncMut = useMutation({
    mutationFn: () => api<SyncResult>("/integrations/nmbrs/sync-employees", { method: "POST" }),
    onSuccess: (r) => {
      setSyncResult(r);
      qc.invalidateQueries({ queryKey: ["/integrations/nmbrs/status"] });
      qc.invalidateQueries({ queryKey: ["/inventory/employees"] });
    },
    onError: (e: any) => setSyncResult({ ok: false, error: e?.message || "Onbekende fout" }),
  });

  const s = statusQ.data;

  return (
    <div className="max-w-3xl mx-auto p-6 space-y-6">
      <header>
        <h1 className="text-2xl font-medium">NMBRS koppeling</h1>
        <p className="text-sm text-slate-500 mt-1">
          Medewerkers en verlof synchroniseren vanuit NMBRS. Verlof komt via
          HaloPSA Appointment in iedereen z'n persoonlijke Outlook-agenda.
        </p>
      </header>

      {callbackResult && (
        <div className={`rounded-lg p-4 border ${
          callbackResult === "ok"
            ? "bg-emerald-50 border-emerald-200 text-emerald-900"
            : "bg-rose-50 border-rose-200 text-rose-900"
        }`}>
          <div className="font-medium">
            {callbackResult === "ok"
              ? "✓ Gekoppeld aan NMBRS"
              : "✗ Koppeling mislukt"}
          </div>
          {callbackMsg && <div className="text-xs mt-1">{callbackMsg}</div>}
        </div>
      )}

      {/* Status */}
      <section className="rounded-lg bg-white ring-1 ring-slate-200 p-5 space-y-3">
        <h2 className="text-base font-medium">Status</h2>
        {statusQ.isLoading && <div className="text-sm text-slate-500">Laden…</div>}
        {s && (
          <div className="grid grid-cols-2 gap-y-2 text-sm">
            <StatusRow label="Credentials" ok={s.configured}>
              {s.configured ? "Compleet" : "Ontbreken"}
            </StatusRow>
            <StatusRow label="OAuth verbinding" ok={s.connected}>
              {s.connected ? "Actief" : "Niet verbonden"}
            </StatusRow>
            <StatusRow label="Token verloopt">
              {fmtIso(s.access_token_expires_at)}
            </StatusRow>
            <StatusRow label="Laatste sync">
              {fmtIso(s.last_sync_at)}
            </StatusRow>
            {s.granted_scopes.length > 0 && (
              <div className="col-span-2">
                <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-1">
                  Goedgekeurde scopes
                </div>
                <div className="flex flex-wrap gap-1">
                  {s.granted_scopes.map((sc) => (
                    <span key={sc} className="text-[11px] px-1.5 py-0.5 rounded bg-blue-50 text-blue-800 font-mono">
                      {sc}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </section>

      {/* Actions */}
      {s && (
        <section className="rounded-lg bg-white ring-1 ring-slate-200 p-5 space-y-3">
          <h2 className="text-base font-medium">Acties</h2>

          {!s.connected && (
            <div className="space-y-2">
              <p className="text-sm text-slate-600">
                Klik op de knop om je NMBRS-account te koppelen. Je wordt
                doorgestuurd naar NMBRS om consent te geven voor de scopes:
                <code className="text-xs bg-slate-100 px-1 mx-1 rounded">employee.info.read</code>,
                <code className="text-xs bg-slate-100 px-1 mx-1 rounded">employee.absence.read</code>,
                <code className="text-xs bg-slate-100 px-1 mx-1 rounded">company.info.read</code>.
              </p>
              <a
                href="/api/v1/integrations/nmbrs/oauth/start"
                className="inline-block text-sm px-3 py-1.5 rounded bg-blue-600 text-white hover:bg-blue-700"
              >
                Verbinden met NMBRS →
              </a>
            </div>
          )}

          {s.connected && (
            <div className="space-y-3">
              <div className="flex items-baseline gap-3 flex-wrap">
                <button
                  onClick={() => syncMut.mutate()}
                  disabled={syncMut.isPending}
                  className="text-sm px-3 py-1.5 rounded bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
                >
                  {syncMut.isPending ? "Synchroniseren…" : "Sync medewerkers nu"}
                </button>
                <a
                  href="/api/v1/integrations/nmbrs/oauth/start"
                  className="text-xs text-slate-500 hover:text-blue-700"
                >
                  Opnieuw autoriseren
                </a>
              </div>

              {syncResult && (
                <div className={`text-sm rounded-md p-3 ${
                  syncResult.ok
                    ? "bg-emerald-50 border border-emerald-200 text-emerald-900"
                    : "bg-rose-50 border border-rose-200 text-rose-900"
                }`}>
                  {syncResult.ok ? (
                    <div className="space-y-0.5">
                      <div className="font-medium">✓ Sync klaar</div>
                      <div className="text-xs">
                        {syncResult.companies_seen} bedrijven bekeken;
                        {" "}<strong>{syncResult.employees_created}</strong> nieuw,
                        {" "}<strong>{syncResult.employees_updated}</strong> bijgewerkt,
                        {" "}{syncResult.employees_unchanged} ongewijzigd
                        {(syncResult.skipped_no_email ?? 0) > 0 &&
                          <>, {syncResult.skipped_no_email} overgeslagen (geen naam)</>}
                      </div>
                    </div>
                  ) : (
                    <div>
                      <div className="font-medium">✗ Sync mislukt</div>
                      <div className="text-xs mt-1">{syncResult.error}</div>
                    </div>
                  )}
                </div>
              )}

              <div className="text-xs text-slate-500 pt-2 border-t border-slate-100">
                Verlof-sync naar HaloPSA-agenda's volgt zodra deze eerste
                synchronisatie werkt. Tussenstop: even verifiëren of de
                medewerkers-lijst klopt op <a href="/financieel/inventaris" className="underline">/financieel/inventaris</a>.
              </div>
            </div>
          )}
        </section>
      )}
    </div>
  );
}

function StatusRow({ label, ok, children }: {
  label: string; ok?: boolean; children: React.ReactNode;
}) {
  return (
    <>
      <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">{label}</div>
      <div className="flex items-baseline gap-2">
        {ok !== undefined && (
          <span className={ok ? "text-emerald-600" : "text-rose-600"}>
            {ok ? "●" : "○"}
          </span>
        )}
        <span>{children}</span>
      </div>
    </>
  );
}

function fmtIso(s: string | null | undefined): string {
  if (!s) return "—";
  try {
    return new Date(s).toLocaleString("nl-NL", {
      day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
    });
  } catch {
    return s;
  }
}
