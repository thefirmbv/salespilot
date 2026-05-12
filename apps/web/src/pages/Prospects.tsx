import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import { useDebounce } from "@/lib/useDebounce";

type Prospect = {
  id: string;
  name: string;
  domain: string | null;
  industry: string | null;
  employees: number | null;
  city: string | null;
  source: string;
  mail_platform: "m365" | "google" | "other" | "unknown";
  lead_score: number;
  last_visit_at: string | null;
  pageview_count_30d: number;
  created_at: string;
};
type Page<T> = { items: T[]; total: number };
type SyncResult = { ok: boolean; detail: string; fetched?: number; created?: number; updated?: number };

function scoreBucket(score: number): "hot" | "warm" | "cold" {
  if (score >= 80) return "hot";
  if (score >= 50) return "warm";
  return "cold";
}

function ScorePill({ score }: { score: number }) {
  const bucket = scoreBucket(score);
  const styles: Record<string, { bg: string; dot: string; text: string; label: string }> = {
    hot:  { bg: "#FCEBEB", dot: "#A32D2D", text: "#791F1F", label: "hot"  },
    warm: { bg: "#FAEEDA", dot: "#BA7517", text: "#633806", label: "warm" },
    cold: { bg: "#F1F5F9", dot: "#64748B", text: "#475569", label: "cold" },
  };
  const s = styles[bucket];
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium tabular-nums"
      style={{ backgroundColor: s.bg, color: s.text }}
    >
      <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: s.dot }} />
      {score} {s.label}
    </span>
  );
}

function MailIcon({ platform }: { platform: string }) {
  if (platform === "m365") {
    return (
      <span title="Microsoft 365" className="text-blue-700">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-label="Microsoft 365">
          <path d="M3 3h8.5v8.5H3zM12.5 3H21v8.5h-8.5zM3 12.5h8.5V21H3zM12.5 12.5H21V21h-8.5z" />
        </svg>
      </span>
    );
  }
  if (platform === "google") {
    return (
      <span title="Google Workspace" className="text-red-700">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-label="Google Workspace">
          <path d="M12 2a10 10 0 100 20 10 10 0 000-20zm0 18a8 8 0 110-16 8 8 0 010 16zm-3-8a3 3 0 116 0 3 3 0 01-6 0z" />
        </svg>
      </span>
    );
  }
  if (platform === "other") {
    return <span title="Other" className="text-slate-400 text-xs font-medium">·</span>;
  }
  return <span title="Unknown" className="text-slate-300 text-xs">?</span>;
}

function ICPBadge({ employees }: { employees: number | null }) {
  if (employees === null) return null;
  const fits = employees >= 20 && employees <= 60;
  if (!fits) return null;
  return (
    <span className="rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-800">
      ICP
    </span>
  );
}

function PageviewBadges({ score }: { score: number }) {
  const tags: string[] = [];
  if (score >= 75) tags.push("pricing");
  if (score >= 65) tags.push("return");
  return (
    <div className="flex gap-1">
      {tags.map((t) => (
        <span
          key={t}
          className="rounded px-1.5 py-0.5 text-[10px] font-medium bg-amber-50 text-amber-800"
        >
          {t}
        </span>
      ))}
    </div>
  );
}

function relativeShort(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const diffMs = Date.now() - d.getTime();
  const m = Math.floor(diffMs / 60000);
  if (m < 1) return "now";
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} u`;
  const days = Math.floor(h / 24);
  if (days < 30) return `${days} d`;
  return d.toLocaleDateString("nl-NL", { day: "numeric", month: "short" });
}

function Avatar({ name }: { name: string }) {
  const initials =
    name
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((s) => s[0])
      .join("")
      .toUpperCase() || "?";
  return (
    <div className="h-8 w-8 shrink-0 rounded-full bg-brand-50 text-brand-700 text-xs font-medium flex items-center justify-center">
      {initials}
    </div>
  );
}

export function Prospects() {
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();

  const [q, setQ] = useState(params.get("q") ?? "");
  const debouncedQ = useDebounce(q, 300);
  if (debouncedQ !== (params.get("q") ?? "")) {
    const next = new URLSearchParams(params);
    if (debouncedQ) next.set("q", debouncedQ);
    else next.delete("q");
    setParams(next, { replace: true });
  }

  const scoreFilter = params.get("score") ?? "";
  const mailFilter = params.get("mail_platform") ?? "";
  const sizeFilter = params.get("size") ?? "";

  function setFilter(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  }

  const requestParams = new URLSearchParams();
  requestParams.set("source", "salespilot");
  requestParams.set("limit", "100");
  requestParams.set("sort", "-lead_score");
  if (debouncedQ) requestParams.set("q", debouncedQ);
  if (mailFilter) requestParams.set("mail_platform", mailFilter);
  const reqStr = requestParams.toString();

  const prospectsQ = useQuery<Page<Prospect>>({
    queryKey: ["/prospects-list", reqStr],
    queryFn: () => api<Page<Prospect>>(`/companies?${reqStr}`),
  });

  const items = (prospectsQ.data?.items ?? []).filter((p) => {
    if (scoreFilter === "hot" && p.lead_score < 80) return false;
    if (scoreFilter === "warm" && (p.lead_score < 50 || p.lead_score >= 80)) return false;
    if (scoreFilter === "cold" && p.lead_score >= 50) return false;
    if (sizeFilter === "icp" && !(p.employees && p.employees >= 20 && p.employees <= 60)) return false;
    if (sizeFilter === "small" && !(p.employees !== null && p.employees < 20)) return false;
    if (sizeFilter === "large" && !(p.employees !== null && p.employees > 60)) return false;
    return true;
  });

  const counts = (prospectsQ.data?.items ?? []).reduce(
    (acc, p) => {
      const b = scoreBucket(p.lead_score);
      acc[b] += 1;
      return acc;
    },
    { hot: 0, warm: 0, cold: 0 },
  );

  const syncMut = useMutation({
    mutationFn: () =>
      api<SyncResult>("/integrations/prospectpro/sync", { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["/prospects-list"] });
      qc.invalidateQueries({ queryKey: ["/integrations/prospectpro"] });
    },
  });

  const lastSyncQ = useQuery<{ last_sync_at: string | null } | null>({
    queryKey: ["/integrations/prospectpro"],
    queryFn: () => api("/integrations/prospectpro"),
  });

  const lastSync = lastSyncQ.data?.last_sync_at;
  const hasAnyFilter = !!(q || scoreFilter || mailFilter || sizeFilter);

  return (
    <div>
      <div className="overflow-hidden rounded-lg bg-white ring-1 ring-slate-200">
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
          <div>
            <h1 className="text-lg font-medium">Prospects</h1>
            <div className="mt-0.5 text-xs text-slate-500">
              {counts.hot} hot · {counts.warm} warm · {counts.cold} cold
              {lastSync && <> · last sync {relativeShort(lastSync)} ago</>}
            </div>
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => syncMut.mutate()}
              disabled={syncMut.isPending}
              className="inline-flex items-center gap-1.5 rounded-md bg-white px-3 py-1.5 text-sm text-slate-700 ring-1 ring-slate-300 hover:bg-slate-100 disabled:opacity-50"
            >
              {syncMut.isPending ? "Syncing…" : "Sync"}
            </button>
          </div>
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

        <div className="flex flex-wrap items-center gap-2 border-b border-slate-200 bg-slate-50 px-4 py-3">
          <input
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search by name, domain, industry..."
            className="flex-1 min-w-[220px] rounded-md border border-slate-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
          />
          <select
            value={scoreFilter}
            onChange={(e) => setFilter("score", e.target.value)}
            className="rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          >
            <option value="">Score: all</option>
            <option value="hot">Hot (80+)</option>
            <option value="warm">Warm (50-79)</option>
            <option value="cold">Cold (&lt;50)</option>
          </select>
          <select
            value={mailFilter}
            onChange={(e) => setFilter("mail_platform", e.target.value)}
            className="rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          >
            <option value="">Mail: all</option>
            <option value="m365">Microsoft 365</option>
            <option value="google">Google Workspace</option>
            <option value="other">Other</option>
            <option value="unknown">Unknown</option>
          </select>
          <select
            value={sizeFilter}
            onChange={(e) => setFilter("size", e.target.value)}
            className="rounded-md border border-slate-300 px-2 py-1.5 text-sm"
          >
            <option value="">Size: all</option>
            <option value="icp">20-60 (ICP)</option>
            <option value="small">1-19</option>
            <option value="large">61+</option>
          </select>
          {hasAnyFilter && (
            <button
              onClick={() => {
                setQ("");
                setParams(new URLSearchParams(), { replace: true });
              }}
              className="text-xs text-slate-500 hover:text-slate-900 underline"
            >
              Clear
            </button>
          )}
        </div>

        <div className="grid grid-cols-[minmax(0,2.2fr)_86px_110px_88px_60px_70px] gap-3 px-4 py-2 text-[11px] uppercase tracking-wider text-slate-500 border-b border-slate-200">
          <div>Company</div>
          <div>Score</div>
          <div>Signals</div>
          <div className="text-right">Pageviews</div>
          <div className="text-center">Mail</div>
          <div className="text-right">Last visit</div>
        </div>

        {prospectsQ.isLoading && (
          <div className="p-6 text-sm text-slate-500">Loading prospects…</div>
        )}

        {!prospectsQ.isLoading && items.length === 0 && (
          <div className="p-10 text-center text-sm text-slate-500">
            {hasAnyFilter
              ? "No prospects match these filters."
              : "No prospects yet. Connect ProspectPRO in Settings \u2192 Integrations, then click Sync."}
          </div>
        )}

        {items.map((p) => (
          <Link
            key={p.id}
            to={`/companies/${p.id}`}
            className="grid grid-cols-[minmax(0,2.2fr)_86px_110px_88px_60px_70px] gap-3 px-4 py-3 items-center border-b border-slate-100 last:border-0 hover:bg-slate-50"
          >
            <div className="flex items-center gap-2.5 min-w-0">
              <Avatar name={p.name} />
              <div className="min-w-0">
                <div className="flex items-center gap-1.5">
                  <span className="text-sm font-medium truncate">{p.name}</span>
                  <ICPBadge employees={p.employees} />
                </div>
                <div className="text-xs text-slate-500 truncate">
                  {p.domain ?? "no domain"}
                  {p.employees !== null && <> · {p.employees} medewerkers</>}
                  {p.industry && <> · {p.industry}</>}
                </div>
              </div>
            </div>
            <div>
              <ScorePill score={p.lead_score} />
            </div>
            <PageviewBadges score={p.lead_score} />
            <div className="text-right text-sm tabular-nums">{p.pageview_count_30d}</div>
            <div className="text-center">
              <MailIcon platform={p.mail_platform} />
            </div>
            <div className="text-right text-xs text-slate-500">
              {relativeShort(p.last_visit_at)}
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
