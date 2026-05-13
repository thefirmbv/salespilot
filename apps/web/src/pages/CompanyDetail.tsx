import { useState } from "react";
import { Link, useParams, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import { FormDialog, type FieldSpec, type FormValues } from "@/components/FormDialog";
import { DetailHeader, FieldList } from "@/components/DetailHeader";
import { ProspectPanel } from "@/components/ProspectPanel";
import { ActivityFeed } from "@/components/ActivityFeed";
import { ActivityCreateModal } from "./Activities";
import { dash, fmtDate, fmtDateTime, fmtMoney, SourceBadge, StatusBadge } from "@/lib/format";

type Company = {
  id: string;
  name: string;
  domain: string | null;
  industry: string | null;
  size: string | null;
  description: string | null;
  source: string;
  halopsa_id: number | null;
  halopsa_synced_at: string | null;
  employees: number | null;
  city: string | null;
  country: string | null;
  mail_platform: "m365" | "google" | "other" | "unknown";
  lead_score: number;
  last_visit_at: string | null;
  pageview_count_30d: number;
  created_at: string;
};
type Contact = {
  id: string;
  first_name: string | null;
  last_name: string | null;
  email: string | null;
  job_title: string | null;
};
type Deal = {
  id: string;
  name: string;
  amount: number | null;
  currency: string;
  status: "open" | "won" | "lost";
};
type InternalQuotation = {
  id: string;
  reference: string;
  subject: string | null;
  status: string;
  amount_gross: number | null;
  amount_net: number | null;
  sent_at: string | null;
  expires_at: string | null;
  accepted_at: string | null;
  company_id: string;
  deal_id: string | null;
};
type Page<T> = { items: T[]; total: number };

const editFields: FieldSpec[] = [
  { name: "name", label: "Company name", type: "text", required: true },
  { name: "domain", label: "Domain", type: "text" },
  { name: "industry", label: "Industry", type: "text" },
  {
    name: "size",
    label: "Size",
    type: "select",
    options: [
      { value: "1-10", label: "1-10" },
      { value: "11-50", label: "11-50" },
      { value: "51-200", label: "51-200" },
      { value: "201-1000", label: "201-1000" },
      { value: "1000+", label: "1000+" },
    ],
  },
  { name: "description", label: "Description", type: "textarea", rows: 3 },
];

export function CompanyDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [pushMsg, setPushMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [tab, setTab] = useState<"overview" | "communications">("overview");
  const [quotationForFollowup, setQuotationForFollowup] = useState<InternalQuotation | null>(null);

  const companyQ = useQuery<Company>({
    queryKey: ["/companies", id],
    queryFn: () => api<Company>(`/companies/${id}`),
    enabled: !!id,
  });

  const contactsQ = useQuery<Page<Contact>>({
    queryKey: ["/contacts", { company_id: id }],
    queryFn: () => api<Page<Contact>>(`/contacts?company_id=${id}&limit=200`),
    enabled: !!id,
  });

  const dealsQ = useQuery<Page<Deal>>({
    queryKey: ["/deals", { company_id: id }],
    queryFn: () => api<Page<Deal>>(`/deals?company_id=${id}&limit=200`),
    enabled: !!id,
  });

  // Internal (synced) quotations -- preferred source because they have
  // synced state in our DB and can be cross-linked. /quotations returns a
  // plain list, not a paginated envelope.
  const internalQuotationsQ = useQuery<InternalQuotation[]>({
    queryKey: ["/quotations", { company_id: id }],
    queryFn: () => api<InternalQuotation[]>(`/quotations?company_id=${id}&limit=100`),
    enabled: !!id,
  });

  const updateMut = useMutation({
    mutationFn: (body: unknown) =>
      api<Company>(`/companies/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["/companies", id] });
      qc.invalidateQueries({ queryKey: ["/companies"] });
    },
  });

  const deleteMut = useMutation({
    mutationFn: () => api<void>(`/companies/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["/companies"] }),
  });

  const pushMut = useMutation({
    mutationFn: () =>
      api<{ halopsa_id: number; source: string }>(
        `/companies/${id}/push-to-halopsa`,
        { method: "POST" },
      ),
    onSuccess: (r) => {
      setPushMsg({ ok: true, text: `Pushed to HaloPSA (id ${r.halopsa_id}).` });
      qc.invalidateQueries({ queryKey: ["/companies", id] });
    },
    onError: (e) =>
      setPushMsg({
        ok: false,
        text: e instanceof ApiError ? e.detail : "push failed",
      }),
  });

  if (!id) return <div>Missing id</div>;
  if (companyQ.isLoading) return <div className="text-slate-500">Loading…</div>;
  if (!companyQ.data) return null;

  const c = companyQ.data;
  const readOnly = c.source === "halopsa";

  return (
    <div className="space-y-6">
      <DetailHeader
        backTo={c.source === "halopsa" ? "/customers" : "/prospects"}
        backLabel={c.source === "halopsa" ? "All customers" : "All prospects"}
        title={c.name}
        subtitle={c.industry ?? undefined}
        onEdit={() => setEditing(true)}
        onDelete={async () => {
          await deleteMut.mutateAsync();
          navigate(c.source === "halopsa" ? "/customers" : "/prospects");
        }}
      />

      {(c.source === "salespilot" || c.source === "halopsa_pushed") && (
        <ProspectPanel company={c} />
      )}

      <div className="rounded-lg ring-1 ring-slate-200 bg-white p-5">
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <SourceBadge source={c.source} />
          {c.halopsa_id && (
            <span className="text-xs text-slate-500">
              HaloPSA client id: <span className="font-mono">{c.halopsa_id}</span>
              {c.halopsa_synced_at && (
                <> · synced {fmtDateTime(c.halopsa_synced_at)}</>
              )}
            </span>
          )}
          {c.source === "salespilot" && (
            <button
              onClick={() => {
                setPushMsg(null);
                if (
                  confirm(
                    `Push "${c.name}" to HaloPSA as a new client? The main site will be named "HaloPSA".`,
                  )
                ) {
                  pushMut.mutate();
                }
              }}
              disabled={pushMut.isPending}
              className="ml-auto rounded-md bg-indigo-600 px-3 py-1 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
            >
              {pushMut.isPending ? "Pushing…" : "Push to HaloPSA"}
            </button>
          )}
        </div>

        {pushMsg && (
          <div
            className={`mb-3 text-sm ${pushMsg.ok ? "text-green-700" : "text-red-600"}`}
          >
            {pushMsg.text}
          </div>
        )}

        {readOnly && (
          <div className="mb-3 text-xs text-slate-500">
            This client is synced from HaloPSA and is read-only here. Edit it in HaloPSA.
          </div>
        )}

        <FieldList
          fields={[
            ["Domain", dash(c.domain)],
            ["Industry", dash(c.industry)],
            ["Size", dash(c.size)],
            ["Description", c.description ? c.description : "—"],
          ]}
        />
      </div>

      {/* Tab bar */}
      <div className="border-b border-slate-200">
        <div className="-mb-px flex gap-1">
          <button
            type="button"
            onClick={() => setTab("overview")}
            className={`px-3 py-2 text-sm font-medium border-b-2 transition-colors ${
              tab === "overview"
                ? "border-brand-500 text-slate-900"
                : "border-transparent text-slate-500 hover:text-slate-800"
            }`}
          >
            Overview
          </button>
          <button
            type="button"
            onClick={() => setTab("communications")}
            className={`px-3 py-2 text-sm font-medium border-b-2 transition-colors ${
              tab === "communications"
                ? "border-brand-500 text-slate-900"
                : "border-transparent text-slate-500 hover:text-slate-800"
            }`}
          >
            Communicatie
          </button>
        </div>
      </div>

      {tab === "communications" && <CommunicationsPanel companyId={c.id} />}
      {tab === "overview" && (
      <div className="grid gap-6 lg:grid-cols-[2fr_1fr]">
        <div className="space-y-6">
          <ActivityFeed targetType="company" targetId={c.id} />

          <div className="rounded-lg ring-1 ring-slate-200 bg-white">
            <div className="border-b border-slate-200 px-4 py-3">
              <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-600">
                Deals
              </h2>
            </div>
            {dealsQ.data && dealsQ.data.items.length === 0 && (
              <div className="p-6 text-center text-sm text-slate-500">
                No deals yet.
              </div>
            )}
            {dealsQ.data && dealsQ.data.items.length > 0 && (
              <ul className="divide-y divide-slate-100">
                {dealsQ.data.items.map((d) => (
                  <li key={d.id}>
                    <Link
                      to={`/deals/${d.id}`}
                      className="flex items-center justify-between px-4 py-3 hover:bg-slate-50"
                    >
                      <span className="font-medium">{d.name}</span>
                      <span className="flex items-center gap-2 text-sm">
                        <span className="tabular-nums text-slate-700">
                          {fmtMoney(d.amount, d.currency)}
                        </span>
                        <StatusBadge status={d.status} />
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="rounded-lg ring-1 ring-slate-200 bg-white">
            <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
              <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-600">
                Offertes
              </h2>
              <Link to={`/quotations?company_id=${c.id}`}
                className="text-xs text-brand-600 hover:underline">Alle offertes ↗</Link>
            </div>
            {internalQuotationsQ.isLoading && (
              <div className="p-4 text-sm text-slate-500">Bezig met laden…</div>
            )}
            {internalQuotationsQ.data && internalQuotationsQ.data.length === 0 && (
              <div className="p-6 text-center text-sm text-slate-500">
                Nog geen offertes voor deze klant.
              </div>
            )}
            {internalQuotationsQ.data && internalQuotationsQ.data.length > 0 && (
              <ul className="divide-y divide-slate-100">
                {internalQuotationsQ.data.map((q) => {
                  const tone: "emerald" | "red" | "slate" | "amber" =
                    q.status === "accepted" ? "emerald" :
                    q.status === "rejected" ? "red" :
                    q.status === "expired"  ? "slate"  :
                    "amber";
                  const toneCls = {
                    emerald: "bg-emerald-50 text-emerald-800",
                    red:     "bg-red-50 text-red-800",
                    amber:   "bg-amber-50 text-amber-800",
                    slate:   "bg-slate-100 text-slate-600",
                  }[tone];
                  return (
                    <li key={q.id} className="flex items-center gap-3 px-4 py-3 hover:bg-slate-50">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-baseline gap-2">
                          <span className="font-medium">{q.reference}</span>
                          <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${toneCls}`}>{q.status}</span>
                        </div>
                        {q.subject && <div className="text-xs text-slate-500 truncate">{q.subject}</div>}
                        <div className="text-[11px] text-slate-500 mt-0.5">
                          {q.sent_at && <>verstuurd {fmtDate(q.sent_at)}</>}
                          {q.expires_at && <> · verloopt {fmtDate(q.expires_at)}</>}
                        </div>
                      </div>
                      <div className="text-right">
                        {q.amount_gross != null && (
                          <div className="font-medium tabular-nums">{fmtMoney(q.amount_gross, "EUR")}</div>
                        )}
                        <button
                          type="button"
                          onClick={() => setQuotationForFollowup(q)}
                          className="mt-1 text-xs text-brand-600 hover:underline"
                          title="Maak een bel-/follow-up taak voor deze offerte"
                        >
                          + Nabel-actie
                        </button>
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </div>

        <div className="rounded-lg ring-1 ring-slate-200 bg-white">
          <div className="border-b border-slate-200 px-4 py-3">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-600">
              People
            </h2>
          </div>
          {contactsQ.data && contactsQ.data.items.length === 0 && (
            <div className="p-6 text-center text-sm text-slate-500">
              No contacts at this company.
            </div>
          )}
          {contactsQ.data && contactsQ.data.items.length > 0 && (
            <ul className="divide-y divide-slate-100">
              {contactsQ.data.items.map((p) => (
                <li key={p.id}>
                  <Link
                    to={`/contacts/${p.id}`}
                    className="block px-4 py-3 hover:bg-slate-50"
                  >
                    <div className="font-medium">
                      {[p.first_name, p.last_name].filter(Boolean).join(" ") ||
                        p.email ||
                        "—"}
                    </div>
                    <div className="text-xs text-slate-500">
                      {dash(p.job_title)}
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
      )}

      {quotationForFollowup && (
        <ActivityCreateModal
          onClose={() => setQuotationForFollowup(null)}
          onCreated={() => setQuotationForFollowup(null)}
          defaultTargetType="company"
          defaultTargetId={c.id}
          defaultQuotationId={quotationForFollowup.id}
          defaultSubject={`Nabellen offerte ${quotationForFollowup.reference}${quotationForFollowup.subject ? ": " + quotationForFollowup.subject : ""}`}
        />
      )}

      {editing && (
        <FormDialog
          open
          onClose={() => setEditing(false)}
          title={`Edit ${c.name}`}
          fields={editFields}
          initialValues={{
            name: c.name,
            domain: c.domain,
            industry: c.industry,
            size: c.size,
            description: c.description,
          }}
          submitLabel="Save changes"
          onSubmit={async (values: FormValues) => {
            await updateMut.mutateAsync(values);
          }}
        />
      )}
    </div>
  );
}

// ===== Communications panel =====

type CommEntry = {
  id: string;
  kind: "campaign_mail" | "sequence_mail" | "linkedin_post" | "linkedin_task";
  direction: "outbound" | "inbound";
  subject: string | null;
  snippet: string | null;
  to_name: string | null;
  to_email: string | null;
  sent_at: string | null;
  delivered_at: string | null;
  opened_at: string | null;
  clicked_at: string | null;
  bounced_at: string | null;
  status: string | null;
  campaign_id: string | null;
  post_id: string | null;
  external_url: string | null;
};

type CommsResponse = {
  company_id: string;
  total: number;
  entries: CommEntry[];
  last_outbound_at: string | null;
  last_open_at: string | null;
  open_count: number;
  click_count: number;
};

const KIND_LABEL: Record<CommEntry["kind"], { icon: string; label: string; bg: string; fg: string }> = {
  campaign_mail:  { icon: "\u2709",        label: "Campagne-mail",  bg: "#E6F1FB", fg: "#0C447C" },
  sequence_mail:  { icon: "\u27a4",        label: "Sequence-mail",  bg: "#FAEEDA", fg: "#854F0B" },
  linkedin_post:  { icon: "\ud83d\udcac",  label: "LinkedIn post",  bg: "#EEEDFE", fg: "#3C3489" },
  linkedin_task:  { icon: "\u27a1",        label: "LinkedIn taak",  bg: "#F1F5F9", fg: "#475569" },
};

function CommunicationsPanel({ companyId }: { companyId: string }) {
  const [kindFilter, setKindFilter] = useState<"all" | CommEntry["kind"]>("all");
  const commsQ = useQuery<CommsResponse>({
    queryKey: ["/communications", companyId],
    queryFn: () => api<CommsResponse>(`/companies/${companyId}/communications`),
  });

  if (commsQ.isLoading) {
    return <div className="rounded-lg ring-1 ring-slate-200 bg-white p-6 text-sm text-slate-500">Bezig met laden\u2026</div>;
  }

  const data = commsQ.data;
  const entries = (data?.entries ?? []).filter((e) => kindFilter === "all" || e.kind === kindFilter);

  return (
    <div className="space-y-4">
      {/* Summary strip */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <SummaryCard label="Totaal verstuurd" value={String(data?.total ?? 0)} />
        <SummaryCard label="Open events" value={String(data?.open_count ?? 0)} tone="emerald" />
        <SummaryCard label="Click events" value={String(data?.click_count ?? 0)} tone="emerald" />
        <SummaryCard
          label="Laatste contact"
          value={data?.last_outbound_at ? new Date(data.last_outbound_at).toLocaleDateString("nl-NL") : "\u2014"}
        />
      </div>

      {/* Filter pills */}
      <div className="flex flex-wrap items-center gap-1">
        {(["all", "campaign_mail", "sequence_mail", "linkedin_post", "linkedin_task"] as const).map((k) => {
          const active = kindFilter === k;
          const count = k === "all" ? (data?.total ?? 0) : (data?.entries ?? []).filter((e) => e.kind === k).length;
          return (
            <button
              key={k}
              type="button"
              onClick={() => setKindFilter(k)}
              className={`rounded-md px-3 py-1.5 text-sm font-medium border ${
                active
                  ? "border-brand-500 bg-brand-500 text-white"
                  : "border-slate-200 bg-white text-slate-700 hover:bg-slate-50"
              }`}
            >
              {k === "all" ? `Alle (${data?.total ?? 0})` : `${KIND_LABEL[k].icon} ${KIND_LABEL[k].label} (${count})`}
            </button>
          );
        })}
      </div>

      {entries.length === 0 && (
        <div className="rounded-lg ring-1 ring-slate-200 bg-white p-10 text-center text-sm text-slate-500">
          <div className="text-3xl mb-2">\u270b</div>
          <div className="font-medium text-slate-700">Nog geen communicatie</div>
          <div className="mt-1">Mailings via HaloPSA + sequence-emails + LinkedIn-posts naar deze klant verschijnen hier.</div>
        </div>
      )}

      <div className="rounded-lg ring-1 ring-slate-200 bg-white overflow-hidden">
        <ul className="divide-y divide-slate-100">
          {entries.map((e) => <CommRow key={e.id} entry={e} />)}
        </ul>
      </div>
    </div>
  );
}

function CommRow({ entry }: { entry: CommEntry }) {
  const meta = KIND_LABEL[entry.kind];
  const isMail = entry.kind === "campaign_mail" || entry.kind === "sequence_mail";

  return (
    <li className="px-4 py-3 hover:bg-slate-50">
      <div className="flex items-start gap-3">
        <div
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-base"
          style={{ backgroundColor: meta.bg, color: meta.fg }}
        >
          {meta.icon}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-baseline gap-2">
            <span className="text-[10px] uppercase tracking-wider text-slate-500">{meta.label}</span>
            <span className="text-xs text-slate-400">\u00b7 {fmtDateTime(entry.sent_at)}</span>
            {entry.status && (
              <span className="ml-1 rounded-full bg-slate-100 px-2 py-0.5 text-[10px] text-slate-600">
                {entry.status}
              </span>
            )}
          </div>
          <div className="mt-0.5 truncate text-sm font-medium">
            {entry.subject || "(geen onderwerp)"}
          </div>
          {entry.snippet && (
            <div className="mt-0.5 truncate text-xs text-slate-500">{entry.snippet}</div>
          )}
          <div className="mt-1 text-[11px] text-slate-500">
            {entry.to_email && <span className="mr-3">naar {entry.to_name ? `${entry.to_name} <${entry.to_email}>` : entry.to_email}</span>}
            {isMail && (
              <span className="inline-flex items-center gap-2">
                {entry.delivered_at && <span title={fmtDateTime(entry.delivered_at) || ""}>\u2709 bezorgd</span>}
                {entry.opened_at && <span className="text-emerald-700" title={fmtDateTime(entry.opened_at) || ""}>\ud83d\udc41 geopend</span>}
                {entry.clicked_at && <span className="text-emerald-700" title={fmtDateTime(entry.clicked_at) || ""}>\u270b geklikt</span>}
                {entry.bounced_at && <span className="text-red-700" title={fmtDateTime(entry.bounced_at) || ""}>\u26a0 bounced</span>}
              </span>
            )}
          </div>
        </div>
        <div className="shrink-0 flex flex-col items-end gap-1">
          {entry.external_url && (
            <a href={entry.external_url} target="_blank" rel="noreferrer"
              className="text-xs text-brand-600 hover:underline">Open \u2197</a>
          )}
          {entry.campaign_id && (
            <Link to={`/mail-campaigns/${entry.campaign_id}`} className="text-xs text-brand-600 hover:underline">
              Naar campagne \u2197
            </Link>
          )}
          {entry.post_id && (
            <Link to={`/social/${entry.post_id}`} className="text-xs text-brand-600 hover:underline">
              Naar post \u2197
            </Link>
          )}
        </div>
      </div>
    </li>
  );
}

function SummaryCard({ label, value, tone = "default" }: { label: string; value: string; tone?: "default" | "emerald" }) {
  const toneCls = tone === "emerald" ? "text-emerald-700" : "text-slate-900";
  return (
    <div className="rounded-md border border-slate-200 bg-white p-3">
      <div className="text-[10px] uppercase tracking-wider text-slate-500">{label}</div>
      <div className={`mt-1 text-xl font-medium tabular-nums ${toneCls}`}>{value}</div>
    </div>
  );
}
