import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

type SepaRow = {
  factuur_id: string | null;
  factuurnummer: string | null;
  factuurdatum: string | null;
  relatie_id: string | null;
  relatie_naam: string;
  bedrag: number;
  action: string;
};

type SepaResult = {
  ok: boolean;
  dry_run: boolean;
  scanned: number;
  missing_flag: number;
  fixable: number;
  fixed: number;
  rows: SepaRow[];
  errors: { factuur_id?: string | null; factuurnummer?: string | null; error: string }[];
};

const fmtEUR = (v: number) =>
  v.toLocaleString("nl-NL", { style: "currency", currency: "EUR" });

const fmtDate = (s: string | null | undefined) => {
  if (!s) return "—";
  try {
    return new Date(s).toLocaleDateString("nl-NL", {
      day: "2-digit", month: "short", year: "numeric",
    });
  } catch { return s; }
};

export function SepaFix() {
  const qc = useQueryClient();
  const [daysBack, setDaysBack] = useState(90);
  const [preview, setPreview] = useState<SepaResult | null>(null);
  const [appliedResult, setAppliedResult] = useState<SepaResult | null>(null);

  const previewMut = useMutation({
    mutationFn: () =>
      api<SepaResult>("/snelstart/sepa-fix/preview", {
        method: "POST",
        body: JSON.stringify({ days_back: daysBack }),
      }),
    onSuccess: (data) => {
      setPreview(data);
      setAppliedResult(null);
    },
  });

  const applyMut = useMutation({
    mutationFn: () =>
      api<SepaResult>("/snelstart/sepa-fix/apply", {
        method: "POST",
        body: JSON.stringify({ days_back: daysBack }),
      }),
    onSuccess: (data) => {
      setAppliedResult(data);
      setPreview(null);
      qc.invalidateQueries({ queryKey: ["/snelstart/dashboard"] });
    },
  });

  const result = appliedResult || preview;
  const isApplied = !!appliedResult;
  const isLoading = previewMut.isPending || applyMut.isPending;

  return (
    <div className="space-y-4">
      <div className="rounded-lg bg-white ring-1 ring-slate-200 p-4">
        <h1 className="text-lg font-medium">SEPA bulk-fix</h1>
        <p className="mt-1 text-sm text-slate-600">
          Verkoopfacturen uit SnelStart waarbij de SEPA-incasso-vlag <code>isIncasso</code>{" "}
          NIET aanstaat, terwijl de bijbehorende relatie wèl een geldige incassomachtiging
          heeft. HaloPSA exporteert facturen soms zonder deze vlag. Hier zet je 'm voor
          alle gedetecteerde rijen in één klik aan.
        </p>
      </div>

      <div className="rounded-lg bg-white ring-1 ring-slate-200 p-4">
        <div className="flex items-end gap-3 flex-wrap">
          <div>
            <label className="block text-xs uppercase tracking-wider text-slate-500 font-semibold mb-1">
              Zoekvenster
            </label>
            <select
              value={daysBack}
              onChange={(e) => setDaysBack(Number(e.target.value))}
              className="rounded-md border border-slate-300 px-3 py-2 text-sm"
            >
              <option value={30}>Laatste 30 dagen</option>
              <option value={60}>Laatste 60 dagen</option>
              <option value={90}>Laatste 90 dagen</option>
              <option value={180}>Laatste 6 maanden</option>
              <option value={365}>Laatste jaar</option>
            </select>
          </div>
          <button
            onClick={() => previewMut.mutate()}
            disabled={isLoading}
            className="rounded-md bg-slate-100 hover:bg-slate-200 px-4 py-2 text-sm font-medium disabled:opacity-50"
          >
            {previewMut.isPending ? "Bezig..." : "1. Preview (geen wijzigingen)"}
          </button>
          {preview && preview.fixable > 0 && (
            <button
              onClick={() => {
                if (confirm(
                  `Weet je zeker dat je voor ${preview.fixable} factu(u)r(en) ` +
                  `de isIncasso-vlag op true wilt zetten? Dit kan niet ongedaan worden ` +
                  `gemaakt vanuit SalesPilot (wel in SnelStart zelf).`
                )) {
                  applyMut.mutate();
                }
              }}
              disabled={isLoading}
              className="rounded-md bg-emerald-600 hover:bg-emerald-700 text-white px-4 py-2 text-sm font-medium disabled:opacity-50"
            >
              {applyMut.isPending ? "Bezig..." : `2. Apply (${preview.fixable} facturen fixen)`}
            </button>
          )}
        </div>
        {previewMut.isError && (
          <div className="mt-3 rounded-md bg-rose-50 border border-rose-200 p-3 text-sm text-rose-900">
            Preview mislukt: {(previewMut.error as Error).message}
          </div>
        )}
        {applyMut.isError && (
          <div className="mt-3 rounded-md bg-rose-50 border border-rose-200 p-3 text-sm text-rose-900">
            Apply mislukt: {(applyMut.error as Error).message}
          </div>
        )}
      </div>

      {result && (
        <>
          {/* KPI strip */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <Stat label="Gescand" value={result.scanned} />
            <Stat label="Zonder vlag" value={result.missing_flag} tone="amber" />
            <Stat label="Fixable" value={result.fixable} tone="brand" />
            <Stat
              label={isApplied ? "Gefixt" : "Geselecteerd"}
              value={isApplied ? result.fixed : result.fixable}
              tone={isApplied ? "emerald" : "slate"}
            />
          </div>

          {isApplied && (
            <div className="rounded-md bg-emerald-50 border border-emerald-200 p-3 text-sm text-emerald-900">
              ✓ {result.fixed} factuur/facturen zijn bijgewerkt in SnelStart.
              {result.errors.length > 0 && (
                <> {result.errors.length} fouten — zie onderaan.</>
              )}
            </div>
          )}

          {/* Rijen */}
          <div className="rounded-lg bg-white ring-1 ring-slate-200 overflow-hidden">
            <div className="grid grid-cols-[100px_100px_minmax(0,1fr)_140px_100px] gap-3 border-b border-slate-200 px-4 py-2 text-[10px] uppercase tracking-wider text-slate-500">
              <div>Factuurnr.</div>
              <div>Datum</div>
              <div>Relatie</div>
              <div className="text-right">Bedrag</div>
              <div className="text-right">Status</div>
            </div>
            {result.rows.length === 0 ? (
              <div className="p-8 text-center text-sm text-slate-500">
                Geen facturen gevonden waarvoor de SEPA-vlag mist
                terwijl er een geldige machtiging is. Alle administratie is op orde 🎉
              </div>
            ) : (
              result.rows.map((r, i) => (
                <div
                  key={r.factuur_id || i}
                  className="grid grid-cols-[100px_100px_minmax(0,1fr)_140px_100px] gap-3 border-b border-slate-100 px-4 py-2 text-sm hover:bg-slate-50"
                >
                  <div className="font-mono text-xs">{r.factuurnummer || "—"}</div>
                  <div className="text-xs text-slate-500">{fmtDate(r.factuurdatum)}</div>
                  <div className="truncate">{r.relatie_naam || "(onbekend)"}</div>
                  <div className="text-right tabular-nums">{fmtEUR(r.bedrag)}</div>
                  <div className="text-right">
                    <ActionPill action={r.action} />
                  </div>
                </div>
              ))
            )}
          </div>

          {result.errors.length > 0 && (
            <div className="rounded-lg bg-rose-50 ring-1 ring-rose-200 p-4">
              <div className="text-sm font-medium text-rose-900 mb-2">
                Fouten ({result.errors.length})
              </div>
              <ul className="text-xs text-rose-900 space-y-1 font-mono">
                {result.errors.map((e, i) => (
                  <li key={i}>
                    {e.factuurnummer || e.factuur_id || "?"}: {e.error}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function Stat({ label, value, tone = "slate" }: { label: string; value: number; tone?: string }) {
  const colors: Record<string, string> = {
    slate: "text-slate-900",
    brand: "text-brand-600",
    emerald: "text-emerald-700",
    amber: "text-amber-700",
  };
  return (
    <div className="rounded-lg bg-white ring-1 ring-slate-200 p-3">
      <div className="text-xs uppercase tracking-wider text-slate-500 font-semibold">{label}</div>
      <div className={`mt-1 text-2xl font-medium tabular-nums ${colors[tone] || colors.slate}`}>
        {value.toLocaleString("nl-NL")}
      </div>
    </div>
  );
}

function ActionPill({ action }: { action: string }) {
  const map: Record<string, { bg: string; fg: string; label: string }> = {
    would_fix: { bg: "#FAEEDA", fg: "#633806", label: "wordt gefixt" },
    fixing:    { bg: "#E0F2FE", fg: "#0C4A6E", label: "bezig..." },
    fixed:     { bg: "#DCFCE7", fg: "#15803D", label: "✓ gefixt" },
    error:     { bg: "#FCE7E7", fg: "#9F1239", label: "✗ fout" },
  };
  const s = map[action] || { bg: "#F1F5F9", fg: "#475569", label: action };
  return (
    <span
      className="inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium"
      style={{ backgroundColor: s.bg, color: s.fg }}
    >
      {s.label}
    </span>
  );
}

export default SepaFix;
