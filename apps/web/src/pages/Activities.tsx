import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { CallButton } from "@/components/PhoneLink";

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
  // Nieuwe velden voor nabel-workflow
  assignee_id: string | null;
  assignee_name: string | null;
  author_id: string | null;
  author_name: string | null;
  priority: "low" | "normal" | "high" | "urgent";
  phone_override: string | null;
  outcome: "reached" | "voicemail" | "no_answer" | "not_relevant" | null;
  outcome_notes: string | null;
  next_followup_id: string | null;
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
  const [showCreate, setShowCreate] = useState(false);
  const [completingActivity, setCompletingActivity] = useState<Activity | null>(null);

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
    <>
    <div>
      <div className="overflow-hidden rounded-lg bg-white ring-1 ring-slate-200">
        <div className="overflow-x-auto md:overflow-visible">
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
          <div>
            <h1 className="text-lg font-medium">Activities</h1>
            <div className="mt-0.5 text-xs text-slate-500">
              Taken, calls, follow-ups en notities
            </div>
          </div>
          <button
            type="button"
            onClick={() => setShowCreate(true)}
            className="rounded-md bg-brand-500 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-600"
          >
            + Nieuwe activity
          </button>
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
            className="md:ml-auto w-full md:w-auto min-w-0 md:min-w-[200px] rounded-md border border-slate-300 px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
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
              className={`grid grid-cols-[44px_minmax(0,1.5fr)_minmax(0,1fr)_100px_110px_80px] min-w-[700px] md:min-w-0 items-center gap-3 border-b border-slate-100 px-4 py-2.5 ${
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
              <div className="flex justify-end gap-1.5">
                {!a.completed_at && a.type === "call" && a.phone_override && (
                  <CallButton phone={a.phone_override} size="sm" />
                )}
                {!a.completed_at && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      if (a.type === "call") {
                        setCompletingActivity(a);
                      } else {
                        completeMut.mutate(a.id);
                      }
                    }}
                    disabled={completeMut.isPending}
                    className="rounded-md border border-slate-300 px-2 py-1 text-[11px] hover:bg-slate-50 disabled:opacity-50"
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
    </div>
    {showCreate && (
      <ActivityCreateModal
        onClose={() => setShowCreate(false)}
        onCreated={() => {
          setShowCreate(false);
          qc.invalidateQueries({ queryKey: ["/activities-enriched"] });
          qc.invalidateQueries({ queryKey: ["/activities-enriched/summary"] });
        }}
      />
    )}
    {completingActivity && (
      <ActivityCompleteModal
        activity={completingActivity}
        onClose={() => setCompletingActivity(null)}
        onDone={() => {
          setCompletingActivity(null);
          qc.invalidateQueries({ queryKey: ["/activities-enriched"] });
          qc.invalidateQueries({ queryKey: ["/activities-enriched/summary"] });
        }}
      />
    )}
    </>
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

// ===== Activity creation modal =====

type UserOption = { id: string; email: string; full_name: string | null };
type CompanyOption = { id: string; name: string; phone: string | null };
type ContactOption = { id: string; first_name: string | null; last_name: string | null; company_id: string | null };
type DealOption = { id: string; name: string; company_id: string | null };
type QuotationOption = { id: string; reference: string; subject: string | null; company_id: string | null; status: string; amount_gross: number | null };

function ActivityCreateModal({
  onClose,
  onCreated,
  defaultTargetType,
  defaultTargetId,
  defaultQuotationId,
  defaultSubject,
}: {
  onClose: () => void;
  onCreated: () => void;
  defaultTargetType?: "company" | "contact" | "deal";
  defaultTargetId?: string;
  defaultQuotationId?: string;
  defaultSubject?: string;
}) {
  const [type, setType] = useState<"call" | "task" | "note" | "meeting" | "email">("call");
  const [targetType, setTargetType] = useState<"company" | "contact" | "deal">(defaultTargetType ?? "company");
  const [targetId, setTargetId] = useState<string>(defaultTargetId ?? "");
  const [subject, setSubject] = useState(defaultSubject ?? "");
  const [body, setBody] = useState("");
  const [dueLocal, setDueLocal] = useState(() => {
    const now = new Date();
    now.setHours(now.getHours() + 1, 0, 0, 0);
    const pad = (n: number) => String(n).padStart(2, "0");
    return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}T${pad(now.getHours())}:${pad(now.getMinutes())}`;
  });
  const [assigneeId, setAssigneeId] = useState<string>("");
  const [priority, setPriority] = useState<"low" | "normal" | "high" | "urgent">("normal");
  const [phoneOverride, setPhoneOverride] = useState("");
  const [quotationId, setQuotationId] = useState<string>(defaultQuotationId ?? "");
  const [error, setError] = useState<string | null>(null);

  // Lookup data
  const usersQ = useQuery<UserOption[]>({
    queryKey: ["/admin/users-min"],
    queryFn: async () => {
      const r = await api<{ id: string; email: string; full_name: string | null; is_active: boolean }[]>("/admin/users");
      return r.filter((u) => u.is_active).map((u) => ({ id: u.id, email: u.email, full_name: u.full_name }));
    },
  });
  const companiesQ = useQuery<{ items: CompanyOption[] }>({
    queryKey: ["/companies-min"],
    queryFn: () => api<{ items: CompanyOption[] }>("/companies?limit=500&sort_by=name"),
    enabled: targetType === "company",
  });
  const contactsQ = useQuery<{ items: ContactOption[] }>({
    queryKey: ["/contacts-min"],
    queryFn: () => api<{ items: ContactOption[] }>("/contacts?limit=500"),
    enabled: targetType === "contact",
  });
  const dealsQ = useQuery<{ items: DealOption[] }>({
    queryKey: ["/deals-min"],
    queryFn: () => api<{ items: DealOption[] }>("/deals?limit=500"),
    enabled: targetType === "deal",
  });

  // The company we're targeting either directly (target=company) or via contact/deal
  const targetCompanyId = (() => {
    if (targetType === "company") return targetId;
    if (targetType === "contact") {
      return contactsQ.data?.items.find((c) => c.id === targetId)?.company_id ?? "";
    }
    if (targetType === "deal") {
      return dealsQ.data?.items.find((d) => d.id === targetId)?.company_id ?? "";
    }
    return "";
  })();

  // Quotations filtered to this company
  const quotationsQ = useQuery<QuotationOption[]>({
    queryKey: ["/quotations-for-company", targetCompanyId],
    queryFn: () => api<QuotationOption[]>(`/quotations?limit=200`),
    enabled: !!targetCompanyId,
  });
  const companyQuotations = (quotationsQ.data ?? []).filter((q) => q.company_id === targetCompanyId);

  const createMut = useMutation({
    mutationFn: () => api<Activity>("/activities", {
      method: "POST",
      body: JSON.stringify({
        type,
        target_type: targetType,
        target_id: targetId,
        subject: subject || undefined,
        body: body || undefined,
        due_at: dueLocal ? new Date(dueLocal).toISOString() : undefined,
        assignee_id: assigneeId || undefined,
        priority,
        phone_override: phoneOverride || undefined,
        quotation_id: quotationId || undefined,
      }),
    }),
    onSuccess: () => onCreated(),
    onError: (e: unknown) => setError(e instanceof Error ? e.message : "Aanmaken mislukt"),
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4" onClick={onClose}>
      <div className="w-full max-w-xl rounded-lg bg-white shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
          <h2 className="text-base font-semibold">Nieuwe activity</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700">\u00d7</button>
        </div>
        <div className="space-y-3 p-4 max-h-[70vh] overflow-y-auto">
          {error && <div className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-800">{error}</div>}

          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <span className="block text-[11px] uppercase tracking-wider text-slate-500 mb-1">Type</span>
              <select value={type} onChange={(e) => setType(e.target.value as typeof type)}
                className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm">
                <option value="call">\ud83d\udcde Call</option>
                <option value="email">\u2709 Email</option>
                <option value="meeting">\ud83d\udc65 Meeting</option>
                <option value="task">\u2713 Task</option>
                <option value="note">\u00b6 Note</option>
              </select>
            </label>
            <label className="block">
              <span className="block text-[11px] uppercase tracking-wider text-slate-500 mb-1">Prioriteit</span>
              <select value={priority} onChange={(e) => setPriority(e.target.value as typeof priority)}
                className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm">
                <option value="low">Laag</option>
                <option value="normal">Normaal</option>
                <option value="high">Hoog</option>
                <option value="urgent">Urgent</option>
              </select>
            </label>
          </div>

          <div className="grid grid-cols-[120px_1fr] gap-3">
            <label className="block">
              <span className="block text-[11px] uppercase tracking-wider text-slate-500 mb-1">Gekoppeld aan</span>
              <select value={targetType} onChange={(e) => { setTargetType(e.target.value as typeof targetType); setTargetId(""); setQuotationId(""); }}
                className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm">
                <option value="company">Bedrijf</option>
                <option value="contact">Contact</option>
                <option value="deal">Deal</option>
              </select>
            </label>
            <label className="block min-w-0">
              <span className="block text-[11px] uppercase tracking-wider text-slate-500 mb-1">Selecteer</span>
              {targetType === "company" && (
                <select value={targetId} onChange={(e) => { setTargetId(e.target.value); setQuotationId(""); }}
                  className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm">
                  <option value="">\u2014 kies bedrijf \u2014</option>
                  {(companiesQ.data?.items ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              )}
              {targetType === "contact" && (
                <select value={targetId} onChange={(e) => { setTargetId(e.target.value); setQuotationId(""); }}
                  className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm">
                  <option value="">\u2014 kies contact \u2014</option>
                  {(contactsQ.data?.items ?? []).map((c) => (
                    <option key={c.id} value={c.id}>{[c.first_name, c.last_name].filter(Boolean).join(" ") || "(naamloos)"}</option>
                  ))}
                </select>
              )}
              {targetType === "deal" && (
                <select value={targetId} onChange={(e) => { setTargetId(e.target.value); setQuotationId(""); }}
                  className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm">
                  <option value="">\u2014 kies deal \u2014</option>
                  {(dealsQ.data?.items ?? []).map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
                </select>
              )}
            </label>
          </div>

          <label className="block">
            <span className="block text-[11px] uppercase tracking-wider text-slate-500 mb-1">
              Onderwerp {companyQuotations.length > 0 && <span className="text-slate-400 ml-1">\u2014 of koppel aan een offerte hieronder</span>}
            </span>
            <input value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="bv. Bellen over voorstel"
              className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm" />
          </label>

          {targetCompanyId && companyQuotations.length > 0 && (
            <label className="block">
              <span className="block text-[11px] uppercase tracking-wider text-slate-500 mb-1">Of: koppel aan offerte</span>
              <select value={quotationId} onChange={(e) => {
                setQuotationId(e.target.value);
                if (e.target.value) {
                  const q = companyQuotations.find((x) => x.id === e.target.value);
                  if (q && !subject) setSubject(`Nabellen offerte ${q.reference}${q.subject ? `: ${q.subject}` : ""}`);
                }
              }} className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm">
                <option value="">\u2014 geen koppeling \u2014</option>
                {companyQuotations.map((q) => (
                  <option key={q.id} value={q.id}>
                    {q.reference}{q.subject ? ` \u2014 ${q.subject.slice(0, 40)}` : ""}{q.status ? ` (${q.status})` : ""}
                  </option>
                ))}
              </select>
            </label>
          )}

          <label className="block">
            <span className="block text-[11px] uppercase tracking-wider text-slate-500 mb-1">Notitie / context</span>
            <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={3}
              className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm" />
          </label>

          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <span className="block text-[11px] uppercase tracking-wider text-slate-500 mb-1">Wanneer (datum + tijd)</span>
              <input type="datetime-local" value={dueLocal} onChange={(e) => setDueLocal(e.target.value)}
                className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm" />
            </label>
            <label className="block">
              <span className="block text-[11px] uppercase tracking-wider text-slate-500 mb-1">Toegewezen aan collega</span>
              <select value={assigneeId} onChange={(e) => setAssigneeId(e.target.value)}
                className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm">
                <option value="">\u2014 mezelf \u2014</option>
                {(usersQ.data ?? []).map((u) => (
                  <option key={u.id} value={u.id}>{u.full_name || u.email}</option>
                ))}
              </select>
            </label>
          </div>

          {type === "call" && (
            <label className="block">
              <span className="block text-[11px] uppercase tracking-wider text-slate-500 mb-1">
                Doorkies-nummer (override van bedrijfs-hoofdnummer)
              </span>
              <input value={phoneOverride} onChange={(e) => setPhoneOverride(e.target.value)} placeholder="bv. +31 30 1234567"
                className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm" />
            </label>
          )}
        </div>
        <div className="flex justify-end gap-2 border-t border-slate-200 px-4 py-3">
          <button type="button" onClick={onClose}
            className="rounded-md border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50">
            Annuleren
          </button>
          <button type="button" onClick={() => createMut.mutate()}
            disabled={!targetId || createMut.isPending}
            className="rounded-md bg-brand-500 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-600 disabled:opacity-50">
            {createMut.isPending ? "Bezig\u2026" : "Opslaan"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ===== Activity complete modal (with outcome + auto-followup) =====

function ActivityCompleteModal({
  activity, onClose, onDone,
}: { activity: Activity; onClose: () => void; onDone: () => void }) {
  const [outcome, setOutcome] = useState<"reached" | "voicemail" | "no_answer" | "not_relevant">("reached");
  const [outcomeNotes, setOutcomeNotes] = useState("");
  const [autoFollowup, setAutoFollowup] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const completeMut = useMutation({
    mutationFn: () => api(`/activities/${activity.id}`, {
      method: "PATCH",
      body: JSON.stringify({
        completed_at: new Date().toISOString(),
        outcome,
        outcome_notes: outcomeNotes || undefined,
        auto_followup_on_no_answer: autoFollowup,
      }),
    }),
    onSuccess: () => onDone(),
    onError: (e: unknown) => setError(e instanceof Error ? e.message : "Afronden mislukt"),
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4" onClick={onClose}>
      <div className="w-full max-w-md rounded-lg bg-white shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
          <h2 className="text-base font-semibold">Call afronden</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700">\u00d7</button>
        </div>
        <div className="space-y-3 p-4">
          <div className="text-sm text-slate-600">
            {activity.subject || "(geen onderwerp)"}{activity.target_name ? ` \u2014 ${activity.target_name}` : ""}
          </div>
          {error && <div className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-800">{error}</div>}

          <fieldset className="space-y-1">
            <legend className="text-[11px] uppercase tracking-wider text-slate-500 mb-1">Uitkomst</legend>
            {([
              ["reached", "\u2705 Bereikt"],
              ["voicemail", "\ud83d\udcde Voicemail ingesproken"],
              ["no_answer", "\u274c Niet bereikt"],
              ["not_relevant", "\ud83d\udeab Niet meer relevant"],
            ] as const).map(([v, label]) => (
              <label key={v} className="flex items-center gap-2 rounded-md border border-slate-200 px-3 py-2 hover:bg-slate-50 cursor-pointer">
                <input type="radio" name="outcome" value={v} checked={outcome === v}
                  onChange={() => setOutcome(v)} />
                <span className="text-sm">{label}</span>
              </label>
            ))}
          </fieldset>

          <label className="block">
            <span className="block text-[11px] uppercase tracking-wider text-slate-500 mb-1">Korte notitie</span>
            <textarea value={outcomeNotes} onChange={(e) => setOutcomeNotes(e.target.value)} rows={3}
              placeholder="Wat was de uitkomst van het gesprek?"
              className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm" />
          </label>

          {outcome === "no_answer" && (
            <label className="flex items-center gap-2 rounded-md bg-amber-50 px-3 py-2">
              <input type="checkbox" checked={autoFollowup} onChange={(e) => setAutoFollowup(e.target.checked)} />
              <span className="text-sm">Plan automatisch follow-up over 2 dagen, zelfde collega</span>
            </label>
          )}
        </div>
        <div className="flex justify-end gap-2 border-t border-slate-200 px-4 py-3">
          <button type="button" onClick={onClose}
            className="rounded-md border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50">
            Annuleren
          </button>
          <button type="button" onClick={() => completeMut.mutate()}
            disabled={completeMut.isPending}
            className="rounded-md bg-brand-500 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-600 disabled:opacity-50">
            {completeMut.isPending ? "Bezig\u2026" : "Opslaan"}
          </button>
        </div>
      </div>
    </div>
  );
}

// Export so other pages (e.g. CompanyDetail) can reuse the create modal
export { ActivityCreateModal };
