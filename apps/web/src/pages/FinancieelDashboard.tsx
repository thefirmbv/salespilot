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

type RevenueMonth = {
  year: number;
  month: number;
  label: string;
  revenue: number;
  invoice_count: number;
  is_current_month: boolean;
  is_projection: boolean;
  pending_recurring: number;
  pending_labor_estimate: number;
  acquisition_uplift: number;
};

type GrowthProjection = {
  months_history: RevenueMonth[];
  current_month: RevenueMonth | null;
  months_projection: RevenueMonth[];
  average_per_month: number;
  growth_per_month: number;
  year_to_date: number;
  projection_full_year_linear: number;
  projection_full_year_average: number;
  projection_full_year_with_acquisition: number;
  target_one_million: number;
  target_pct_achieved: number;
  target_pct_projected: number;
  target_met: boolean;
  target_gap_to_million: number;
  avg_deals_won_per_month: number;
  avg_deal_amount: number;
  acquisition_recurring_fraction: number;
  acquisition_monthly_uplift: number;
};

type ClientRevenueRow = {
  client_name: string;
  revenue: number;
  invoice_count: number;
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
  const modernQ = useQuery<HelpdeskTrend>({
    queryKey: ["/financieel/account-trend", "251"],
    queryFn: () => api<HelpdeskTrend>("/financieel/account-trend?accountsid=251&months=12"),
    staleTime: 5 * 60 * 1000,
  });
  const [openLabor, setOpenLabor] = useState(0);
  const [includeAcq, setIncludeAcq] = useState(true);
  const growthQ = useQuery<GrowthProjection>({
    queryKey: ["/financieel/revenue-growth", openLabor, includeAcq],
    queryFn: () => api<GrowthProjection>(
      `/financieel/revenue-growth?months=24&open_labor_estimate=${openLabor}&include_acquisition=${includeAcq}`
    ),
    staleTime: 5 * 60 * 1000,
  });
  const actualClientsQ = useQuery<ClientRevenueRow[]>({
    queryKey: ["/financieel/top-clients-actual"],
    queryFn: () => api<ClientRevenueRow[]>("/financieel/top-clients-actual?limit=10&months=12"),
    staleTime: 5 * 60 * 1000,
  });
  const rec = recQ.data;
  const growth = growthQ.data;
  const actualClients = actualClientsQ.data;

  return (
    <div className="space-y-4">
      {/* === Algehele groei + EUR 1M target === */}
      <RevenueGrowthBlock data={growth} loading={growthQ.isLoading} openLabor={openLabor} setOpenLabor={setOpenLabor} includeAcq={includeAcq} setIncludeAcq={setIncludeAcq} />

      {/* Recurring summary */}
      <section className="rounded-lg bg-white ring-1 ring-slate-200 overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-200">
          <h2 className="text-base font-medium">Recurring facturen (HaloPSA)</h2>
          <div className="text-xs text-slate-500 mt-0.5">
            Projectie op basis van huidige recurring-invoice regels. Eenmalige facturen tellen hier NIET mee.
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
                <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-2">Top 10 klanten op recurring jaarprojectie <span className="text-slate-400 normal-case font-normal">(alleen recurring-invoices)</span></div>
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

      {/* Top klanten op werkelijke omzet (12 mnd posted invoices) */}
      <section className="rounded-lg bg-white ring-1 ring-slate-200 overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-200 flex items-baseline justify-between flex-wrap gap-2">
          <div>
            <h2 className="text-base font-medium">Top 10 klanten — werkelijke omzet 12 mnd</h2>
            <div className="text-xs text-slate-500 mt-0.5">
              Op basis van geboekte facturen. Project-werk + eenmalig + recurring samen.
            </div>
          </div>
        </div>
        {actualClientsQ.isLoading && <div className="p-4 text-sm text-slate-500">Laden…</div>}
        {actualClients && (
          <ul className="divide-y divide-slate-100">
            {actualClients.map((c, i) => (
              <li key={c.client_name} className="flex items-baseline justify-between px-4 py-1.5 text-sm">
                <div className="flex items-baseline gap-2 truncate pr-2">
                  <span className="text-slate-400 tabular-nums text-xs w-5">{i + 1}.</span>
                  <span className="truncate">{c.client_name}</span>
                  <span className="text-[10px] text-slate-400">({c.invoice_count} invs)</span>
                </div>
                <span className="tabular-nums font-medium">{fmtEUR(c.revenue)}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Helpdesk trend (compact: chart links, tabel rechts) */}
      <AccountTrendBlock
        title="8041 Helpdesk en Ad-hoc"
        subtitle="Werkuren ad-hoc per maand, lineaire trend 12 mnd vooruit."
        trend={helpQ.data}
        loading={helpQ.isLoading}
      />

      {/* Modern Work growth (8044) */}
      <AccountTrendBlock
        title="8044 Modern Work | Recurring"
        subtitle="Modern Workspace jaarfacturatie -- actief verkocht, dus we monitoren de groei."
        trend={modernQ.data}
        loading={modernQ.isLoading}
        barColor="#10b981"
        projColor="#a7f3d0"
      />
    </div>
  );
}

function RevenueGrowthBlock({
  data, loading, openLabor, setOpenLabor, includeAcq, setIncludeAcq,
}: {
  data: GrowthProjection | undefined;
  loading: boolean;
  openLabor: number;
  setOpenLabor: (n: number) => void;
  includeAcq: boolean;
  setIncludeAcq: (b: boolean) => void;
}) {
  if (loading) {
    return (
      <section className="rounded-lg bg-white ring-1 ring-slate-200 p-4 text-sm text-slate-500">
        Laden algehele omzet-groei…
      </section>
    );
  }
  if (!data) return null;

  const allBars = [
    ...data.months_history,
    ...(data.current_month ? [data.current_month] : []),
    ...data.months_projection,
  ];
  const max = Math.max(
    ...allBars.map(m =>
      m.revenue +
      (m.pending_recurring || 0) +
      (m.pending_labor_estimate || 0)
    ),
    data.target_one_million / 12,
    1,
  );
  const targetLine = data.target_one_million / 12;
  const met = data.target_met;

  return (
    <section className="rounded-lg bg-white ring-1 ring-slate-200 overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-200">
        <h2 className="text-base font-medium">Algehele omzet-groei — €1M doel {met ? "🎯" : ""}</h2>
        <div className="text-xs text-slate-500 mt-0.5">
          Werkelijke omzet per maand + projectie naar eind kalenderjaar.
          Lopende maand telt NIET in trend-fit (incomplete data).
        </div>
      </div>
      <div className="p-3 space-y-3">
        {/* KPI strip */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
          <KPIMini label="YTD 2026 (incl. te factureren)" value={fmtEUR(data.year_to_date)} />
          <KPIMini
            label="Projectie lineair"
            value={fmtEUR(data.projection_full_year_linear)}
            tone={data.projection_full_year_linear >= data.target_one_million ? "emerald" : "rose"}
          />
          <KPIMini
            label="Projectie + acquisitie"
            value={fmtEUR(data.projection_full_year_with_acquisition)}
            tone={met ? "emerald" : "rose"}
          />
          <KPIMini
            label="€1M doel"
            value={`${data.target_pct_projected.toFixed(1)}%`}
            tone={met ? "emerald" : "rose"}
          />
        </div>

        {/* Lopende maand expliciet */}
        {data.current_month && (
          <div className="rounded-md bg-blue-50 border border-blue-200 px-3 py-2 text-xs flex items-baseline justify-between flex-wrap gap-2">
            <div className="text-blue-900">
              <strong>Lopende maand {data.current_month.label}</strong>:
              gefactureerd <strong>{fmtEUR(data.current_month.revenue)}</strong>
              {data.current_month.pending_recurring > 0 && (
                <> + nog te factureren recurring <strong className="text-emerald-700">{fmtEUR(data.current_month.pending_recurring)}</strong></>
              )}
              {" "}= verwacht <strong>{fmtEUR(data.current_month.revenue + data.current_month.pending_recurring + data.current_month.pending_labor_estimate)}</strong>
            </div>
          </div>
        )}

        {/* Acquisitie + open labor inputs */}
        <div className="grid md:grid-cols-2 gap-3 rounded-md bg-slate-50 px-3 py-2 text-xs">
          <label className="flex items-baseline gap-2">
            <span className="text-slate-600 whitespace-nowrap">Open labor schatting (€):</span>
            <input
              type="number" min="0" step="500" value={openLabor}
              onChange={(e) => setOpenLabor(Math.max(0, parseFloat(e.target.value) || 0))}
              className="flex-1 rounded border border-slate-300 px-2 py-0.5 text-sm tabular-nums max-w-[140px]"
              placeholder="0"
            />
            <span className="text-[10px] text-slate-400">geboekte uren × tarief uit HaloPSA</span>
          </label>
          <label className="flex items-baseline gap-2">
            <input
              type="checkbox" checked={includeAcq}
              onChange={(e) => setIncludeAcq(e.target.checked)}
            />
            <span className="text-slate-600">Acquisitie meerekenen</span>
            <span className="text-[10px] text-slate-400">
              {data.avg_deals_won_per_month.toFixed(1)} deals/mnd × €{data.avg_deal_amount.toFixed(0)} ×
              {" "}{(data.acquisition_recurring_fraction * 100).toFixed(0)}% recurring
              {" "}= <strong>+€{data.acquisition_monthly_uplift.toFixed(0)}/mnd extra</strong>
            </span>
          </label>
        </div>

        {/* Target-balk */}
        <div className="space-y-1">
          <div className="flex justify-between text-[11px] text-slate-500">
            <span>Voortgang naar €1M</span>
            <span className={met ? "text-emerald-700 font-medium" : "text-rose-700 font-medium"}>
              {met
                ? `✓ €1M wordt gehaald (+${fmtEUR(-data.target_gap_to_million)})`
                : `✗ Tekort: ${fmtEUR(data.target_gap_to_million)}`}
            </span>
          </div>
          <div className="relative h-3 bg-slate-100 rounded overflow-hidden">
            <div
              className={`absolute left-0 top-0 h-full ${met ? "bg-emerald-500" : "bg-amber-400"}`}
              style={{ width: `${Math.min(100, data.target_pct_projected)}%` }}
            />
            <div
              className="absolute top-0 h-full bg-blue-500"
              style={{ width: `${Math.min(100, data.target_pct_achieved)}%` }}
            />
          </div>
          <div className="flex justify-between text-[10px] text-slate-500">
            <span><span className="inline-block w-2 h-2 bg-blue-500 rounded-sm align-middle mr-1" />Gerealiseerd YTD: {data.target_pct_achieved.toFixed(1)}%</span>
            <span><span className={`inline-block w-2 h-2 ${met ? "bg-emerald-500" : "bg-amber-400"} rounded-sm align-middle mr-1`} />Inclusief projectie: {data.target_pct_projected.toFixed(1)}%</span>
          </div>
        </div>

        {/* Chart */}
        <div className="rounded-md bg-slate-50 p-2">
          <RevenueChart
            history={data.months_history}
            currentMonth={data.current_month}
            projection={data.months_projection}
            max={max}
            targetLine={targetLine}
          />
        </div>

        <div className="text-[11px] text-slate-500 flex flex-wrap gap-4">
          <span>Gemiddeld (excl. lopend): <strong>{fmtEUR(data.average_per_month)}/mnd</strong></span>
          <span>Trend: <strong className={data.growth_per_month >= 0 ? "text-emerald-700" : "text-rose-700"}>{data.growth_per_month >= 0 ? "+" : ""}{fmtEUR(data.growth_per_month)}/mnd</strong></span>
          <span>Nodig voor €1M: <strong>{fmtEUR(83333)}/mnd</strong></span>
        </div>
      </div>
    </section>
  );
}

function RevenueChart({ history, currentMonth, projection, max, targetLine }: {
  history: RevenueMonth[];
  currentMonth: RevenueMonth | null;
  projection: RevenueMonth[];
  max: number;
  targetLine: number;
}) {
  const allMonths = [
    ...history,
    ...(currentMonth ? [currentMonth] : []),
    ...projection,
  ];
  const W = 720, H = 220, PADL = 50, PADR = 8, PADT = 28, PADB = 22;
  const innerW = W - PADL - PADR, innerH = H - PADT - PADB;
  const xStep = innerW / Math.max(1, allMonths.length);

  // Returns y-pixel voor revenue v, scaled to max
  const yFor = (v: number) => PADT + innerH - (max > 0 ? (v / max) * innerH : 0);
  const xCenter = (i: number) => PADL + i * xStep + xStep / 2;
  const barW = xStep * 0.66;

  const targetY = yFor(targetLine);
  let xi = 0;

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
      {/* Target-lijn */}
      <line x1={PADL} x2={W - PADR} y1={targetY} y2={targetY}
        stroke="#dc2626" strokeWidth="1.5" strokeDasharray="5,3" />
      <text x={W - PADR - 4} y={targetY - 3} textAnchor="end" fontSize="9" fill="#dc2626" fontWeight="600">
        €1M doel: €{Math.round(targetLine / 1000)}k/mnd
      </text>

      {/* werkelijk afgeronde maanden (blauw) */}
      {history.map((m) => {
        const cx = xCenter(xi++);
        const y = yFor(m.revenue);
        return (
          <rect key={m.label} x={cx - barW / 2} y={y}
            width={barW} height={PADT + innerH - y}
            fill="#3b82f6" rx="1" />
        );
      })}

      {/* lopende maand: blauw onder + emerald (pending) bovenop, gestippelde rand */}
      {currentMonth && (() => {
        const cx = xCenter(xi++);
        const blueH = PADT + innerH - yFor(currentMonth.revenue);
        const pending = currentMonth.pending_recurring + currentMonth.pending_labor_estimate;
        const pendingTopY = yFor(currentMonth.revenue + pending);
        const totalTopY = yFor(currentMonth.revenue + pending);
        return (
          <g key={currentMonth.label}>
            {/* blauw deel: werkelijk */}
            <rect x={cx - barW / 2} y={yFor(currentMonth.revenue)}
              width={barW} height={blueH} fill="#3b82f6" rx="1" />
            {/* emerald deel: nog te factureren */}
            {pending > 0 && (
              <rect x={cx - barW / 2} y={pendingTopY}
                width={barW} height={yFor(currentMonth.revenue) - pendingTopY}
                fill="#10b981" opacity="0.85" rx="1" />
            )}
            {/* gestippelde rand om hele staaf */}
            <rect x={cx - barW / 2} y={totalTopY}
              width={barW} height={PADT + innerH - totalTopY}
              fill="none" stroke="#0f172a" strokeWidth="1" strokeDasharray="2,2" />
            {/* "lopend" label */}
            <text x={cx} y={totalTopY - 4} textAnchor="middle" fontSize="8"
              fill="#0f172a" fontWeight="600">
              lopend
            </text>
          </g>
        );
      })()}

      {/* projectie: amber basis + emerald acquisitie top */}
      {projection.map((m) => {
        const cx = xCenter(xi++);
        const basis = m.revenue - m.acquisition_uplift;
        const basisY = yFor(basis);
        const totalY = yFor(m.revenue);
        return (
          <g key={m.label}>
            <rect x={cx - barW / 2} y={basisY}
              width={barW} height={PADT + innerH - basisY}
              fill="#f59e0b" opacity="0.85" rx="1" />
            {m.acquisition_uplift > 0 && (
              <rect x={cx - barW / 2} y={totalY}
                width={barW} height={basisY - totalY}
                fill="#10b981" opacity="0.85" rx="1" />
            )}
          </g>
        );
      })}

      {/* X labels */}
      {allMonths.map((m, i) => {
        if (i % 2 !== 0 && allMonths.length > 14) return null;
        const x = xCenter(i);
        return (
          <text key={m.label} x={x} y={H - 6} textAnchor="middle" fontSize="9" fill="#64748b">
            {m.label.slice(2)}
          </text>
        );
      })}

      {/* Legend */}
      <g transform={`translate(${PADL + 4}, 6)`}>
        <rect width="10" height="10" fill="#3b82f6" rx="1" />
        <text x="14" y="9" fontSize="10" fill="#374151">werkelijk</text>
        <rect x="76" width="10" height="10" fill="#10b981" rx="1" opacity="0.85" />
        <text x="90" y="9" fontSize="10" fill="#374151">pending / acquisitie</text>
        <rect x="190" width="10" height="10" fill="#f59e0b" rx="1" opacity="0.85" />
        <text x="204" y="9" fontSize="10" fill="#374151">projectie basis</text>
        <line x1="280" x2="300" y1="5" y2="5" stroke="#dc2626" strokeWidth="1.5" strokeDasharray="3,2" />
        <text x="304" y="9" fontSize="10" fill="#374151">€1M doel</text>
      </g>
    </svg>
  );
}

function AccountTrendBlock({
  title, subtitle, trend, loading,
  barColor = "#3b82f6", projColor = "#f59e0b",
}: {
  title: string;
  subtitle: string;
  trend: HelpdeskTrend | undefined;
  loading: boolean;
  barColor?: string;
  projColor?: string;
}) {
  const all = trend ? [...trend.months, ...trend.projection] : [];
  const max = all.length ? Math.max(...all.map(m => m.revenue), 1) : 1;
  return (
    <section className="rounded-lg bg-white ring-1 ring-slate-200 overflow-hidden">
      <div className="px-4 py-2.5 border-b border-slate-200">
        <h2 className="text-sm font-medium">{title}</h2>
        <div className="text-[11px] text-slate-500 mt-0.5">{subtitle}</div>
      </div>
      {loading && <div className="p-4 text-xs text-slate-500">Laden…</div>}
      {trend && (
        <div className="p-3 space-y-3">
          {/* Compacte KPI-strip */}
          <div className="grid grid-cols-4 gap-2 text-xs">
            <KPIMini label="Gem/mnd" value={fmtEUR(trend.average)} />
            <KPIMini label="Trend/mnd"
              value={(trend.growth_per_month >= 0 ? "+" : "") + fmtEUR(trend.growth_per_month)}
              tone={trend.growth_per_month >= 0 ? "emerald" : "rose"} />
            <KPIMini label="Totaal 12m" value={fmtEUR(trend.total_last_12)} />
            <KPIMini label="Projectie 12m" value={fmtEUR(trend.total_projected_next_12)}
              tone={trend.total_projected_next_12 > trend.total_last_12 ? "emerald" : "slate"} />
          </div>

          {/* 2-koloms: chart links, tabel rechts */}
          <div className="grid grid-cols-[1.6fr_1fr] gap-3">
            <div className="rounded-md bg-slate-50 p-2">
              <HelpdeskChart months={trend.months} projection={trend.projection} max={max}
                barColor={barColor} projColor={projColor} />
            </div>
            <div className="overflow-y-auto max-h-[260px] rounded-md ring-1 ring-slate-100">
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-slate-50">
                  <tr className="text-[10px] uppercase tracking-wider text-slate-500">
                    <th className="text-left px-2 py-1">Mnd</th>
                    <th className="text-right px-2 py-1">Werk.</th>
                    <th className="text-right px-2 py-1">Proj.</th>
                  </tr>
                </thead>
                <tbody>
                  {trend.months.map(m => (
                    <tr key={m.label} className="border-t border-slate-100">
                      <td className="px-2 py-0.5 font-mono">{m.label.slice(2)}</td>
                      <td className="px-2 py-0.5 text-right tabular-nums">{fmtEURcompact(m.revenue)}</td>
                      <td className="px-2 py-0.5 text-right text-slate-300">—</td>
                    </tr>
                  ))}
                  {trend.projection.map(m => (
                    <tr key={m.label} className="border-t border-slate-100 bg-amber-50/40">
                      <td className="px-2 py-0.5 font-mono">{m.label.slice(2)}</td>
                      <td className="px-2 py-0.5 text-right text-slate-300">—</td>
                      <td className="px-2 py-0.5 text-right tabular-nums text-amber-700">{fmtEURcompact(m.revenue)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

function KPIMini({ label, value, tone = "slate" }: { label: string; value: string; tone?: "slate" | "emerald" | "rose" }) {
  const c = tone === "emerald" ? "text-emerald-700" : tone === "rose" ? "text-rose-700" : "text-slate-900";
  return (
    <div className="rounded-md bg-slate-50 px-2 py-1.5">
      <div className="text-[9px] uppercase tracking-wider text-slate-500 font-semibold">{label}</div>
      <div className={`text-sm font-medium tabular-nums ${c}`}>{value}</div>
    </div>
  );
}

function fmtEURcompact(v: number): string {
  if (Math.abs(v) >= 1000) return `€${(v / 1000).toFixed(1)}k`;
  return `€${Math.round(v)}`;
}

function HelpdeskChart({ months, projection, max, barColor = "#3b82f6", projColor = "#f59e0b" }: { months: HelpdeskMonth[]; projection: HelpdeskMonth[]; max: number; barColor?: string; projColor?: string }) {
  const all = [...months, ...projection];
  const W = 720, H = 180, PADL = 44, PADR = 8, PADT = 22, PADB = 20;
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
              fill={barColor} rx="1" />
          </g>
        );
      })}
      {/* projectie (amber) */}
      {projection.map((m, i) => {
        const p = xy(months.length + i, m.revenue);
        return (
          <g key={m.label}>
            <rect x={p.x - xStep / 3} y={p.y} width={xStep * 0.66} height={PADT + innerH - p.y}
              fill={projColor} rx="1" opacity="0.85" />
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
        <rect width="10" height="10" fill={barColor} rx="1" />
        <text x="14" y="9" fontSize="10" fill="#374151">werkelijk</text>
        <rect x="80" width="10" height="10" fill={projColor} rx="1" opacity="0.85" />
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
