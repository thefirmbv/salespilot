import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

type DashboardGroup = { id: string; naam: string };
type DashboardResponse = {
  months: string[];
  groups: DashboardGroup[];
  matrix: Record<string, Record<string, number>>;
  totals_per_month: Record<string, number>;
  totals_per_group: Record<string, number>;
  grand_total: number;
  invoice_count: number;
  from_date: string;
  to_date: string;
};

const fmtEUR = (v: number) =>
  v.toLocaleString("nl-NL", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
const fmtEURexact = (v: number) =>
  v.toLocaleString("nl-NL", { style: "currency", currency: "EUR" });

const monthLabel = (m: string) => {
  // "2026-05" -> "mei 2026"
  const [y, mm] = m.split("-");
  const names = ["jan","feb","mrt","apr","mei","jun","jul","aug","sep","okt","nov","dec"];
  const idx = parseInt(mm, 10) - 1;
  return `${names[idx] || mm} ${y}`;
};

export function FinancieelDashboard() {
  const [months, setMonths] = useState(4);
  const dataQ = useQuery<DashboardResponse>({
    queryKey: ["/snelstart/dashboard", months],
    queryFn: () => api<DashboardResponse>(`/snelstart/dashboard?months=${months}`),
    // Caching: 5 min so refreshing the page doesn't hammer SnelStart
    staleTime: 5 * 60 * 1000,
  });

  if (dataQ.isLoading) {
    return (
      <div className="rounded-lg bg-white ring-1 ring-slate-200 p-8 text-center text-sm text-slate-500">
        Bezig met ophalen uit SnelStart…
      </div>
    );
  }

  if (dataQ.isError) {
    const msg = (dataQ.error as Error).message;
    return (
      <div className="rounded-lg bg-rose-50 ring-1 ring-rose-200 p-4 text-sm text-rose-900">
        <strong>SnelStart niet bereikbaar:</strong> {msg}
        <div className="mt-2 text-xs">
          Check de configuratie op{" "}
          <a className="underline" href="/settings/integrations/snelstart">/settings/integrations/snelstart</a>.
        </div>
      </div>
    );
  }

  const d = dataQ.data!;
  // Max waarde voor relatieve schaal van staafjes
  const maxValue = Math.max(
    ...Object.values(d.totals_per_month),
    1,
  );

  return (
    <div className="space-y-4">
      <div className="rounded-lg bg-white ring-1 ring-slate-200 p-4">
        <div className="flex items-baseline justify-between gap-3 flex-wrap">
          <div>
            <h1 className="text-lg font-medium">Financieel dashboard</h1>
            <p className="mt-1 text-sm text-slate-600">
              Maand-omzet per groep uit SnelStart, op basis van verkoopfacturen.
              Wat in SnelStart alleen ad-hoc te zien is, hier per maand.
            </p>
          </div>
          <div>
            <label className="block text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-1">
              Aantal maanden
            </label>
            <select
              value={months}
              onChange={(e) => setMonths(Number(e.target.value))}
              className="rounded-md border border-slate-300 px-3 py-1.5 text-sm"
            >
              <option value={3}>3 maanden</option>
              <option value={4}>4 maanden</option>
              <option value={6}>6 maanden</option>
              <option value={12}>12 maanden</option>
            </select>
          </div>
        </div>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <KPI label="Totaal omzet" value={fmtEUR(d.grand_total)} sub={`${d.invoice_count} facturen`} />
        <KPI label="Gem. per maand" value={fmtEUR(d.grand_total / Math.max(d.months.length, 1))} />
        <KPI label="Aantal groepen" value={String(d.groups.length)} />
        <KPI label="Periode" value={`${monthLabel(d.months[0])} t/m ${monthLabel(d.months[d.months.length - 1])}`} sub="laatste tikje vandaag" />
      </div>

      {/* Maand-totalen als visuele staven */}
      <div className="rounded-lg bg-white ring-1 ring-slate-200 p-4">
        <div className="text-xs uppercase tracking-wider text-slate-500 font-semibold mb-3">
          Maand-totalen
        </div>
        <div className="space-y-2">
          {d.months.map((m) => {
            const v = d.totals_per_month[m] || 0;
            const w = (v / maxValue) * 100;
            return (
              <div key={m} className="grid grid-cols-[100px_minmax(0,1fr)_130px] gap-2 items-center">
                <div className="text-sm text-slate-700">{monthLabel(m)}</div>
                <div className="h-5 bg-slate-100 rounded overflow-hidden">
                  <div
                    className="h-full bg-brand-500"
                    style={{ width: `${w}%` }}
                  />
                </div>
                <div className="text-sm tabular-nums text-right">{fmtEURexact(v)}</div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Matrix: rij = groep, kolom = maand */}
      <div className="rounded-lg bg-white ring-1 ring-slate-200 overflow-hidden">
        <div className="border-b border-slate-200 px-4 py-2 text-xs uppercase tracking-wider text-slate-500 font-semibold">
          Per groep
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-[10px] uppercase tracking-wider text-slate-500">
                <th className="text-left px-4 py-2 sticky left-0 bg-white">Groep</th>
                {d.months.map((m) => (
                  <th key={m} className="text-right px-4 py-2 whitespace-nowrap">{monthLabel(m)}</th>
                ))}
                <th className="text-right px-4 py-2 bg-slate-50 border-l border-slate-200">Totaal</th>
              </tr>
            </thead>
            <tbody>
              {d.groups.map((g) => {
                const rowTotal = d.totals_per_group[g.id] || 0;
                return (
                  <tr key={g.id} className="border-t border-slate-100 hover:bg-slate-50">
                    <td className="px-4 py-2 sticky left-0 bg-white font-medium">{g.naam}</td>
                    {d.months.map((m) => {
                      const v = (d.matrix[g.id] || {})[m] || 0;
                      return (
                        <td key={m} className="text-right px-4 py-2 tabular-nums">
                          {v > 0 ? fmtEURexact(v) : <span className="text-slate-300">—</span>}
                        </td>
                      );
                    })}
                    <td className="text-right px-4 py-2 tabular-nums bg-slate-50 border-l border-slate-200 font-medium">
                      {fmtEURexact(rowTotal)}
                    </td>
                  </tr>
                );
              })}
              {/* Totaalrij */}
              <tr className="border-t-2 border-slate-300 bg-slate-50">
                <td className="px-4 py-2 sticky left-0 bg-slate-50 font-semibold">Totaal</td>
                {d.months.map((m) => (
                  <td key={m} className="text-right px-4 py-2 tabular-nums font-semibold">
                    {fmtEURexact(d.totals_per_month[m] || 0)}
                  </td>
                ))}
                <td className="text-right px-4 py-2 tabular-nums bg-white border-l border-slate-200 font-bold">
                  {fmtEURexact(d.grand_total)}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function KPI({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-lg bg-white ring-1 ring-slate-200 p-3">
      <div className="text-xs uppercase tracking-wider text-slate-500 font-semibold">{label}</div>
      <div className="mt-1 text-xl font-medium tabular-nums">{value}</div>
      {sub && <div className="text-[11px] text-slate-500 mt-0.5">{sub}</div>}
    </div>
  );
}

export default FinancieelDashboard;
