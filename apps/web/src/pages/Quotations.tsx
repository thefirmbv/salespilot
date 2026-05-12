import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";

type Quotation = {
  id: string;
  company_id: string;
  deal_id: string | null;
  halopsa_id: number;
  reference: string | null;
  subject: string | null;
  status: "draft" | "sent" | "accepted" | "rejected" | "expired";
  status_label_halopsa: string | null;
  amount_net: string | null;
  amount_gross: string | null;
  currency: string;
  sent_at: string | null;
  valid_until: string | null;
  accepted_at: string | null;
  rejected_at: string | null;
  synced_at: string;
  company_name: string | null;
  deal_name: string | null;
};

type Summary = {
  open_count: number;
  open_amount: string;
  expiring_soon_count: number;
  expired_count: number;
  accepted_count_30d: number;
  accepted_amount_30d: string;
  rejected_count_30d: number;
  hit_rate_90d: number;
  currency: string;
};

type SyncResult = {
  ok: boolean;
  detail: string;
  fetched?: number;
  created?: number;
  updated?: number;
  deals_created?: number;
  reminders_scheduled?: number;
};

const STATUS_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  draft:    { bg: "#F1F5F9", text: "#475569", label: "Concept"    },
  sent:     { bg: "#E6F1FB", text: "#0C447C", label: "Verzonden"  },
  accepted: { bg: "#E1F5EE", text: "#085041", label: "Geaccepteerd" },
  rejected: { bg: "#FCEBEB", text: "#791F1F", label: "Afgewezen"  },
  expired:  { bg: "#FAEEDA", text: "#633806", label: "Verlopen"   },
};

function StatusBadge({ status }: { status: string }) {
  const s = STATUS_STYLES[status] ?? STATUS_STYLES.draft;
  return (
    <span
      className="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium"
      style={{ backgroundColor: s.bg, color: s.text }}
    >
      {s.label}
    </span>
  );
}

function fmtEUR(v: string | null): string {
  if (v === null || v === undefined || v === "") return "—";
  const n = Number(v);
  if (!Number.isFinite(n)) return "—";
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

function daysUntil(iso: string | null): number | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Math.ceil((d.getTime() - Date.now()) / 86400e3);
}

function ExpiryHint({ q }: { q: Quotation }) {
  if (q.status !== "sent" || !q.valid_until) return null;
  const days = daysUntil(q.valid_until);
  if (days === null) return null;
  if (days < 0) {
    return (
      <span className="text-[10px] text-red-700 font-medium">
        {Math.abs(days)}d over datum
      </span>
    );
  }
  if (days <= 7) {
    return (
      <span className="text-[10px] text-amber-700 font-medium">
        nog {days}d
      </span>
    );
  }
  return (
    <span className="text-[10px] text-slate-500">nog {days}d</span>
  );
}

const BUCKETS = [
  { id: "",         label: "Alle"          },
  { id: "open",     label: "Open"          },
  { id: "expiring", label: "Bijna verlopen" },
  { id: "expired",  label: "Verlopen"      },
  { id: "accepted", label: "Geaccepteerd"  },
  { id: "rejected", label: "Afgewezen"     },
];

export function Quotations() {
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const bucket = params.get("bucket") ?? "";
  const [searchTerm, setSearchTerm] = useState("");

  const listQ = useQuery<Quotation[]>({
    queryKey: ["/quotations", bucket],
    queryFn: () =>
      api<Quotation[]>(
        bucket ? `/quotations?bucket=${bucket}&limit=500` : "/quotations?limit=500",
      ),
  });

  const summaryQ = useQuery<Summary>({
    queryKey: ["/quotations/summary"],
    queryFn: () => api<Summary>("/quotations/summary"),
  });

  const syncMut = useMutation({
    mutationFn: () =>
      api<SyncResult>("/quotations/sync", { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["/quotations"] });
      qc.invalidateQueries({ queryKey: ["/quotations/summary"] });
      qc.invalidateQueries({ queryKey: ["/activities"] });
    },
  });

  const summary = summaryQ.data;
  const items = (listQ.data ?? []).filter((q) => {
    if (!searchTerm) return true;
    const t = searchTerm.toLowerCase();
    return (
      (q.subject ?? "").toLowerCase().includes(t) ||
      (q.reference ?? "").toLowerCase().includes(t) ||
      (q.company_name ?? "").toLowerCase().includes(t)
    );
  });

  // counts per bucket for tab labels
  const all = listQ.data ?? [];
  const now = Date.now();
  const counts = {
    "":         all.length,
    open:       all.filter(q => q.status === "sent" && (!q.valid_until || new Date(q.valid_until).getTime() > now)).length,
    expiring:   all.filter(q => {
      if (q.status !== "sent" || !q.sent_at) return false;
      const sentTime = new Date(q.sent_at).getTime();
      return sentTime <= now - 14 * 86400e3 && sentTime >= now - 30 * 86400e3;
    }).length,
    expired:    all.filter(q => q.status === "expired" || (q.status === "sent" && q.valid_until && new Date(q.valid_until).getTime() <= now)).length,
    accepted:   all.filter(q => q.status === "accepted").length,
    rejected:   all.filter(q => q.status === "rejected").length,
  };

  return (
    <div>
      <div className="overflow-hidden rounded-lg bg-white ring-1 ring-slate-200">
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
          <div>
            <h1 className="text-lg font-medium">Offertes</h1>
            <div className="mt-0.5 text-xs text-slate-500">
              Gesynchroniseerd vanuit HaloPSA
              {summaryQ.data && (
                <> · {summary?.open_count} open · {fmtEUR(summary?.open_amount ?? null)} pipeline</>
              )}
            </div>
          </div>
          <button
            onClick={() => syncMut.mutate()}
            disabled={syncMut.isPending}
            className="inline-flex items-center gap-1.5 rounded-md border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50 disabled:opacity-50"
          >
            {syncMut.isPending ? "Bezig…" : "Sync HaloPSA"}
          </button>
        </div>

        {syncMut.isSuccess && syncMut.data && (
          <div
            className={`px-4 py-2 text-xs ${
              syncMut.data.ok ? "bg-emerald-50 text-emerald-800" : "bg-red-50 text-red-800"
            }`}
          >
            {syncMut.data.detail}
          </div>
        )}
        {syncMut.isError && (
          <div className="px-4 py-2 text-xs bg-red-50 text-red-800">
            {syncMut.error instanceof ApiError ? syncMut.error.detail : "Sync failed"}
          </div>
        )}

        {summary && (
          <div className="grid grid-cols-2 gap-3 border-b border-slate-200 bg-slate-50 p-4 md:grid-cols-4">
            <KPI label="Open" value={String(summary.open_count)} sub={fmtEUR(summary.open_amount)} />
            <KPI label="Bijna verlopen" value={String(summary.expiring_soon_count)} sub="14-30 dagen" tone={summary.expiring_soon_count > 0 ? "amber" : "default"} />
            <KPI label="Verlopen" value={String(summary.expired_count)} sub="nabellen" tone={summary.expired_count > 0 ? "red" : "default"} />
            <KPI label="Hit-rate (90d)" value={`${summary.hit_rate_90d}%`} sub={`${summary.accepted_count_30d} accepted / 30d`} tone="emerald" />
          </div>
        )}

        <div className="flex flex-wrap items-center gap-1 border-b border-slate-200 px-4 py-2">
          {BUCKETS.map((b) => (
            <button
              key={b.id}
              onClick={() => {
                const next = new URLSearchParams(params);
                if (b.id) next.set("bucket", b.id);
                else next.delete("bucket");
                setParams(next, { replace: true });
              }}
              className={`rounded-md px-2.5 py-1 text-xs ${
                bucket === b.id
                  ? "bg-brand-500 text-white"
                  : "text-slate-600 hover:bg-slate-100"
              }`}
            >
              {b.label}{" "}
              <span className="opacity-70 tabular-nums">({counts[b.id as keyof typeof counts] ?? 0})</span>
            </button>
          ))}
          <input
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            placeholder="Zoek op offerte, bedrijf…"
            className="ml-auto min-w-[200px] rounded-md border border-slate-300 px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
          />
        </div>

        <div className="grid grid-cols-[1fr_minmax(0,1fr)_90px_110px_110px_80px] gap-3 px-4 py-2 text-[10px] uppercase tracking-wider text-slate-500 border-b border-slate-200">
          <div>Offerte</div>
          <div>Bedrijf</div>
          <div>Status</div>
          <div className="text-right">Bedrag</div>
          <div className="text-right">Verzonden</div>
          <div className="text-right">Geldig</div>
        </div>

        {listQ.isLoading && (
          <div className="px-4 py-6 text-sm text-slate-500">Bezig met laden…</div>
        )}

        {!listQ.isLoading && items.length === 0 && (
          <div className="px-4 py-10 text-center text-sm text-slate-500">
            Geen offertes in deze categorie. Klik op{" "}
            <span className="font-medium">Sync HaloPSA</span> om de meest recente te halen.
          </div>
        )}

        {items.map((q) => (
          <Link
            key={q.id}
            to={q.deal_id ? `/deals/${q.deal_id}` : `/companies/${q.company_id}`}
            className="grid grid-cols-[1fr_minmax(0,1fr)_90px_110px_110px_80px] items-center gap-3 border-b border-slate-100 px-4 py-2.5 hover:bg-slate-50"
          >
            <div className="min-w-0">
              <div className="truncate text-sm font-medium">
                {q.subject || `Offerte #${q.halopsa_id}`}
              </div>
              <div className="text-[11px] text-slate-500 font-mono truncate">
                {q.reference ? `Ref ${q.reference}` : `HaloPSA #${q.halopsa_id}`}
              </div>
            </div>
            <div className="min-w-0">
              <div className="truncate text-sm">{q.company_name ?? "—"}</div>
              {q.deal_name && (
                <div className="truncate text-[11px] text-slate-500">{q.deal_name}</div>
              )}
            </div>
            <div>
              <StatusBadge status={q.status} />
            </div>
            <div className="text-right text-sm tabular-nums">
              {fmtEUR(q.amount_gross || q.amount_net)}
            </div>
            <div className="text-right text-xs text-slate-500">
              {fmtDate(q.sent_at)}
            </div>
            <div className="text-right">
              <ExpiryHint q={q} />
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
    amber:   "text-amber-700",
    red:     "text-red-700",
    emerald: "text-emerald-700",
  }[tone];
  return (
    <div className="rounded-md border border-slate-200 bg-white p-3">
      <div className="text-[10px] uppercase tracking-wider text-slate-500">{label}</div>
      <div className={`mt-1 text-xl font-medium tabular-nums ${toneCls}`}>{value}</div>
      {sub && <div className="text-[11px] text-slate-500">{sub}</div>}
    </div>
  );
}
