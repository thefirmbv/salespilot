import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";

type Campaign = {
  id: string;
  halopsa_id: number;
  name: string;
  subject: string | null;
  from_name: string | null;
  from_email: string | null;
  status: "draft" | "scheduled" | "sending" | "sent" | "paused" | "cancelled";
  status_label_halopsa: string | null;
  sent_at: string | null;
  scheduled_at: string | null;
  recipients_total: number;
  sent_count: number;
  delivered_count: number;
  opened_count: number;
  clicked_count: number;
  bounced_count: number;
  unsubscribed_count: number;
  complained_count: number;
  open_rate: number;
  click_rate: number;
  bounce_rate: number;
  synced_at: string;
};

type Summary = {
  total_campaigns: number;
  campaigns_last_30d: number;
  recipients_total_30d: number;
  delivered_30d: number;
  opened_30d: number;
  clicked_30d: number;
  bounced_30d: number;
  avg_open_rate_30d: number;
  avg_click_rate_30d: number;
  avg_bounce_rate_30d: number;
};

type SyncResult = {
  ok: boolean;
  detail: string;
  fetched: number;
  created: number;
  updated: number;
  recipients_synced: number;
};

const STATUS_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  draft:     { bg: "#F1F5F9", text: "#475569", label: "Concept"    },
  scheduled: { bg: "#FAEEDA", text: "#633806", label: "Ingepland"  },
  sending:   { bg: "#E6F1FB", text: "#0C447C", label: "Wordt verzonden" },
  sent:      { bg: "#E1F5EE", text: "#085041", label: "Verzonden"  },
  paused:    { bg: "#FAEEDA", text: "#633806", label: "Gepauzeerd" },
  cancelled: { bg: "#FCEBEB", text: "#791F1F", label: "Geannuleerd" },
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

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("nl-NL", {
    day: "numeric", month: "short", year: "numeric",
  });
}

function ProgressBar({ value, max, tone = "default" }: { value: number; max: number; tone?: "default" | "amber" | "red" | "emerald" }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  const color = {
    default: "#128ece",
    amber: "#BA7517",
    red: "#A32D2D",
    emerald: "#085041",
  }[tone];
  return (
    <div className="relative h-1.5 w-full rounded-full bg-slate-100">
      <div
        className="absolute left-0 top-0 h-full rounded-full"
        style={{ width: `${pct}%`, backgroundColor: color }}
      />
    </div>
  );
}

const BUCKETS = [
  { id: "",          label: "Alle"        },
  { id: "sent",      label: "Verzonden"   },
  { id: "scheduled", label: "Ingepland"   },
  { id: "draft",     label: "Concept"     },
];

export function MailCampaigns() {
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const bucket = params.get("status") ?? "";
  const [searchTerm, setSearchTerm] = useState("");

  const listQ = useQuery<Campaign[]>({
    queryKey: ["/mail-campaigns", bucket],
    queryFn: () =>
      api<Campaign[]>(
        bucket ? `/mail-campaigns?status=${bucket}&limit=300` : "/mail-campaigns?limit=300",
      ),
  });

  const summaryQ = useQuery<Summary>({
    queryKey: ["/mail-campaigns/summary"],
    queryFn: () => api<Summary>("/mail-campaigns/summary"),
  });

  const syncMut = useMutation({
    mutationFn: () => api<SyncResult>("/mail-campaigns/sync", { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["/mail-campaigns"] });
      qc.invalidateQueries({ queryKey: ["/mail-campaigns/summary"] });
    },
  });

  const summary = summaryQ.data;
  const items = (listQ.data ?? []).filter((c) => {
    if (!searchTerm) return true;
    const t = searchTerm.toLowerCase();
    return (
      c.name.toLowerCase().includes(t) ||
      (c.subject ?? "").toLowerCase().includes(t)
    );
  });

  const all = listQ.data ?? [];
  const counts = {
    "":          all.length,
    sent:        all.filter((c) => c.status === "sent").length,
    scheduled:   all.filter((c) => c.status === "scheduled").length,
    draft:       all.filter((c) => c.status === "draft").length,
  };

  const noCampaigns = !listQ.isLoading && all.length === 0;

  return (
    <div>
      <div className="overflow-hidden rounded-lg bg-white ring-1 ring-slate-200">
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
          <div>
            <h1 className="text-lg font-medium">Mail Campaigns</h1>
            <div className="mt-0.5 text-xs text-slate-500">
              Nieuwsbrieven en mailings vanuit HaloPSA
              {summary && all.length > 0 && (
                <> · {summary.total_campaigns} campagnes</>
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
              syncMut.data.ok ? "bg-emerald-50 text-emerald-800" : "bg-amber-50 text-amber-900"
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

        {summary && summary.total_campaigns > 0 && (
          <div className="grid grid-cols-2 gap-3 border-b border-slate-200 bg-slate-50 p-4 md:grid-cols-4">
            <KPI
              label="Verzonden (30d)"
              value={String(summary.recipients_total_30d.toLocaleString("nl-NL"))}
              sub={`${summary.campaigns_last_30d} campagnes`}
            />
            <KPI
              label="Open rate"
              value={`${summary.avg_open_rate_30d}%`}
              sub={`${summary.opened_30d.toLocaleString("nl-NL")} opens`}
              tone="emerald"
            />
            <KPI
              label="Click rate"
              value={`${summary.avg_click_rate_30d}%`}
              sub={`${summary.clicked_30d.toLocaleString("nl-NL")} clicks`}
            />
            <KPI
              label="Bounce rate"
              value={`${summary.avg_bounce_rate_30d}%`}
              sub={`${summary.bounced_30d.toLocaleString("nl-NL")} bounces`}
              tone={summary.avg_bounce_rate_30d > 5 ? "red" : "default"}
            />
          </div>
        )}

        {all.length > 0 && (
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
              placeholder="Zoek…"
              className="ml-auto min-w-[200px] rounded-md border border-slate-300 px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
            />
          </div>
        )}

        {listQ.isLoading && (
          <div className="px-4 py-6 text-sm text-slate-500">Bezig met laden…</div>
        )}

        {noCampaigns && (
          <div className="px-4 py-12 text-center">
            <div className="mx-auto max-w-md">
              <div className="text-4xl mb-3">📧</div>
              <h2 className="text-base font-medium text-slate-900">Nog geen campagnes</h2>
              <p className="mt-2 text-sm text-slate-600">
                Mail Campaigns worden in HaloPSA opgesteld. Druk op <b>Sync HaloPSA</b> hierboven
                om ze hier in te laden zodra ze beschikbaar zijn.
              </p>
              <div className="mt-4 rounded-md bg-amber-50 px-3 py-2 text-left text-xs text-amber-900">
                <strong>Tip:</strong> als de sync een &ldquo;permission ontbreekt&rdquo;
                melding geeft, voeg dan in HaloPSA bij{" "}
                <em>Configuration → Integrations → API → Applications</em>{" "}
                de permissie <b>Mail Campaign (Read)</b> toe aan de SalesPilot API-app.
              </div>
            </div>
          </div>
        )}

        {items.length > 0 && (
          <>
            <div className="grid grid-cols-[minmax(0,2fr)_90px_80px_160px_160px_90px] gap-3 border-b border-slate-200 px-4 py-2 text-[10px] uppercase tracking-wider text-slate-500">
              <div>Campagne</div>
              <div className="text-right">Ontvangers</div>
              <div className="text-right">Status</div>
              <div>Open rate</div>
              <div>Click rate</div>
              <div className="text-right">Verzonden</div>
            </div>

            {items.map((c) => (
              <Link
                key={c.id}
                to={`/mail-campaigns/${c.id}`}
                className="grid grid-cols-[minmax(0,2fr)_90px_80px_160px_160px_90px] items-center gap-3 border-b border-slate-100 px-4 py-2.5 hover:bg-slate-50"
              >
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium">{c.name}</div>
                  {c.subject && (
                    <div className="truncate text-[11px] text-slate-500">
                      {c.subject}
                    </div>
                  )}
                </div>
                <div className="text-right text-sm tabular-nums">
                  {c.recipients_total.toLocaleString("nl-NL")}
                </div>
                <div className="text-right">
                  <StatusBadge status={c.status} />
                </div>
                <div>
                  <div className="flex items-center justify-between text-[11px] tabular-nums">
                    <span className="text-slate-700">{c.open_rate}%</span>
                    <span className="text-slate-500">
                      {c.opened_count.toLocaleString("nl-NL")}
                    </span>
                  </div>
                  <ProgressBar value={c.opened_count} max={c.delivered_count || c.sent_count || c.recipients_total} tone="emerald" />
                </div>
                <div>
                  <div className="flex items-center justify-between text-[11px] tabular-nums">
                    <span className="text-slate-700">{c.click_rate}%</span>
                    <span className="text-slate-500">
                      {c.clicked_count.toLocaleString("nl-NL")}
                    </span>
                  </div>
                  <ProgressBar value={c.clicked_count} max={c.delivered_count || c.sent_count || c.recipients_total} />
                </div>
                <div className="text-right text-[11px] text-slate-500">
                  {fmtDate(c.sent_at)}
                </div>
              </Link>
            ))}
          </>
        )}
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
