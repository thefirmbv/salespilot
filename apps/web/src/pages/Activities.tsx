import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

type Activity = {
  id: string;
  type: "note" | "call" | "email" | "meeting" | "task";
  target_type: "contact" | "company" | "deal";
  target_id: string;
  target_name: string | null;
  subject: string | null;
  body: string | null;
  due_at: string | null;
  completed_at: string | null;
  quotation_id: string | null;
  quotation_reference: string | null;
  quotation_amount: string | null;
  reminder_kind: string | null;
  is_overdue: boolean;
  created_at: string;
  updated_at: string;
};

type Summary = {
  overdue_count: number;
  today_count: number;
  this_week_count: number;
  completed_30d_count: number;
  open_total: number;
  open_followup_count: number;
};

const TYPE_ICONS: Record<string, { icon: string; bg: string; fg: string }> = {
  call:    { icon: "\ud83d\udcde", bg: "#FAEEDA", fg: "#854F0B" },
  email:   { icon: "\u2709",       bg: "#E6F1FB", fg: "#0C447C" },
  meeting: { icon: "\ud83d\udc65", bg: "#EEEDFE", fg: "#3C3489" },
  task:    { icon: "\u2713",       bg: "#E1F5EE", fg: "#085041" },
  note:    { icon: "\u00b6",       bg: "#F1F5F9", fg: "#475569" },
};

function TypeChip({ type }: { type: string }) {
  const s = TYPE_ICONS[type] ?? TYPE_ICONS.note;
  return (
    <span
      className="inline-flex h-7 w-7 items-center justify-center rounded-full text-sm"
      style={{ backgroundColor: s.bg, color: s.fg }}
      title={type}
    >
      {s.icon}
    </span>
  );
}

function fmtDate(iso: string | null): string {
  if (!iso) return "\u2014";
  const d = new Date(iso);
  return d.toLocaleDateString("nl-NL", {
    day: "numeric",
    month: "short",
  });
}

function fmtTime(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleTimeString("nl-NL", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function relativeDate(iso: string | null): string {
  if (!iso) return "\u2014";
  const d = new Date(iso);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const target = new Date(d);
  target.setHours(0, 0, 0, 0);
  const diffDays = Math.round((target.getTime() - today.getTime()) / 86400e3);
  if (diffDays === 0) return `Vandaag ${fmtTime(iso)}`;
  if (diffDays === 1) return `Morgen ${fmtTime(iso)}`;
  if (diffDays === -1) return `Gisteren`;
  if (diffDays < 0) return `${Math.abs(diffDays)}d geleden`;
  if (diffDays < 7) return `Over ${diffDays}d`;
  return fmtDate(iso);
}

function fmtEUR(v: string | null): string {
  if (v === null || v === undefined || v === "") return "";
  const n = Number(v);
  if (!Number.isFinite(n) || n === 0) return "";
  return new Intl.NumberFormat("nl-NL", {
    style: "currency",
    currency: "EUR",
    maximumFractionDigits: 0,
  }).format(n);
}

const BUCKETS = [
  { id: "",         label: "Alle"        },
  { id: "overdue",  label: "Achterstand" },
  { id: "today",    label: "Vandaag"     },
  { id: "week",     label: "Deze week"   },
  { id: "followup", label: "Nabel-lijst" },
  { id: "done",     label: "Afgerond"    },
];

/** Maps a bucket id to the right counter from the summary endpoint. Returns
 * null when the bucket has no direct counter — that's fine, the badge just
 * doesn't render then. */
function bucketCount(id: string, s: Summary | undefined): number | null {
  if (!s) return null;
  switch (id) {
    case "":         return s.open_total;
    case "overdue":  return s.overdue_count;
    case "today":    return s.today_count;
    case "week":     return s.this_week_count;
    case "followup": return s.open_followup_count;
    case "done":     return s.completed_30d_count;
    default:         return null;
  }
}

export function Activities() {
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const bucket = params.get("bucket") ?? "overdue";
  const [searchTerm, setSearchTerm] = useState("");

  const listQ = useQuery<Activity[]>({
    queryKey: ["/activities-enriched", bucket],
    queryFn: () =>
      api<Activity[]>(
        bucket ? `/activities-enriched?bucket=${bucket}&limit=300` : "/activities-enriched?limit=300",
      ),
  });

  const summaryQ = useQuery<Summary>({
    queryKey: ["/activities-enriched/summary"],
    queryFn: () => api<Summary>("/activities-enriched/summary"),
  });

  const completeMut = useMutation({
    mutationFn: (id: string) =>
      api(`/activities/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ completed_at: new Date().toISOString() }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["/activities-enriched"] });
      qc.invalidateQueries({ queryKey: ["/activities-enriched/summary"] });
    },
  });

  const summary = summaryQ.data;
  const items = (listQ.data ?? []).filter((a) => {
    if (!searchTerm) return true;
    const t = searchTerm.toLowerCase();
    return (
      (a.subject ?? "").toLowerCase().includes(t) ||
      (a.target_name ?? "").toLowerCase().includes(t)
    );
  });

  return (
    <div>
      <div className="overflow-hidden rounded-lg bg-white ring-1 ring-slate-200">
        <div className="border-b border-slate-200 px-4 py-3">
          <h1 className="text-lg font-medium">Activities</h1>
          <div className="mt-0.5 text-xs text-slate-500">
            Taken, calls, follow-ups en notities
          </div>
        </div>

        {summary && (
          <div className="grid grid-cols-2 gap-3 border-b border-slate-200 bg-slate-50 p-4 md:grid-cols-4">
            <KPI
              label="Achterstand"
              value={String(summary.overdue_count)}
              sub="moet ingehaald"
              tone={summary.overdue_count > 0 ? "red" : "default"}
            />
            <KPI
              label="Vandaag"
              value={String(summary.today_count)}
              sub="te doen"
              tone={summary.today_count > 0 ? "amber" : "default"}
            />
            <KPI
              label="Deze week"
              value={String(summary.this_week_count)}
              sub="komende 7 dagen"
            />
            <KPI
              label="Open nabel-acties"
              value={String(summary.open_followup_count)}
              sub="vanuit offertes"
              tone={summary.open_followup_count > 0 ? "amber" : "default"}
            />
          </div>
        )}

        <div className="flex flex-wrap items-center gap-2 border-b border-slate-200 px-4 py-2">
          {BUCKETS.map((b) => {
            const count = bucketCount(b.id, summary);
            const isActive = bucket === b.id;
            return (
              <button
                key={b.id}
                onClick={() => {
                  const next = new URLSearchParams(params);
                  if (b.id) next.set("bucket", b.id);
                  else next.delete("bucket");
                  setParams(next, { replace: true });
                }}
                className={`inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm font-medium transition ${
                  isActive
                    ? "border-brand-500 bg-brand-500 text-white shadow-sm"
                    : "border-slate-200 bg-white text-slate-700 hover:border-slate-300 hover:bg-slate-50"
                }`}
              >
                <span>{b.label}</span>
                {count !== null && (
                  <span
                    className={`inline-flex min-w-[20px] items-center justify-center rounded-full px-1.5 py-0.5 text-[10px] font-semibold tabular-nums ${
                      isActive
                        ? "bg-white/25 text-white"
                        : count > 0
                          ? "bg-slate-100 text-slate-700"
                          : "bg-slate-50 text-slate-400"
                    }`}
                  >
                    {count}
                  </span>
                )}
              </button>
            );
          })}
          <input
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            placeholder="Zoek\u2026"
            className="ml-auto min-w-[200px] rounded-md border border-slate-300 px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
          />
        </div>

        {listQ.isLoading && (
          <div className="px-4 py-6 text-sm text-slate-500">Bezig met laden\u2026</div>
        )}

        {!listQ.isLoading && items.length === 0 && (
          <div className="px-4 py-10 text-center text-sm text-slate-500">
            Geen activiteiten in deze categorie.
          </div>
        )}

        {items.map((a) => {
          const targetLink = `/${a.target_type === "company" ? "companies" : a.target_type + "s"}/${a.target_id}`;
          return (
            <div
              key={a.id}
              className={`grid grid-cols-[44px_minmax(0,1.5fr)_minmax(0,1fr)_100px_110px_80px] items-center gap-3 border-b border-slate-100 px-4 py-2.5 ${
                a.is_overdue && a.completed_at === null ? "bg-red-50/30" : ""
              } ${a.completed_at ? "opacity-60" : ""}`}
            >
              <TypeChip type={a.type} />
              <div className="min-w-0">
                <Link
                  to={targetLink}
                  className="block truncate text-sm font-medium text-slate-900 hover:text-brand-600 hover:underline"
                >
                  {a.subject || `(geen titel)`}
                </Link>
                {a.body && (
                  <div className="truncate text-[11px] text-slate-500">
                    {a.body.split("\n")[0]}
                  </div>
                )}
              </div>
              <div className="min-w-0">
                {a.target_name ? (
                  <Link
                    to={targetLink}
                    className="truncate text-sm text-slate-700 hover:text-brand-600 hover:underline"
                  >
                    {a.target_name}
                  </Link>
                ) : (
                  <span className="text-sm text-slate-400">\u2014</span>
                )}
                {a.quotation_amount && (
                  <div className="text-[11px] text-slate-500">
                    Offerte {fmtEUR(a.quotation_amount)}
                  </div>
                )}
              </div>
              <div className="text-sm">
                {a.completed_at ? (
                  <span className="inline-flex items-center rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-800">
                    Afgerond
                  </span>
                ) : a.is_overdue ? (
                  <span className="inline-flex items-center rounded-full bg-red-50 px-2 py-0.5 text-[11px] font-medium text-red-800">
                    Te laat
                  </span>
                ) : (
                  <span className="inline-flex items-center rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-600">
                    Open
                  </span>
                )}
              </div>
              <div className={`text-right text-xs tabular-nums ${a.is_overdue && !a.completed_at ? "text-red-700 font-medium" : "text-slate-600"}`}>
                {relativeDate(a.due_at)}
              </div>
              <div className="text-right">
                {!a.completed_at && (
                  <button
                    onClick={() => completeMut.mutate(a.id)}
                    disabled={completeMut.isPending}
                    className="rounded-md border border-slate-300 px-2 py-0.5 text-[11px] hover:bg-slate-50 disabled:opacity-50"
                  >
                    Klaar
                  </button>
                )}
              </div>
            </div>
          );
        })}
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
