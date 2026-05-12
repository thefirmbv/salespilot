import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  BarChart,
  Bar,
  Line,
  LineChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { api } from "@/lib/api";
import { TypeBadge, dash, fmtDateTime, fmtMoney } from "@/lib/format";

type Stat = { count: number; amount: number };

type Dashboard = {
  generated_at: string;
  open_pipeline: Stat;
  won_this_month: Stat;
  lost_this_month: Stat;
  won_last_30d: Stat;
  win_rate_90d: { won: number; lost: number; rate: number | null; window_days: number };
  deals_per_stage: Array<{
    stage_id: string;
    name: string;
    position: number;
    is_won: boolean;
    is_lost: boolean;
    count: number;
    amount: number;
  }>;
  won_revenue_by_month: Array<{ month: string; count: number; amount: number }>;
  top_open_deals: Array<{
    id: string;
    name: string;
    amount: number | null;
    currency: string;
    expected_close_date: string | null;
  }>;
  recent_activities: Array<{
    id: string;
    type: string;
    target_type: string;
    target_id: string;
    subject: string | null;
    completed_at: string | null;
    created_at: string;
  }>;
  totals: { contacts: number; companies: number };
};

export function Dashboard() {
  const { data, isLoading, error } = useQuery<Dashboard>({
    queryKey: ["dashboard"],
    queryFn: () => api<Dashboard>("/dashboard"),
  });

  if (isLoading)
    return <div className="text-slate-500">Loading dashboard…</div>;
  if (error)
    return (
      <div className="text-red-600">
        {error instanceof Error ? error.message : "failed to load"}
      </div>
    );
  if (!data) return null;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Dashboard</h1>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          label="Open pipeline"
          primary={fmtMoney(data.open_pipeline.amount, "EUR")}
          secondary={`${data.open_pipeline.count} open deals`}
        />
        <KpiCard
          label="Won this month"
          primary={fmtMoney(data.won_this_month.amount, "EUR")}
          secondary={`${data.won_this_month.count} deals`}
          accent="text-green-700"
        />
        <KpiCard
          label="Lost this month"
          primary={fmtMoney(data.lost_this_month.amount, "EUR")}
          secondary={`${data.lost_this_month.count} deals`}
          accent="text-red-700"
        />
        <KpiCard
          label={`Win rate (last ${data.win_rate_90d.window_days}d)`}
          primary={
            data.win_rate_90d.rate === null
              ? "—"
              : `${Math.round(data.win_rate_90d.rate * 100)}%`
          }
          secondary={`${data.win_rate_90d.won} won · ${data.win_rate_90d.lost} lost`}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Deals per stage */}
        <Panel title="Open deals per stage">
          {data.deals_per_stage.length === 0 ? (
            <Empty>No stages configured.</Empty>
          ) : (
            <div className="px-4 pt-2 pb-4">
              <ResponsiveContainer width="100%" height={260}>
                <BarChart
                  data={data.deals_per_stage.map((s) => ({
                    name: s.name,
                    count: s.count,
                    amount: s.amount,
                  }))}
                  margin={{ top: 8, right: 8, left: 0, bottom: 8 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis dataKey="name" stroke="#64748b" fontSize={12} />
                  <YAxis stroke="#64748b" fontSize={12} allowDecimals={false} />
                  <Tooltip
                    formatter={(value, name) =>
                      name === "amount"
                        ? [fmtMoney(Number(value), "EUR"), "Value"]
                        : [value, "Count"]
                    }
                  />
                  <Bar dataKey="count" fill="#0f172a" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </Panel>

        {/* Won revenue by month */}
        <Panel title="Won revenue · last 6 months">
          <div className="px-4 pt-2 pb-4">
            <ResponsiveContainer width="100%" height={260}>
              <LineChart
                data={data.won_revenue_by_month}
                margin={{ top: 8, right: 16, left: 0, bottom: 8 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="month" stroke="#64748b" fontSize={12} />
                <YAxis stroke="#64748b" fontSize={12} />
                <Tooltip
                  formatter={(value) => fmtMoney(Number(value), "EUR")}
                />
                <Line
                  type="monotone"
                  dataKey="amount"
                  stroke="#059669"
                  strokeWidth={2}
                  dot={{ r: 3 }}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Panel>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Top open deals */}
        <Panel title="Top open deals">
          {data.top_open_deals.length === 0 ? (
            <Empty>No open deals.</Empty>
          ) : (
            <ul className="divide-y divide-slate-100">
              {data.top_open_deals.map((d) => (
                <li key={d.id}>
                  <Link
                    to={`/deals/${d.id}`}
                    className="flex items-center justify-between px-4 py-3 hover:bg-slate-50"
                  >
                    <span className="font-medium">{d.name}</span>
                    <span className="tabular-nums text-slate-700">
                      {fmtMoney(d.amount, d.currency)}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        {/* Recent activity */}
        <Panel title="Recent activity">
          {data.recent_activities.length === 0 ? (
            <Empty>No activity yet.</Empty>
          ) : (
            <ul className="divide-y divide-slate-100">
              {data.recent_activities.map((a) => (
                <li key={a.id}>
                  <Link
                    to={`/${a.target_type}s/${a.target_id}`}
                    className="block px-4 py-3 hover:bg-slate-50"
                  >
                    <div className="flex items-center gap-2">
                      <TypeBadge type={a.type} />
                      <span className="text-sm font-medium">
                        {dash(a.subject)}
                      </span>
                    </div>
                    <div className="mt-0.5 text-xs text-slate-500">
                      on {a.target_type} · {fmtDateTime(a.created_at)}
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>

      <div className="text-xs text-slate-400">
        {data.totals.contacts} contacts · {data.totals.companies} companies
      </div>
    </div>
  );
}

function KpiCard({
  label,
  primary,
  secondary,
  accent = "text-slate-900",
}: {
  label: string;
  primary: string;
  secondary?: string;
  accent?: string;
}) {
  return (
    <div className="rounded-lg ring-1 ring-slate-200 bg-white p-5">
      <div className="text-xs uppercase tracking-wider text-slate-500">
        {label}
      </div>
      <div className={`mt-2 text-2xl font-semibold tabular-nums ${accent}`}>
        {primary}
      </div>
      {secondary && (
        <div className="mt-1 text-xs text-slate-500">{secondary}</div>
      )}
    </div>
  );
}

function Panel({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-lg ring-1 ring-slate-200 bg-white">
      <div className="border-b border-slate-200 px-4 py-3">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-600">
          {title}
        </h2>
      </div>
      {children}
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div className="p-6 text-center text-sm text-slate-500">{children}</div>
  );
}
