import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { api } from "@/lib/api";

type DebtorStatus = {
  debtor_id: string;
  name: string;
  granted_scopes: string[];
  access_token_expires_at: string | null;
  last_token_refresh_at: string | null;
};

type SoapCredsStatus = {
  configured: boolean;
  username: string | null;
};

type AbsenceSyncResult = {
  ok: boolean;
  employees_with_absences: number;
  absences_total: number;
  appointments_created: number;
  appointments_skipped_duplicate: number;
  skipped_no_match: string[];
  error: string | null;
};

type NmbrsStatus = {
  configured: boolean;
  connected: boolean;
  debtors: DebtorStatus[];
  last_sync_at: string | null;
};

type DebtorSyncResult = {
  debtor_id: string;
  debtor_name: string;
  ok: boolean;
  employees_created: number;
  employees_updated: number;
  employees_unchanged: number;
  companies_seen: number;
  skipped_no_name: number;
  error: string | null;
};

type SyncResult = {
  ok: boolean;
  debtors_synced: number;
  total_created: number;
  total_updated: number;
  total_unchanged: number;
  per_debtor: DebtorSyncResult[];
  error: string | null;
};

export function NmbrsSettings() {
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const callbackResult = params.get("nmbrs");
  const callbackMsg = params.get("msg");

  useEffect(() => {
    if (callbackResult) {
      const t = setTimeout(() => {
        const p = new URLSearchParams(params);
        p.delete("nmbrs"); p.delete("msg");
        setParams(p, { replace: true });
      }, 12000);
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
    onError: (e: any) => setSyncResult({
      ok: false, debtors_synced: 0, total_created: 0, total_updated: 0,
      total_unchanged: 0, per_debtor: [],
      error: e?.message || "Onbekende fout",
    }),
  });

  const startConnect = async () => {
    try {
      const r = await api<{ authorize_url: string }>("/integrations/nmbrs/oauth/start");
      window.location.href = r.authorize_url;
    } catch (e: any) {
      alert("Fout bij starten OAuth: " + (e?.message || "onbekend"));
    }
  };

  const disconnectMut = useMutation({
    mutationFn: (debtorId: string) =>
      api(`/integrations/nmbrs/debtors/${debtorId}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["/integrations/nmbrs/status"] }),
  });

  // SOAP creds (voor verlof-sync via legacy SOAP API)
  const soapQ = useQuery<SoapCredsStatus>({
    queryKey: ["/integrations/nmbrs/soap-creds"],
    queryFn: () => api<SoapCredsStatus>("/integrations/nmbrs/soap-creds"),
  });
  const [soapUsername, setSoapUsername] = useState("");
  const [soapToken, setSoapToken] = useState("");
  const [soapEdit, setSoapEdit] = useState(false);
  const soapSaveMut = useMutation({
    mutationFn: () =>
      api("/integrations/nmbrs/soap-creds", {
        method: "PUT",
        body: JSON.stringify({ username: soapUsername, token: soapToken }),
      }),
    onSuccess: () => {
      setSoapEdit(false);
      setSoapUsername(""); setSoapToken("");
      qc.invalidateQueries({ queryKey: ["/integrations/nmbrs/soap-creds"] });
    },
  });
  const soapDeleteMut = useMutation({
    mutationFn: () => api("/integrations/nmbrs/soap-creds", { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["/integrations/nmbrs/soap-creds"] }),
  });

  // Verlof-sync
  const [absenceResult, setAbsenceResult] = useState<AbsenceSyncResult | null>(null);
  const absenceMut = useMutation({
    mutationFn: () => api<AbsenceSyncResult>("/integrations/nmbrs/sync-absences", { method: "POST" }),
    onSuccess: (r) => setAbsenceResult(r),
    onError: (e: any) => setAbsenceResult({
      ok: false, employees_with_absences: 0, absences_total: 0,
      appointments_created: 0, appointments_skipped_duplicate: 0,
      skipped_no_match: [], error: e?.message || "onbekend",
    }),
  });

  const s = statusQ.data;

  return (
    <div className="max-w-3xl mx-auto p-6 space-y-6">
      <header>
        <h1 className="text-2xl font-medium">NMBRS koppeling</h1>
        <p className="text-sm text-slate-500 mt-1">
          Medewerkers + verlof per debtor synchroniseren. Heb je meerdere
          NMBRS-debtors (bv. IT-gemak B.V. én The Firm ISP B.V.)? Verbind
          ze allemaal apart — elke "Verbinden"-actie voegt een debtor toe.
        </p>
      </header>

      {callbackResult && (
        <div className={`rounded-lg p-4 border ${
          callbackResult === "ok"
            ? "bg-emerald-50 border-emerald-200 text-emerald-900"
            : "bg-rose-50 border-rose-200 text-rose-900"
        }`}>
          <div className="font-medium">
            {callbackResult === "ok" ? "✓ Debtor gekoppeld" : "✗ Koppeling mislukt"}
          </div>
          {callbackMsg && <div className="text-xs mt-1">{callbackMsg}</div>}
        </div>
      )}

      {/* Status van credentials */}
      <section className="rounded-lg bg-white ring-1 ring-slate-200 p-5 space-y-3">
        <h2 className="text-base font-medium">Status</h2>
        {statusQ.isLoading && <div className="text-sm text-slate-500">Laden…</div>}
        {s && (
          <div className="grid grid-cols-2 gap-y-2 text-sm">
            <Cell label="Credentials" ok={s.configured}>{s.configured ? "Compleet" : "Ontbreken"}</Cell>
            <Cell label="Verbonden debtors">{s.debtors.length}</Cell>
            <Cell label="Laatste sync">{fmtIso(s.last_sync_at)}</Cell>
          </div>
        )}
      </section>

      {/* Lijst van gekoppelde debtors */}
      {s && (
        <section className="rounded-lg bg-white ring-1 ring-slate-200 p-5 space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-medium">Gekoppelde debtors</h2>
            <button
              onClick={startConnect}
              className="text-sm px-3 py-1.5 rounded bg-blue-600 text-white hover:bg-blue-700"
            >
              {s.debtors.length === 0 ? "Verbinden met NMBRS →" : "+ Debtor toevoegen"}
            </button>
          </div>

          {s.debtors.length === 0 && (
            <p className="text-sm text-slate-500">
              Nog geen debtor gekoppeld. Klik op "Verbinden" en kies in
              het NMBRS consent-scherm welke debtor je wil koppelen. Heb
              je meerdere, herhaal voor elke debtor.
            </p>
          )}

          <ul className="space-y-2">
            {s.debtors.map((d) => (
              <li key={d.debtor_id} className="rounded-md ring-1 ring-slate-200 p-3 flex items-baseline justify-between gap-3">
                <div className="min-w-0">
                  <div className="font-medium">{d.name}</div>
                  <div className="text-xs text-slate-500 font-mono truncate">{d.debtor_id}</div>
                  <div className="text-xs text-slate-500 mt-1">
                    Token vernieuwt: {fmtIso(d.access_token_expires_at)}
                  </div>
                </div>
                <button
                  onClick={() => {
                    if (confirm(`Debtor ${d.name} ontkoppelen?`)) {
                      disconnectMut.mutate(d.debtor_id);
                    }
                  }}
                  className="text-xs px-2 py-1 rounded ring-1 ring-rose-300 text-rose-700 hover:bg-rose-50"
                >
                  Ontkoppelen
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Sync */}
      {s && s.debtors.length > 0 && (
        <section className="rounded-lg bg-white ring-1 ring-slate-200 p-5 space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-medium">Synchronisatie</h2>
            <button
              onClick={() => syncMut.mutate()}
              disabled={syncMut.isPending}
              className="text-sm px-3 py-1.5 rounded bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {syncMut.isPending ? "Synchroniseren…" : "Sync nu (alle debtors)"}
            </button>
          </div>
          <p className="text-xs text-slate-500">
            Cron draait elk uur op :07 en pikt automatisch nieuwe medewerkers op uit elke gekoppelde debtor.
          </p>

          {syncResult && (
            <div className={`text-sm rounded-md p-3 ${
              syncResult.ok
                ? "bg-emerald-50 border border-emerald-200"
                : "bg-rose-50 border border-rose-200"
            }`}>
              {syncResult.ok ? (
                <div>
                  <div className="font-medium text-emerald-900">
                    ✓ Sync over {syncResult.debtors_synced} debtor(s) klaar
                  </div>
                  <div className="text-xs mt-1 text-emerald-900">
                    Totaal: <strong>{syncResult.total_created}</strong> nieuw,
                    {" "}<strong>{syncResult.total_updated}</strong> bijgewerkt,
                    {" "}{syncResult.total_unchanged} ongewijzigd
                  </div>
                </div>
              ) : (
                <div className="text-rose-900">
                  <div className="font-medium">
                    {syncResult.error
                      ? "✗ Sync mislukt"
                      : "⚠ Gedeeltelijke sync — sommige debtors gefaald"}
                  </div>
                  {syncResult.error && <div className="text-xs mt-1">{syncResult.error}</div>}
                </div>
              )}

              {syncResult.per_debtor.length > 0 && (
                <ul className="mt-3 space-y-1 text-xs">
                  {syncResult.per_debtor.map((d) => (
                    <li key={d.debtor_id} className={d.ok ? "text-emerald-900" : "text-rose-900"}>
                      {d.ok ? "✓" : "✗"} <strong>{d.debtor_name}</strong>:
                      {d.ok ? (
                        <> {d.employees_created} nieuw, {d.employees_updated} bijgewerkt,
                        {" "}{d.companies_seen} bedrijven</>
                      ) : (
                        <> {d.error}</>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          <div className="text-xs text-slate-500 pt-2 border-t border-slate-100">
            Verifieer op <a href="/financieel/inventaris" className="underline">/financieel/inventaris</a> dat de medewerkers van álle debtors zijn ingeladen.
          </div>
        </section>
      )}

      {/* SOAP credentials voor verlof-sync */}
      <section className="rounded-lg bg-white ring-1 ring-slate-200 p-5 space-y-3">
        <div className="flex items-baseline justify-between">
          <h2 className="text-base font-medium">Verlof-sync (SOAP API)</h2>
          <span className="text-[10px] text-amber-700 bg-amber-100 px-2 py-0.5 rounded font-mono">
            Legacy SOAP — wordt 2027 vervangen
          </span>
        </div>
        <p className="text-xs text-slate-500">
          NMBRS' moderne REST API heeft (nog) geen verlof-endpoint. Voor verlof gebruiken
          we hun SOAP-API met je NMBRS-login + API-token.
        </p>

        {soapQ.isLoading && <div className="text-sm text-slate-500">Laden…</div>}

        {soapQ.data && !soapEdit && (
          <div className="space-y-2">
            {soapQ.data.configured ? (
              <div className="flex items-baseline justify-between gap-2 text-sm">
                <div>
                  <span className="text-emerald-700">✓ Ingesteld</span>
                  {" — "}
                  <span className="font-mono text-xs">{soapQ.data.username}</span>
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => setSoapEdit(true)}
                    className="text-xs px-2 py-1 rounded ring-1 ring-slate-300 hover:bg-slate-50"
                  >
                    Wijzigen
                  </button>
                  <button
                    onClick={() => { if (confirm("SOAP-credentials verwijderen?")) soapDeleteMut.mutate(); }}
                    className="text-xs px-2 py-1 rounded ring-1 ring-rose-300 text-rose-700 hover:bg-rose-50"
                  >
                    Verwijderen
                  </button>
                </div>
              </div>
            ) : (
              <div className="space-y-2">
                <p className="text-sm text-slate-600">
                  Nog niet ingesteld. Vul je NMBRS-login + API-token in.
                </p>
                <button
                  onClick={() => setSoapEdit(true)}
                  className="text-sm px-3 py-1.5 rounded bg-blue-600 text-white hover:bg-blue-700"
                >
                  Credentials invoeren
                </button>
              </div>
            )}
          </div>
        )}

        {soapEdit && (
          <div className="space-y-3 bg-slate-50 rounded p-3">
            <div>
              <label className="block text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-1">
                NMBRS Username (login email)
              </label>
              <input
                type="email"
                value={soapUsername}
                onChange={(e) => setSoapUsername(e.target.value)}
                placeholder="jouw.nmbrs-login@bedrijf.nl"
                className="w-full text-sm rounded border border-slate-300 px-2 py-1"
              />
            </div>
            <div>
              <label className="block text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-1">
                NMBRS API Token
              </label>
              <input
                type="password"
                value={soapToken}
                onChange={(e) => setSoapToken(e.target.value)}
                placeholder="32-char token uit Mijn Profiel > API Tokens"
                className="w-full text-sm rounded border border-slate-300 px-2 py-1 font-mono"
              />
              <div className="text-xs text-slate-500 mt-1">
                Token vind je in app.nmbrs.nl → Mijn Profiel → API Tokens.
              </div>
            </div>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => { setSoapEdit(false); setSoapUsername(""); setSoapToken(""); }}
                className="text-sm px-3 py-1 rounded ring-1 ring-slate-300 hover:bg-slate-100"
              >
                Annuleren
              </button>
              <button
                onClick={() => soapSaveMut.mutate()}
                disabled={!soapUsername || !soapToken || soapSaveMut.isPending}
                className="text-sm px-3 py-1 rounded bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {soapSaveMut.isPending ? "Opslaan…" : "Opslaan"}
              </button>
            </div>
            {soapSaveMut.isError && (
              <div className="text-xs text-rose-700">
                Fout: {(soapSaveMut.error as any)?.message}
              </div>
            )}
          </div>
        )}

        {/* Verlof-sync button (alleen als SOAP geconfigd) */}
        {soapQ.data?.configured && !soapEdit && (
          <div className="space-y-2 pt-3 border-t border-slate-100">
            <button
              onClick={() => absenceMut.mutate()}
              disabled={absenceMut.isPending}
              className="text-sm px-3 py-1.5 rounded bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {absenceMut.isPending ? "Verlof synchroniseren…" : "Sync verlof nu"}
            </button>
            <div className="text-xs text-slate-500">
              Haalt verlof-records uit NMBRS (huidig + vorig jaar) en plaatst ze als
              all-day Appointments in HaloPSA. De HaloPSA → MS365 sync zorgt voor doorpush
              naar persoonlijke Outlook-agenda's. Werkt alleen voor medewerkers met
              gekoppelde HaloPSA-agent.
            </div>

            {absenceResult && (
              <div className={`text-sm rounded-md p-3 ${
                absenceResult.ok && !absenceResult.error
                  ? "bg-emerald-50 border border-emerald-200 text-emerald-900"
                  : "bg-rose-50 border border-rose-200 text-rose-900"
              }`}>
                {absenceResult.ok && !absenceResult.error ? (
                  <div>
                    <div className="font-medium">✓ Sync klaar</div>
                    <div className="text-xs mt-1">
                      {absenceResult.employees_with_absences} medewerkers met verlof,
                      {" "}{absenceResult.absences_total} records totaal —
                      {" "}<strong>{absenceResult.appointments_created}</strong> aangemaakt in HaloPSA,
                      {" "}{absenceResult.appointments_skipped_duplicate} duplicaat
                    </div>
                  </div>
                ) : (
                  <div>
                    <div className="font-medium">✗ Sync mislukt</div>
                    {absenceResult.error && (
                      <div className="text-xs mt-1">{absenceResult.error}</div>
                    )}
                  </div>
                )}
                {absenceResult.skipped_no_match.length > 0 && (
                  <details className="mt-2 text-xs">
                    <summary className="cursor-pointer">
                      {absenceResult.skipped_no_match.length} overgeslagen records — toon details
                    </summary>
                    <ul className="mt-1 space-y-0.5 list-disc list-inside">
                      {absenceResult.skipped_no_match.map((m, i) => (
                        <li key={i}>{m}</li>
                      ))}
                    </ul>
                  </details>
                )}
              </div>
            )}
          </div>
        )}
      </section>
    </div>
  );
}

function Cell({ label, ok, children }: {
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
