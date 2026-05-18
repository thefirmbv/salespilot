import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import { fmtDateTime } from "@/lib/format";
import { PhoneLink } from "@/components/PhoneLink";

type SnelstartConnTest = {
  configured: boolean;
  ok: boolean;
  administraties_count: number;
  administraties: { id: string; naam: string }[];
  error: string | null;
};

type SepaMachtigingDetail = {
  umr?: string;
  debtor_name?: string;
  snelstart_factuur_id?: string;
  snelstart_factuurnummer?: string | null;
  outcome: string;
};

type SepaMachtigingError = {
  umr?: string;
  phase?: string;
  snelstart_factuur_id?: string;
  error: string;
};

type SepaMachtigingResult = {
  ok: boolean;
  dry_run: boolean;
  error: string | null;
  mandates_total: number;
  matched_in_snelstart: number;
  mandates_no_match: number;
  machtigingen_existing: number;
  machtigingen_created: number;
  boekingen_scanned: number;
  boekingen_patched: number;
  boekingen_already_set: number;
  errors: SepaMachtigingError[];
  details: SepaMachtigingDetail[];
};

type Mandate = {
  id: string;
  umr: string;
  debtor_name: string;
  debtor_email: string;
  debtor_iban: string;
  debtor_city: string;
  debtor_kvk: string | null;
  sign_place: string;
  kvk_verified: boolean;
  status: string;
  ip_address: string | null;
  geo_country: string | null;
  geo_city: string | null;
  pdf_sha256: string | null;
  has_pdf: boolean;
  emailed_at: string | null;
  email_error: string | null;
  created_at: string;
};

type MandateDetail = Mandate & {
  debtor_address: string;
  debtor_postcode: string;
  debtor_country: string;
  debtor_bic: string | null;
  debtor_phone: string | null;
  signature_png_base64: string;
  user_agent: string | null;
  geo_region: string | null;
  geo_lat: number | null;
  geo_lon: number | null;
  kvk_verified_at: string | null;
  kvk_raw: unknown;
};

function StatusBadge({ status, hasError }: { status: string; hasError: boolean }) {
  let cls = "bg-slate-100 text-slate-700";
  let label: string = status;
  if (hasError) { cls = "bg-red-50 text-red-800"; label = "email mislukt"; }
  else if (status === "emailed") { cls = "bg-emerald-50 text-emerald-800"; label = "verzonden"; }
  else if (status === "submitted") { cls = "bg-amber-50 text-amber-800"; label = "ontvangen"; }
  else if (status === "revoked") { cls = "bg-slate-200 text-slate-600"; label = "herroepen"; }
  return <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ${cls}`}>{label}</span>;
}

function fmtIban(iban: string): string {
  return iban.replace(/(.{4})/g, "$1 ").trim();
}

export function Mandates() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const listQ = useQuery<Mandate[]>({
    queryKey: ["/admin/mandates"],
    queryFn: () => api<Mandate[]>("/admin/mandates"),
  });

  // Snelstart connection-status (skeleton -- werkt zodra credentials gevuld)
  const connQ = useQuery<SnelstartConnTest>({
    queryKey: ["/snelstart/connection-test"],
    queryFn: () => api<SnelstartConnTest>("/snelstart/connection-test"),
    retry: false,
  });

  const [syncResult, setSyncResult] = useState<SepaMachtigingResult | null>(null);
  const previewMut = useMutation({
    mutationFn: () => api<SepaMachtigingResult>(
      "/snelstart/sepa-machtiging-sync/preview?days_back=90",
      { method: "POST" },
    ),
    onSuccess: (r) => setSyncResult(r),
  });
  const applyMut = useMutation({
    mutationFn: () => api<SepaMachtigingResult>(
      "/snelstart/sepa-machtiging-sync/apply?days_back=90",
      { method: "POST" },
    ),
    onSuccess: (r) => setSyncResult(r),
  });

  return (
    <div>
      <div className="mb-4 flex items-baseline justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">SEPA-mandaten</h1>
          <p className="mt-1 text-sm text-slate-500">
            Digitaal ondertekende mandaten via <a href="https://sign.it-gemak.nl/" target="_blank" rel="noreferrer" className="text-brand-600 hover:underline">sign.it-gemak.nl</a> — incl. audit trail.
          </p>
        </div>
        <a
          href="https://sign.it-gemak.nl/"
          target="_blank"
          rel="noreferrer"
          className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50"
        >
          ↗ Open ondertekenportaal
        </a>
      </div>

      {/* Snelstart -> doorlopende incassomachtiging sync */}
      <div className="mb-6 rounded-lg bg-white ring-1 ring-slate-200 p-5 space-y-3">
        <div className="flex items-baseline justify-between gap-3">
          <h2 className="text-base font-medium">Snelstart → doorlopende incassomachtiging</h2>
          {connQ.data?.configured ? (
            connQ.data.ok ? (
              <span className="text-[10px] text-emerald-700 bg-emerald-100 px-2 py-0.5 rounded font-mono">
                ✓ Verbonden ({connQ.data.administraties_count} adm)
              </span>
            ) : (
              <span className="text-[10px] text-rose-700 bg-rose-100 px-2 py-0.5 rounded font-mono">
                Fout
              </span>
            )
          ) : (
            <span className="text-[10px] text-amber-700 bg-amber-100 px-2 py-0.5 rounded font-mono">
              Credentials ontbreken
            </span>
          )}
        </div>

        {connQ.data && !connQ.data.configured && (
          <div className="text-xs bg-amber-50 border border-amber-200 rounded p-2 text-amber-900">
            Snelstart B2B API credentials zijn nog niet ingesteld. Vul ze in via{" "}
            <a href="/settings/integrations" className="underline font-medium">
              Settings → Integraties → Snelstart
            </a>{" "}— daarna werkt de sync.
          </div>
        )}

        {connQ.data?.configured && !connQ.data.ok && (
          <div className="text-xs bg-rose-50 border border-rose-200 rounded p-2 text-rose-900">
            Snelstart connection-test faalt: <span className="font-mono">{connQ.data.error}</span>
          </div>
        )}

        <p className="text-xs text-slate-500">
          HaloPSA pusht verkoopboekingen naar Snelstart zonder de{" "}
          <span className="font-mono">doorlopendeIncassoMachtiging</span>-referentie.
          Deze sync vult die referentie achteraf in zodat de boekingen in het
          incassobestand komen. Bron-of-waarheid: SalesPilot{" "}
          <span className="font-mono">signed_mandates</span>.
        </p>

        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => previewMut.mutate()}
            disabled={previewMut.isPending || applyMut.isPending}
            className="text-sm px-3 py-1.5 rounded ring-1 ring-slate-300 hover:bg-slate-50 disabled:opacity-50"
          >
            {previewMut.isPending ? "Bezig..." : "Test (dry-run)"}
          </button>
          <button
            onClick={() => {
              if (!confirm("Echt pushen naar Snelstart? Dit maakt aan/koppelt machtigingen en patcht verkoopboekingen.")) return;
              applyMut.mutate();
            }}
            disabled={applyMut.isPending || previewMut.isPending || !connQ.data?.ok}
            className="text-sm px-3 py-1.5 rounded bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {applyMut.isPending ? "Pushen..." : "Echt pushen naar Snelstart"}
          </button>
        </div>

        {syncResult && (
          <div className={`text-sm rounded-md p-3 ${
            syncResult.ok && !syncResult.error
              ? syncResult.dry_run
                ? "bg-amber-50 border border-amber-200 text-amber-900"
                : "bg-emerald-50 border border-emerald-200 text-emerald-900"
              : "bg-rose-50 border border-rose-200 text-rose-900"
          }`}>
            <div className="font-medium">
              {syncResult.error ? "Sync mislukt" : syncResult.dry_run ? "Dry-run resultaat" : "Sync klaar"}
            </div>
            {syncResult.error ? (
              <div className="text-xs mt-1">{syncResult.error}</div>
            ) : (
              <div className="text-xs mt-1 space-y-0.5">
                <div>
                  <strong>{syncResult.mandates_total}</strong> mandaten
                  • {syncResult.matched_in_snelstart} matched in Snelstart
                  • {syncResult.mandates_no_match} no-match
                </div>
                <div>
                  Machtigingen: {syncResult.machtigingen_existing} bestaand
                  {" "}• {syncResult.machtigingen_created} {syncResult.dry_run ? "zou aanmaken" : "aangemaakt"}
                </div>
                <div>
                  Verkoopboekingen: {syncResult.boekingen_scanned} gescand
                  {" "}• <strong>{syncResult.boekingen_patched}</strong> {syncResult.dry_run ? "zou patchen" : "gepatched"}
                  {" "}• {syncResult.boekingen_already_set} al gekoppeld
                </div>
                {syncResult.errors.length > 0 && (
                  <div className="text-rose-700">{syncResult.errors.length} fouten</div>
                )}
              </div>
            )}
            {(syncResult.details.length > 0 || syncResult.errors.length > 0) && (
              <details className="mt-2 text-xs">
                <summary className="cursor-pointer">Details ({syncResult.details.length} rijen)</summary>
                <ul className="mt-1 space-y-0.5">
                  {syncResult.details.map((d, i) => (
                    <li key={i} className="font-mono">
                      <span className={
                        d.outcome === "no_match_in_snelstart" ? "text-amber-700"
                        : d.outcome === "would_patch" ? "text-emerald-700"
                        : d.outcome === "patched" ? "text-emerald-700"
                        : "text-slate-500"
                      }>
                        [{d.outcome}]
                      </span>{" "}
                      <span className="text-slate-700">{d.debtor_name || d.umr}</span>
                      {d.snelstart_factuurnummer && (
                        <span className="text-slate-400"> — #{d.snelstart_factuurnummer}</span>
                      )}
                    </li>
                  ))}
                  {syncResult.errors.map((e, i) => (
                    <li key={`e${i}`} className="font-mono text-rose-700">
                      [error/{e.phase}] {e.umr || e.snelstart_factuur_id}: {e.error}
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </div>
        )}
      </div>

      <div className="overflow-hidden rounded-lg bg-white ring-1 ring-slate-200">
        <div className="overflow-x-auto">
        {listQ.isLoading && <div className="p-6 text-sm text-slate-500">Bezig met laden…</div>}
        {listQ.error && (
          <div className="p-6 text-sm text-red-700">
            {listQ.error instanceof ApiError ? listQ.error.detail : "Kon mandaten niet ophalen."}
          </div>
        )}
        {listQ.data && listQ.data.length === 0 && (
          <div className="p-10 text-center">
            <div className="text-3xl mb-2">✍️</div>
            <div className="font-medium text-slate-700">Nog geen mandaten</div>
            <div className="mt-1 text-sm text-slate-500">
              Stuur klanten naar <code className="font-mono text-xs bg-slate-100 px-1.5 py-0.5 rounded">sign.it-gemak.nl</code> om een SEPA-incassomandaat te ondertekenen.
            </div>
          </div>
        )}
        {listQ.data && listQ.data.length > 0 && (
          <>
            <div className="grid grid-cols-[140px_minmax(0,2fr)_minmax(0,1.5fr)_140px_120px_140px] min-w-[820px] gap-3 border-b border-slate-200 bg-slate-50 px-4 py-2 text-[11px] uppercase tracking-wider text-slate-500">
              <div>UMR</div>
              <div>Debiteur</div>
              <div>IBAN</div>
              <div>Status</div>
              <div>KvK</div>
              <div className="text-right">Ondertekend</div>
            </div>
            {listQ.data.map((m) => (
              <button
                key={m.id}
                onClick={() => setSelectedId(m.id)}
                className="grid grid-cols-[140px_minmax(0,2fr)_minmax(0,1.5fr)_140px_120px_140px] min-w-[820px] gap-3 border-b border-slate-100 px-4 py-3 text-left hover:bg-slate-50 w-full"
              >
                <div className="font-mono text-xs tabular-nums text-slate-700">{m.umr}</div>
                <div className="min-w-0">
                  <div className="truncate font-medium text-sm">{m.debtor_name}</div>
                  <div className="truncate text-xs text-slate-500">{m.debtor_email} · {m.debtor_city}</div>
                </div>
                <div className="font-mono text-xs tabular-nums truncate">{fmtIban(m.debtor_iban)}</div>
                <div><StatusBadge status={m.status} hasError={!!m.email_error} /></div>
                <div className="text-xs">
                  {m.debtor_kvk ? (
                    <span className={m.kvk_verified ? "text-emerald-700" : "text-slate-500"}>
                      {m.kvk_verified ? "✓ " : ""}{m.debtor_kvk}
                    </span>
                  ) : <span className="text-slate-400">—</span>}
                </div>
                <div className="text-right text-xs text-slate-500">{fmtDateTime(m.created_at)}</div>
              </button>
            ))}
          </>
        )}
      </div>
      </div>

      {selectedId && <MandateDetailDrawer id={selectedId} onClose={() => setSelectedId(null)} />}
    </div>
  );
}


function MandateDetailDrawer({ id, onClose }: { id: string; onClose: () => void }) {
  const qc = useQueryClient();
  const detailQ = useQuery<MandateDetail>({
    queryKey: ["/admin/mandates", id],
    queryFn: () => api<MandateDetail>(`/admin/mandates/${id}`),
  });

  const resendMut = useMutation({
    mutationFn: () => api(`/admin/mandates/${id}/resend-email`, { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["/admin/mandates"] });
      qc.invalidateQueries({ queryKey: ["/admin/mandates", id] });
    },
  });

  const downloadPdf = async () => {
    const token = localStorage.getItem("access_token");
    const r = await fetch(`/api/v1/admin/mandates/${id}/pdf`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!r.ok) { alert("Download mislukt: " + r.status); return; }
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `SEPA-mandaat-${detailQ.data?.umr ?? id}.pdf`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };

  const d = detailQ.data;

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-slate-900/40" onClick={onClose}>
      <div className="w-full md:max-w-2xl bg-white shadow-xl overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <div className="sticky top-0 bg-white border-b border-slate-200 px-5 py-3 flex items-center justify-between">
          <div>
            <div className="text-[11px] uppercase tracking-wider text-slate-500">SEPA-mandaat</div>
            <h2 className="text-lg font-semibold">{d?.umr ?? "…"}</h2>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700 text-xl">×</button>
        </div>

        {!d && <div className="p-6 text-sm text-slate-500">Bezig met laden…</div>}

        {d && (
          <div className="space-y-5 p-5">
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge status={d.status} hasError={!!d.email_error} />
              {d.kvk_verified && (
                <span className="inline-flex items-center rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-800">
                  ✓ KvK geverifieerd
                </span>
              )}
              <button onClick={downloadPdf} disabled={!d.has_pdf}
                className="ml-auto rounded-md bg-brand-500 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-600 disabled:opacity-50">
                ↓ Download PDF
              </button>
              {d.email_error && (
                <button onClick={() => resendMut.mutate()} disabled={resendMut.isPending}
                  className="rounded-md border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50 disabled:opacity-50">
                  {resendMut.isPending ? "Bezig…" : "↻ Email opnieuw"}
                </button>
              )}
            </div>

            {d.email_error && (
              <div className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-800">
                <div className="font-medium">Verzending mislukt</div>
                <div className="font-mono text-xs mt-1">{d.email_error}</div>
              </div>
            )}

            <Section title="Debiteur">
              <KV label="Naam" value={d.debtor_name} />
              <KV label="Adres" value={`${d.debtor_address}, ${d.debtor_postcode} ${d.debtor_city}`} />
              <KV label="Land" value={d.debtor_country} />
              <KV label="E-mail" value={d.debtor_email} />
              {d.debtor_phone && <KV label="Telefoon" value={<PhoneLink phone={d.debtor_phone} />} />}
              {d.debtor_kvk && <KV label="KvK-nummer" value={`${d.debtor_kvk}${d.kvk_verified ? " (geverifieerd)" : ""}`} />}
            </Section>

            <Section title="Bankgegevens">
              <KV label="IBAN" value={fmtIban(d.debtor_iban)} mono />
              {d.debtor_bic && <KV label="BIC" value={d.debtor_bic} mono />}
            </Section>

            <Section title="Ondertekening">
              <KV label="Plaats" value={d.sign_place} />
              <KV label="Datum" value={fmtDateTime(d.created_at) ?? "—"} />
              <div className="mt-2">
                <div className="text-[11px] uppercase tracking-wider text-slate-500 mb-1">Handtekening</div>
                {d.signature_png_base64 ? (
                  <img src={d.signature_png_base64} alt="handtekening"
                    className="max-h-32 max-w-full border border-slate-200 rounded bg-white p-2" />
                ) : (
                  <div className="text-sm text-slate-400">(geen handtekening)</div>
                )}
              </div>
            </Section>

            <Section title="Audit trail">
              {d.ip_address && <KV label="IP-adres" value={d.ip_address} mono />}
              {d.geo_country && <KV label="Locatie (bij benadering)" value={[d.geo_city, d.geo_region, d.geo_country].filter(Boolean).join(", ")} />}
              {d.geo_lat != null && d.geo_lon != null && (
                <KV label="Coordinaten" value={
                  <a href={`https://www.google.com/maps/search/?api=1&query=${d.geo_lat},${d.geo_lon}`} target="_blank" rel="noreferrer"
                    className="text-brand-600 hover:underline">
                    {d.geo_lat}, {d.geo_lon} ↗
                  </a>
                } />
              )}
              {d.user_agent && <KV label="Browser" value={<span className="font-mono text-xs">{d.user_agent}</span>} />}
              {d.emailed_at && <KV label="Verzonden om" value={fmtDateTime(d.emailed_at) ?? "—"} />}
            </Section>

            <Section title="Document-integriteit">
              <KV label="SHA-256 hash" value={<span className="font-mono text-[11px] break-all">{d.pdf_sha256 ?? "—"}</span>} />
              <KV label="PDF beschikbaar" value={d.has_pdf ? "Ja" : "Nee, niet meer op disk"} />
            </Section>
          </div>
        )}
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="border-t border-slate-200 pt-4 first:border-0 first:pt-0">
      <h3 className="text-sm font-semibold text-slate-700 mb-2">{title}</h3>
      <div className="space-y-1.5">{children}</div>
    </div>
  );
}

function KV({ label, value, mono = false }: { label: string; value: React.ReactNode; mono?: boolean }) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-[140px_minmax(0,1fr)] gap-1 md:gap-3 text-sm">
      <div className="text-slate-500">{label}</div>
      <div className={mono ? "font-mono" : ""}>{value}</div>
    </div>
  );
}
