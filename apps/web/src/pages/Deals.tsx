import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

type Deal = {
  id: string;
  name: string;
  amount: string | null;
  currency: string;
  status: "open" | "won" | "lost";
  pipeline_id: string;
  stage_id: string;
  stage_name: string | null;
  company_id: string | null;
  company_name: string | null;
  primary_contact_id: string | null;
  primary_contact_name: string | null;
  primary_contact_email: string | null;
  primary_contact_phone: string | null;
  expected_close_date: string | null;
  closed_at: string | null;
  quotation_count: number;
  quotation_total: string | null;
  last_quotation_status: string | null;
  created_at: string;
  updated_at: string;
};

type Summary = {
  open_count: number;
  open_amount: string;
  won_count_30d: number;
  won_amount_30d: string;
  lost_count_30d: number;
  lost_amount_30d: string;
  win_rate_90d: number;
  stale_open_count: number;
  currency: string;
};

const STATUS_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  open: { bg: "#E6F1FB", text: "#0C447C", label: "Open" },
  won:  { bg: "#E1F5EE", text: "#085041", label: "Gewonnen" },
  lost: { bg: "#FCEBEB", text: "#791F1F", label: "Verloren" },
};

const QUOTE_STATUS_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  draft:    { bg: "#F1F5F9", text: "#475569", label: "concept" },
  sent:     { bg: "#E6F1FB", text: "#0C447C", label: "verzonden" },
  accepted: { bg: "#E1F5EE", text: "#085041", label: "geaccepteerd" },
  rejected: { bg: "#FCEBEB", text: "#791F1F", label: "afgewezen" },
  expired:  { bg: "#FAEEDA", text: "#633806", label: "verlopen" },
};

function StatusBadge({ status }: { status: string }) {
  const s = STATUS_STYLES[status] ?? STATUS_STYLES.open;
  return (
    <span
      className="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium"
      style={{ backgroundColor: s.bg, color: s.text }}
    >
      {s.label}
    </span>
  );
}

function QuoteStatusBadge({ status }: { status: string }) {
  const s = QUOTE_STATUS_STYLES[status] ?? QUOTE_STATUS_STYLES.draft;
  return (
    <span
      className="inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-medium"
      style={{ backgroundColor: s.bg, color: s.text }}
    >
      {s.label}
    </span>
  );
}

function fmtEUR(v: string | null): string {
  if (v === null || v === undefined || v === "") return "—";
  const n = Number(v);
  if (!Number.isFinite(n) || n === 0) return "—";
  return new Intl.NumberFormat("nl-NL", {
    style: "currency",
    currency: "EUR",
    maximumFractionDigits: 0,
  }).format(n);
}

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("nl-NL", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

function PhoneLink({ phone }: { phone: string | null }) {
  if (!phone) return <span className="text-slate-400">—</span>;
  // Render as <span> with onClick handler instead of <a> because this
  // component is rendered inside a <Link> (router <a>). Nested <a> tags
  // are invalid HTML and many browsers drop the outer link entirely.
  return (
    <span
      role="button"
      tabIndex={0}
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        window.location.href = `tel:${phone}`;
      }}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          e.stopPropagation();
          window.location.href = `tel:${phone}`;
        }
      }}
      className="font-mono text-[11px] text-slate-700 hover:text-brand-600 hover:underline cursor-pointer"
    >
      {phone}
    </span>
  );
}

const BUCKETS = [
  { id: "",     label: "Alle"      },
  { id: "open", label: "Open"      },
  { id: "won",  label: "Gewonnen"  },
  { id: "lost", label: "Verloren"  },
];

export function Deals() {
  const [params, setParams] = useSearchParams();
  const bucket = params.get("status") ?? "open";
  const [searchTerm, setSearchTerm] = useState("");

  const listQ = useQuery<Deal[]>({
    queryKey: ["/deals-enriched", bucket],
    queryFn: () =>
      api<Deal[]>(
        bucket ? `/deals-enriched?status=${bucket}&limit=500` : "/deals-enriched?limit=500",
      ),
  });

  const summaryQ = useQuery<Summary>({
    queryKey: ["/deals-enriched/summary"],
    queryFn: () => api<Summary>("/deals-enriched/summary"),
  });

  const summary = summaryQ.data;
  const items = (listQ.data ?? []).filter((d) => {
    if (!searchTerm) return true;
    const t = searchTerm.toLowerCase();
    return (
      d.name.toLowerCase().includes(t) ||
      (d.company_name ?? "").toLowerCase().includes(t) ||
      (d.primary_contact_name ?? "").toLowerCase().includes(t)
    );
  });

  const all = listQ.data ?? [];
  const counts = {
    "":   all.length,
    open: all.filter((d) => d.status === "open").length,
    won:  all.filter((d) => d.status === "won").length,
    lost: all.filter((d) => d.status === "lost").length,
  };

  return (
    <div>
      <div className="overflow-hidden rounded-lg bg-white ring-1 ring-slate-200">
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
          <div>
            <h1 className="text-lg font-medium">Deals</h1>
            <div className="mt-0.5 text-xs text-slate-500">
              {summary?.open_count} open · {fmtEUR(summary?.open_amount ?? null)} in pipeline
            </div>
          </div>
        </div>

        {summary && (
          <div className="grid grid-cols-2 gap-3 border-b border-slate-200 bg-slate-50 p-4 md:grid-cols-4">
            <KPI label="Open pipeline" value={fmtEUR(summary.open_amount)} sub={`${summary.open_count} deals`} />
            <KPI label="Gewonnen (30d)" value={fmtEUR(summary.won_amount_30d)} sub={`${summary.won_count_30d} deals`} tone="emerald" />
            <KPI label="Verloren (30d)" value={fmtEUR(summary.lost_amount_30d)} sub={`${summary.lost_count_30d} deals`} tone="red" />
            <KPI label={`Win rate 90d`} value={`${summary.win_rate_90d}%`} sub={summary.stale_open_count > 0 ? `${summary.stale_open_count} stilliggend` : "geen oude"} tone={summary.stale_open_count > 0 ? "amber" : "default"} />
          </div>
        )}

        <div className="flex flex-wrap items-center gap-1 border-b border-slate-200 px-4 py-2">
          {BUCKETS.map((b) => (
            <button
              key={b.id}
              onClick={() => {
                const next = new URLSearchParams(params);
                if (b.id) next.set("status", b.id);
                else next.delete("status");
                setParams(next, { replace: true });
              }}
              className={`rounded-md px-2.5 py-1 text-xs ${
                bucket === b.id
                  ? "bg-brand-500 text-white"
                  : "text-slate-600 hover:bg-slate-100"
              }`}
            >
              {b.label}{" "}
              <span className="opacity-70 tabular-nums">
                ({counts[b.id as keyof typeof counts] ?? 0})
              </span>
            </button>
          ))}
          <input
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            placeholder="Zoek op deal, bedrijf, contact…"
            className="ml-auto min-w-[200px] rounded-md border border-slate-300 px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
          />
        </div>

        <div className="grid grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)_minmax(0,1fr)_90px_100px_90px] gap-3 border-b border-slate-200 px-4 py-2 text-[10px] uppercase tracking-wider text-slate-500">
          <div>Deal</div>
          <div>Bedrijf</div>
          <div>Contact</div>
          <div>Status</div>
          <div className="text-right">Bedrag</div>
          <div className="text-right">Bijgewerkt</div>
        </div>

        {listQ.isLoading && (
          <div className="px-4 py-6 text-sm text-slate-500">Bezig met laden…</div>
        )}

        {!listQ.isLoading && items.length === 0 && (
          <div className="px-4 py-10 text-center text-sm text-slate-500">
            Geen deals in deze categorie.
          </div>
        )}

        {items.map((d) => (
          <Link
            key={d.id}
            to={`/deals/${d.id}`}
            className="grid grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)_minmax(0,1fr)_90px_100px_90px] items-center gap-3 border-b border-slate-100 px-4 py-2.5 hover:bg-slate-50"
          >
            <div className="min-w-0">
              <div className="truncate text-sm font-medium">{d.name}</div>
              <div className="flex items-center gap-1 text-[11px] text-slate-500">
                {d.stage_name && <span>{d.stage_name}</span>}
                {d.quotation_count > 0 && (
                  <>
                    <span>·</span>
                    <span>{d.quotation_count}× offerte</span>
                    {d.last_quotation_status && (
                      <QuoteStatusBadge status={d.last_quotation_status} />
                    )}
                  </>
                )}
              </div>
            </div>
            <div className="min-w-0">
              {d.company_name ? (
                <span className="truncate text-sm text-slate-700">
                  {d.company_name}
                </span>
              ) : (
                <span className="text-sm text-slate-400">—</span>
              )}
            </div>
            <div className="min-w-0">
              {d.primary_contact_name ? (
                <>
                  <div className="truncate text-sm text-slate-700">
                    {d.primary_contact_name}
                  </div>
                  <PhoneLink phone={d.primary_contact_phone} />
                </>
              ) : (
                <span className="text-sm text-slate-400">geen contact</span>
              )}
            </div>
            <div>
              <StatusBadge status={d.status} />
            </div>
            <div className="text-right text-sm tabular-nums">
              {fmtEUR(d.amount)}
            </div>
            <div className="text-right text-[11px] text-slate-500">
              {fmtDate(d.updated_at)}
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}

function KPI({
  label,
  value,
  sub,
  tone = "default",
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "default" | "amber" | "red" | "emerald";
}) {
  const toneCls = {
    default: "text-slate-900",
    amber: "text-amber-700",
    red: "text-red-700",
    emerald: "text-emerald-700",
  }[tone];
  return (
    <div className="rounded-md border border-slate-200 bg-white p-3">
      <div className="text-[10px] uppercase tracking-wider text-slate-500">
        {label}
      </div>
      <div className={`mt-1 text-xl font-medium tabular-nums ${toneCls}`}>
        {value}
      </div>
      {sub && <div className="text-[11px] text-slate-500">{sub}</div>}
    </div>
  );
}
