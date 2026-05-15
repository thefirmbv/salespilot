import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

type Campaign = {
  id: string;
  halopsa_id: number;
  name: string;
  subject: string | null;
  from_name: string | null;
  from_email: string | null;
  status: string;
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
};

type Recipient = {
  id: string;
  campaign_id: string;
  company_id: string | null;
  company_name: string | null;
  contact_id: string | null;
  contact_name: string | null;
  email: string;
  name: string | null;
  status: "queued" | "sent" | "delivered" | "opened" | "clicked" | "bounced" | "complained" | "unsubscribed" | "failed";
  sent_at: string | null;
  delivered_at: string | null;
  opened_at: string | null;
  clicked_at: string | null;
  bounced_at: string | null;
  unsubscribed_at: string | null;
  open_count: number;
  click_count: number;
};

const STATUS_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  queued:       { bg: "#F1F5F9", text: "#475569", label: "Wachtrij"   },
  sent:         { bg: "#E6F1FB", text: "#0C447C", label: "Verzonden"  },
  delivered:    { bg: "#E1F5EE", text: "#085041", label: "Bezorgd"    },
  opened:       { bg: "#E1F5EE", text: "#085041", label: "Geopend"    },
  clicked:      { bg: "#EEEDFE", text: "#3C3489", label: "Geklikt"    },
  bounced:      { bg: "#FCEBEB", text: "#791F1F", label: "Bounced"    },
  complained:   { bg: "#FCEBEB", text: "#791F1F", label: "Spam"       },
  unsubscribed: { bg: "#FAEEDA", text: "#633806", label: "Uitgeschreven" },
  failed:       { bg: "#FCEBEB", text: "#791F1F", label: "Mislukt"    },
};

function StatusBadge({ status }: { status: string }) {
  const s = STATUS_STYLES[status] ?? STATUS_STYLES.queued;
  return (
    <span
      className="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium"
      style={{ backgroundColor: s.bg, color: s.text }}
    >
      {s.label}
    </span>
  );
}

function fmtDateTime(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("nl-NL", {
    day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
  });
}

const RECIPIENT_BUCKETS = [
  { id: "",                                    label: "Alle"          },
  { id: "clicked",                             label: "Geklikt"       },
  { id: "opened",                              label: "Geopend"       },
  { id: "delivered,opened,clicked",            label: "Bezorgd"       },
  { id: "bounced,complained,failed",           label: "Problemen"     },
  { id: "unsubscribed",                        label: "Uitgeschreven" },
];

export function MailCampaignDetail() {
  const { id = "" } = useParams();
  const [statusFilter, setStatusFilter] = useState("");

  const campQ = useQuery<Campaign>({
    queryKey: [`/mail-campaigns/${id}`],
    queryFn: () => api<Campaign>(`/mail-campaigns/${id}`),
  });

  const rcptsQ = useQuery<Recipient[]>({
    queryKey: [`/mail-campaigns/${id}/recipients`, statusFilter],
    queryFn: () =>
      api<Recipient[]>(
        statusFilter
          ? `/mail-campaigns/${id}/recipients?status=${statusFilter}&limit=2000`
          : `/mail-campaigns/${id}/recipients?limit=2000`,
      ),
  });

  if (campQ.isLoading || !campQ.data) {
    return <div className="text-sm text-slate-500">Bezig met laden…</div>;
  }
  const c = campQ.data;
  const recipients = rcptsQ.data ?? [];

  return (
    <div>
      <div className="overflow-hidden rounded-lg bg-white ring-1 ring-slate-200">
        <div className="border-b border-slate-200 px-4 py-3">
          <Link to="/mail-campaigns" className="text-xs text-slate-500 hover:text-slate-900">
            ← Alle campagnes
          </Link>
          <h1 className="mt-1 text-lg font-medium">{c.name}</h1>
          {c.subject && (
            <div className="mt-0.5 text-sm text-slate-600">{c.subject}</div>
          )}
          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
            <StatusBadge status={c.status} />
            {c.from_name && <span>Van: {c.from_name}{c.from_email && ` <${c.from_email}>`}</span>}
            {c.sent_at && <span>· Verzonden {fmtDateTime(c.sent_at)}</span>}
            {!c.sent_at && c.scheduled_at && <span>· Ingepland {fmtDateTime(c.scheduled_at)}</span>}
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3 border-b border-slate-200 bg-slate-50 p-4 md:grid-cols-5">
          <KPI label="Ontvangers" value={c.recipients_total.toLocaleString("nl-NL")} />
          <KPI label="Bezorgd" value={c.delivered_count.toLocaleString("nl-NL")} sub={c.recipients_total ? `${Math.round(c.delivered_count / c.recipients_total * 100)}%` : ""} />
          <KPI label="Geopend" value={`${c.open_rate}%`} sub={`${c.opened_count.toLocaleString("nl-NL")} opens`} tone="emerald" />
          <KPI label="Geklikt" value={`${c.click_rate}%`} sub={`${c.clicked_count.toLocaleString("nl-NL")} clicks`} />
          <KPI
            label="Bounce"
            value={`${c.bounce_rate}%`}
            sub={`${c.bounced_count.toLocaleString("nl-NL")} bounces`}
            tone={c.bounce_rate > 5 ? "red" : "default"}
          />
        </div>

        <div className="border-b border-slate-200 px-4 py-2">
          <div className="mb-1 text-[10px] uppercase tracking-wider text-slate-500">
            Ontvangers ({recipients.length})
          </div>
          <div className="flex flex-wrap items-center gap-1">
            {RECIPIENT_BUCKETS.map((b) => (
              <button
                key={b.id}
                onClick={() => setStatusFilter(b.id)}
                className={`rounded-md px-2.5 py-1 text-xs ${
                  statusFilter === b.id
                    ? "bg-brand-500 text-white"
                    : "text-slate-600 hover:bg-slate-100"
                }`}
              >
                {b.label}
              </button>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_100px_120px_120px] gap-3 border-b border-slate-200 px-4 py-2 text-[10px] uppercase tracking-wider text-slate-500">
          <div>Ontvanger</div>
          <div>Bedrijf</div>
          <div>Status</div>
          <div className="text-right">Geopend</div>
          <div className="text-right">Geklikt</div>
        </div>

        {rcptsQ.isLoading && (
          <div className="px-4 py-6 text-sm text-slate-500">Bezig met laden…</div>
        )}
        {!rcptsQ.isLoading && recipients.length === 0 && (
          <div className="px-4 py-10 text-center text-sm text-slate-500">
            Geen ontvangers in deze categorie.
          </div>
        )}

        {recipients.map((r) => (
          <div
            key={r.id}
            className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_100px_120px_120px] items-center gap-3 border-b border-slate-100 px-4 py-2"
          >
            <div className="min-w-0">
              <div className="truncate text-sm">
                {r.contact_name || r.name || r.email}
              </div>
              <div className="truncate text-[11px] text-slate-500 font-mono">
                {r.email}
              </div>
            </div>
            <div className="min-w-0">
              {r.company_id && r.company_name ? (
                <Link
                  to={`/companies/${r.company_id}`}
                  className="truncate text-sm text-slate-700 hover:text-brand-600 hover:underline"
                >
                  {r.company_name}
                </Link>
              ) : (
                <span className="text-sm text-slate-400">—</span>
              )}
            </div>
            <div>
              <StatusBadge status={r.status} />
            </div>
            <div className="text-right text-xs tabular-nums">
              {r.opened_at ? (
                <>
                  <div>{fmtDateTime(r.opened_at)}</div>
                  {r.open_count > 1 && (
                    <div className="text-[10px] text-slate-500">{r.open_count}×</div>
                  )}
                </>
              ) : (
                <span className="text-slate-400">—</span>
              )}
            </div>
            <div className="text-right text-xs tabular-nums">
              {r.clicked_at ? (
                <>
                  <div>{fmtDateTime(r.clicked_at)}</div>
                  {r.click_count > 1 && (
                    <div className="text-[10px] text-slate-500">{r.click_count}×</div>
                  )}
                </>
              ) : (
                <span className="text-slate-400">—</span>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function KPI({
  label, value, sub, tone = "default",
}: { label: string; value: string; sub?: string; tone?: "default" | "amber" | "red" | "emerald" }) {
  const toneCls = {
    default: "text-slate-900",
    amber: "text-amber-700",
    red: "text-red-700",
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
