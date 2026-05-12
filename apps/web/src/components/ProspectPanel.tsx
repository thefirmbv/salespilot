import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";

type Company = {
  id: string;
  name: string;
  domain: string | null;
  industry: string | null;
  employees: number | null;
  city: string | null;
  country: string | null;
  source: string;
  mail_platform: "m365" | "google" | "other" | "unknown";
  lead_score: number;
  last_visit_at: string | null;
  pageview_count_30d: number;
};

type CallscriptStep = { title: string; content: string };
type Callscript = {
  company_id: string;
  generated_at: string;
  model: string;
  steps: CallscriptStep[];
  context_summary: string;
  website_summary?: string | null;
  decision_maker_hint?: string | null;
};

type VisitorEvent = {
  id: string;
  source: string;
  event_type: string;
  url: string | null;
  page_title: string | null;
  occurred_at: string;
};

function scoreBucket(score: number): "hot" | "warm" | "cold" {
  if (score >= 80) return "hot";
  if (score >= 50) return "warm";
  return "cold";
}

function ScorePill({ score }: { score: number }) {
  const bucket = scoreBucket(score);
  const styles: Record<string, { bg: string; dot: string; text: string }> = {
    hot:  { bg: "#FCEBEB", dot: "#A32D2D", text: "#791F1F" },
    warm: { bg: "#FAEEDA", dot: "#BA7517", text: "#633806" },
    cold: { bg: "#F1F5F9", dot: "#64748B", text: "#475569" },
  };
  const s = styles[bucket];
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium tabular-nums"
      style={{ backgroundColor: s.bg, color: s.text }}
    >
      <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: s.dot }} />
      {score} {bucket}
    </span>
  );
}

function MailLabel({ platform }: { platform: string }) {
  const labels: Record<string, string> = {
    m365: "Microsoft 365",
    google: "Google Workspace",
    other: "Other",
    unknown: "Unknown",
  };
  return <span>{labels[platform] ?? platform}</span>;
}

function relativeFromNow(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const diff = Date.now() - d.getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m} min ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} u ago`;
  const days = Math.floor(h / 24);
  return `${days} d ago`;
}

function computeBreakdown(c: Company, urls: string[], dates: Date[]) {
  // Mirror the server-side scoring rules so users see why a score is what it is.
  const items: { label: string; delta: number }[] = [];
  if (c.employees !== null) {
    if (c.employees >= 20 && c.employees <= 60) items.push({ label: "ICP fit (size 20-60)", delta: 30 });
    else if ((c.employees >= 1 && c.employees <= 19) || (c.employees >= 61 && c.employees <= 150))
      items.push({ label: "Mid-fit company size", delta: 10 });
  }
  const has = (kws: string[]) => urls.some((u) => kws.some((k) => u.toLowerCase().includes(k)));
  if (has(["pricing", "tarieven", "prijs"])) items.push({ label: "Pricing page visited", delta: 25 });
  if (has(["contact"])) items.push({ label: "Contact page visited", delta: 10 });
  if (has(["case", "klantverhaal", "customer"])) items.push({ label: "Case study page visited", delta: 10 });
  const distinctDays = new Set(dates.map((d) => d.toDateString()));
  if (distinctDays.size >= 2) items.push({ label: "Return visitor", delta: 20 });
  if (c.mail_platform === "m365") items.push({ label: "Microsoft 365 detected", delta: 10 });
  else if (c.mail_platform === "google") items.push({ label: "Google Workspace detected", delta: 10 });
  if (c.last_visit_at) {
    const age = (Date.now() - new Date(c.last_visit_at).getTime()) / 1000 / 60 / 60;
    if (age <= 1) items.push({ label: "Recent activity (<1h)", delta: 10 });
    else if (age <= 24) items.push({ label: "Active today", delta: 5 });
  }
  return items;
}

export function ProspectPanel({ company }: { company: Company }) {
  const qc = useQueryClient();
  const [showFullSummary, setShowFullSummary] = useState(false);

  const eventsQ = useQuery<{ items: VisitorEvent[]; total: number }>({
    queryKey: [`/visitor-events/${company.id}`],
    queryFn: async () => {
      try {
        return await api<{ items: VisitorEvent[]; total: number }>(
          `/visitor_events?company_id=${company.id}&limit=20&sort=-occurred_at`,
        );
      } catch {
        return { items: [], total: 0 };
      }
    },
  });

  const callscriptMut = useMutation({
    mutationFn: () =>
      api<Callscript>(`/companies/${company.id}/callscript`, { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [`/companies/${company.id}`] });
    },
  });

  const mxMut = useMutation({
    mutationFn: () =>
      api<{ platform: string; records: string[] }>(`/companies/${company.id}/refresh-mx`, { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [`/companies/${company.id}`] });
    },
  });

  // Aggregate the page URLs we know about — used both for "pages visited"
  // and for the score breakdown.
  const events = eventsQ.data?.items ?? [];
  const urls = events.map((e) => e.url ?? "");
  const dates = events.map((e) => new Date(e.occurred_at));

  // Tally pages visited (path-level, ignore query string).
  const pageCounts = new Map<string, number>();
  for (const e of events) {
    if (!e.url) continue;
    try {
      const u = new URL(e.url);
      const path = u.pathname || "/";
      pageCounts.set(path, (pageCounts.get(path) ?? 0) + 1);
    } catch {
      pageCounts.set(e.url, (pageCounts.get(e.url) ?? 0) + 1);
    }
  }
  const topPages = [...pageCounts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 6);

  const breakdown = computeBreakdown(company, urls, dates);
  const breakdownTotal = breakdown.reduce((acc, b) => acc + b.delta, 0);

  const script: Callscript | null = callscriptMut.data ?? null;

  return (
    <div className="mb-6 overflow-hidden rounded-lg bg-white ring-1 ring-slate-200">
      {/* KPI strip */}
      <div className="grid grid-cols-2 gap-3 border-b border-slate-200 bg-slate-50 p-4 md:grid-cols-4">
        <div className="rounded-md border border-slate-200 bg-white p-3">
          <div className="text-[10px] uppercase tracking-wider text-slate-500">Lead score</div>
          <div className="mt-1"><ScorePill score={company.lead_score} /></div>
        </div>
        <div className="rounded-md border border-slate-200 bg-white p-3">
          <div className="text-[10px] uppercase tracking-wider text-slate-500">Pageviews</div>
          <div className="mt-1 text-lg font-medium tabular-nums">{company.pageview_count_30d}</div>
          <div className="text-[11px] text-slate-500">last 30 days</div>
        </div>
        <div className="rounded-md border border-slate-200 bg-white p-3">
          <div className="text-[10px] uppercase tracking-wider text-slate-500">Mail platform</div>
          <div className="mt-1 text-sm font-medium"><MailLabel platform={company.mail_platform} /></div>
          <button
            onClick={() => mxMut.mutate()}
            disabled={mxMut.isPending}
            className="text-[11px] text-brand-600 underline disabled:opacity-50"
          >
            {mxMut.isPending ? "Checking…" : "Refresh MX"}
          </button>
        </div>
        <div className="rounded-md border border-slate-200 bg-white p-3">
          <div className="text-[10px] uppercase tracking-wider text-slate-500">Last visit</div>
          <div className="mt-1 text-sm font-medium">{relativeFromNow(company.last_visit_at)}</div>
        </div>
      </div>

      <div className="grid gap-0 md:grid-cols-[1.5fr_1fr]">
        {/* Left: AI Callscript */}
        <div className="border-b border-slate-200 p-4 md:border-b-0 md:border-r">
          <div className="mb-3 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className="text-sm font-medium">AI Callscript</div>
              {script && (
                <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-medium text-emerald-800">
                  generated just now
                </span>
              )}
            </div>
            <button
              onClick={() => callscriptMut.mutate()}
              disabled={callscriptMut.isPending}
              className="rounded-md border border-slate-300 bg-white px-2.5 py-1 text-xs hover:bg-slate-50 disabled:opacity-50"
            >
              {callscriptMut.isPending ? "Generating…" : script ? "Regenerate" : "Generate"}
            </button>
          </div>

          {callscriptMut.isError && (
            <div className="rounded-md bg-red-50 px-3 py-1.5 text-xs text-red-800">
              {callscriptMut.error instanceof ApiError ? callscriptMut.error.detail : "Generation failed"}
            </div>
          )}

          {!script && !callscriptMut.isPending && (
            <div className="rounded-md border border-dashed border-slate-300 bg-slate-50 p-6 text-center text-xs text-slate-500">
              Click <span className="font-medium">Generate</span> to build a personalised
              call script based on this prospect's signals.
            </div>
          )}

          {script && (
            <div className="space-y-3">
              {script.steps.map((s, i) => (
                <div key={i} className="rounded-md bg-slate-50 p-3">
                  <div className="mb-1 text-[10px] uppercase tracking-wider text-slate-500">
                    {i + 1} · {s.title}
                  </div>
                  <div className="text-sm leading-relaxed text-slate-800 whitespace-pre-wrap">
                    {s.content}
                  </div>
                </div>
              ))}
              <div className="mt-3 text-[11px] text-slate-500">
                Model: <span className="font-mono">{script.model}</span>
              </div>
            </div>
          )}
        </div>

        {/* Right: Website context + Pages visited + Score breakdown */}
        <div className="p-4 space-y-5">
          {script?.website_summary && (
            <div>
              <div className="mb-1 text-sm font-medium">Website context</div>
              <div className="text-xs leading-relaxed text-slate-700">
                {showFullSummary
                  ? script.website_summary
                  : script.website_summary.slice(0, 240) +
                    (script.website_summary.length > 240 ? "…" : "")}
                {script.website_summary.length > 240 && (
                  <button
                    onClick={() => setShowFullSummary((v) => !v)}
                    className="ml-1 text-brand-600 underline"
                  >
                    {showFullSummary ? "less" : "more"}
                  </button>
                )}
              </div>
            </div>
          )}

          <div>
            <div className="mb-1 text-sm font-medium">Pages visited</div>
            {topPages.length === 0 ? (
              <div className="text-xs text-slate-500">No pageviews yet.</div>
            ) : (
              <div className="space-y-1 text-xs">
                {topPages.map(([path, count]) => (
                  <div key={path} className="flex justify-between">
                    <span className="truncate font-mono text-slate-700">{path}</span>
                    <span className="ml-2 text-slate-500 tabular-nums">×{count}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div>
            <div className="mb-1 text-sm font-medium">Score breakdown</div>
            <div className="space-y-1 text-xs">
              {breakdown.length === 0 ? (
                <div className="text-slate-500">No active signals.</div>
              ) : (
                breakdown.map((b, i) => (
                  <div key={i} className="flex justify-between">
                    <span className="text-slate-700">{b.label}</span>
                    <span className="tabular-nums text-slate-600">+{b.delta}</span>
                  </div>
                ))
              )}
              <div className="flex justify-between border-t border-slate-200 pt-1 font-medium">
                <span>Total (raw)</span>
                <span className="tabular-nums">{breakdownTotal}</span>
              </div>
              <div className="flex justify-between text-slate-500">
                <span>Stored</span>
                <span className="tabular-nums">{company.lead_score}</span>
              </div>
            </div>
          </div>

          {script?.decision_maker_hint && (
            <div>
              <div className="mb-1 text-sm font-medium">Decision maker hint</div>
              <div className="text-xs text-slate-700">{script.decision_maker_hint}</div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
