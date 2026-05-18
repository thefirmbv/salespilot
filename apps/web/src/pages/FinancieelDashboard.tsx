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

type RecurringSummary = {
  invoice_count: number;
  line_count: number;
  annual_revenue: number;
  revenue_24m: number;
  revenue_36m: number;
  by_period: Record<string, number>;
  top_clients: { client_name: string; annual_revenue: number }[];
};

type HelpdeskMonth = {
  year: number;
  month: number;
  label: string;
  revenue: number;
  line_count: number;
};

type HelpdeskTrend = {
  accountsid: string;
  months: HelpdeskMonth[];
  average: number;
  growth_per_month: number;
  projection: HelpdeskMonth[];
  total_last_12: number;
  total_projected_next_12: number;
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
  return (
    <div className="space-y-6">
      <HaloPSABlock />
      <SnelStartBlock />
    </div>
  );
}

function HaloPSABlock() {
  const recQ = useQuery<RecurringSummary>({
    queryKey: ["/financieel/recurring-summary"],
    queryFn: () => api<RecurringSummary>("/financieel/recurring-summary"),
    staleTime: 5 * 60 * 1000,
  });
  const helpQ = useQuery<HelpdeskTrend>({
    queryKey: ["/financieel/helpdesk-trend"],
    queryFn: () => api<HelpdeskTrend>("/financieel/helpdesk-trend?months=12"),
    staleTime: 5 * 60 * 1000,
  });
  const rec = recQ.data;
  const trend = helpQ.data;
  const allMonths = trend ? [...trend.months, ...trend.projection] : [];
  const maxRev = allMonths.length ? Math.max(...allMonths.map(m => m.revenue)) : 1;

  return (
    <div className="space-y-4">
      {/* Recurring summary */}
      <section className="rounded-lg bg-white ring-1 ring-slate-200 overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-200">
          <h2 className="text-base font-medium">Recurring facturen (HaloPSA)</h2>
          <div className="text-xs text-slate-500 mt-0.5">
            Projectie op basis van alle huidige recurring-invoice regels in HaloPSA.
          </div>
        </div>
        {recQ.isLoading && <div className="p-6 text-sm text-slate-500">Laden…</div>}
        {rec && (
          <div className="p-4 space-y-4">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <KPI label="12 maanden" value={fmtEUR(rec.annual_revenue)} sub={`${rec.invoice_count} invoices · ${rec.line_count} lines`} />
              <KPI label="24 maanden" value={fmtEUR(rec.revenue_24m)} />
              <KPI label="36 maanden" value={fmtEUR(rec.revenue_36m)} />
              <KPI label="Per maand gemiddeld" value={fmtEUR(rec.annual_revenue / 12)} />
            </div>
            <div className="grid md:grid-cols-2 gap-4">
              <div>
                <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-2">Verdeling per facturatie-frequentie</div>
                <ul className="space-y-1 text-sm">
                  {Object.entries(rec.by_period).map(([k, v]) => (
                    <li key={k} className="flex justify-between border-b border-slate-100 py-1">
                      <span className="capitalize">{k}</span>
                      <span className="tabular-nums font-medium">{fmtEUR(v)}</span>
                    </li>
                  ))}
                </ul>
              </div>
              <div>
                <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-2">Top 10 klanten (jaaromzet recurring)</div>
                <ul className="space-y-1 text-sm">
                  {rec.top_clients.map(c => (
                    <li key={c.client_name} className="flex justify-between border-b border-slate-100 py-1">
                      <span className="truncate pr-2">{c.client_name}</span>
                      <span className="tabular-nums font-medium">{fmtEUR(c.annual_revenue)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </div>
        )}
      </section>

      {/* Helpdesk trend */}
      <section className="rounded-lg bg-white ring-1 ring-slate-200 overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-200">
          <h2 className="text-base font-medium">8041 Helpdesk en Ad-hoc</h2>
          <div className="text-xs text-slate-500 mt-0.5">
            Omzet van werkuren ad-hoc per maand, met lineaire trend-projectie 12 mnd vooruit.
          </div>
        </div>
        {helpQ.isLoading && <div className="p-6 text-sm text-slate-500">Laden…</div>}
        {trend && (
          <div className="p-4 space-y-4">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <KPI label="Gemiddeld/mnd" value={fmtEUR(trend.average)} />
              <KPI label="Trend/mnd" value={(trend.growth_per_month >= 0 ? "+" : "") + fmtEUR(trend.growth_per_month)} sub="lineair fit" />
              <KPI label="Afgelopen 12 mnd" value={fmtEUR(trend.total_last_12)} />
              <KPI label="Projectie 12 mnd" value={fmtEUR(trend.total_projected_next_12)} sub={trend.total_projected_next_12 > trend.total_last_12 ? "📈 groei" : "📉 daling"} />
            </div>

            {/* Inline SVG chart */}
            <div className="rounded-md bg-slate-50 p-3">
              <HelpdeskChart months={trend.months} projection={trend.projection} max={maxRev} />
            </div>

            {/* Tabel onder de grafiek */}
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-[10px] uppercase tracking-wider text-slate-500">
                    <th className="text-left px-2 py-1">Maand</th>
                    <th className="text-right px-2 py-1">Omzet werkelijk</th>
                    <th className="text-right px-2 py-1">Projectie</th>
                    <th className="text-right px-2 py-1">Lines</th>
                  </tr>
                </thead>
                <tbody>
                  {trend.months.map(m => (
                    <tr key={m.label} className="border-t border-slate-100">
                      <td className="px-2 py-1 font-mono text-xs">{m.label}</td>
                      <td className="px-2 py-1 text-right tabular-nums">{fmtEUR(m.revenue)}</td>
                      <td className="px-2 py-1 text-right text-slate-300">—</td>
                      <td className="px-2 py-1 text-right tabular-nums text-xs text-slate-500">{m.line_count}</td>
                    </tr>
                  ))}
                  {trend.projection.map(m => (
                    <tr key={m.label} className="border-t border-slate-100 bg-amber-50/50">
                      <td className="px-2 py-1 font-mono text-xs">{m.label}</td>
                      <td className="px-2 py-1 text-right text-slate-300">—</td>
                      <td className="px-2 py-1 text-right tabular-nums text-amber-700">{fmtEUR(m.revenue)}</td>
                      <td className="px-2 py-1 text-right text-slate-300">—</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}

function HelpdeskChart({ months, projection, max }: { months: HelpdeskMonth[]; projection: HelpdeskMonth[]; max: number }) {
  const all = [...months, ...projection];
  const W = 720, H = 220, PADL = 50, PADR = 10, PADT = 10, PADB = 24;
  const innerW = W - PADL - PADR, innerH = H - PADT - PADB;
  const xStep = innerW / Math.max(1, all.length);

  const xy = (i: number, v: number) => ({
    x: PADL + i * xStep + xStep / 2,
    y: PADT + innerH - (max > 0 ? (v / max) * innerH : 0),
  });

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" preserveAspectRatio="xMidYMid meet">
      {/* gridlines */}
      {[0, 0.25, 0.5, 0.75, 1].map(f => (
        <line key={f} x1={PADL} x2={W - PADR}
          y1={PADT + innerH * (1 - f)} y2={PADT + innerH * (1 - f)}
          stroke="#e5e7eb" strokeDasharray="2,3" />
      ))}
      {/* Y labels */}
      {[0, 0.5, 1].map(f => (
        <text key={f} x={PADL - 5} y={PADT + innerH * (1 - f) + 4}
          textAnchor="end" fontSize="9" fill="#64748b">
          €{Math.round((max * f) / 1000)}k
        </text>
      ))}
      {/* werkelijk (blauw) */}
      {months.map((m, i) => {
        const p = xy(i, m.revenue);
        return (
          <g key={m.label}>
            <rect x={p.x - xStep / 3} y={p.y} width={xStep * 0.66} height={PADT + innerH - p.y}
              fill="#3b82f6" rx="1" />
          </g>
        );
      })}
      {/* projectie (amber) */}
      {projection.map((m, i) => {
        const p = xy(months.length + i, m.revenue);
        return (
          <g key={m.label}>
            <rect x={p.x - xStep / 3} y={p.y} width={xStep * 0.66} height={PADT + innerH - p.y}
              fill="#f59e0b" rx="1" opacity="0.8" />
          </g>
        );
      })}
      {/* X labels */}
      {all.map((m, i) => {
        if (i % 2 !== 0 && all.length > 14) return null;
        const p = xy(i, 0);
        return (
          <text key={m.label} x={p.x} y={H - 6} textAnchor="middle" fontSize="9" fill="#64748b">
            {m.label.slice(2)}
          </text>
        );
      })}
      {/* Legend */}
      <g transform={`translate(${PADL + 10}, ${PADT + 5})`}>
        <rect width="10" height="10" fill="#3b82f6" rx="1" />
        <text x="14" y="9" fontSize="10" fill="#374151">werkelijk</text>
        <rect x="80" width="10" height="10" fill="#f59e0b" rx="1" opacity="0.8" />
        <text x="94" y="9" fontSize="10" fill="#374151">projectie</text>
      </g>
    </svg>
  );
}

function SnelStartBlock() {
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
