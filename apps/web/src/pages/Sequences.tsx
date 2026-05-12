import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

type Sequence = {
  id: string;
  name: string;
  description: string | null;
  status: "draft" | "active" | "paused";
  auto_enroll_bucket: "hot" | "warm" | "cold" | null;
  from_name: string;
  from_email: string;
  daily_limit: number;
  cooldown_hours: number;
  updated_at: string;
};

type Enrollment = {
  id: string;
  sequence_id: string;
  status: "active" | "replied" | "stopped" | "done";
};

type Message = {
  id: string;
  sequence_id: string | null;
  status: "queued" | "sent" | "delivered" | "opened" | "replied" | "bounced" | "failed";
  sent_at: string | null;
  scheduled_at: string | null;
};

type TodayItem = {
  enrollment_id: string;
  company_name: string;
  step_position: number;
  step_kind: string;
  scheduled_at: string;
  bucket: "hot" | "warm" | "cold" | null;
};

function BucketPill({ bucket }: { bucket: string | null }) {
  if (!bucket) {
    return (
      <span className="inline-flex items-center rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-600">
        manual
      </span>
    );
  }
  const styles: Record<string, { bg: string; dot: string; text: string }> = {
    hot:  { bg: "#FCEBEB", dot: "#A32D2D", text: "#791F1F" },
    warm: { bg: "#FAEEDA", dot: "#BA7517", text: "#633806" },
    cold: { bg: "#F1F5F9", dot: "#64748B", text: "#475569" },
  };
  const s = styles[bucket] ?? styles.cold;
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium tabular-nums"
      style={{ backgroundColor: s.bg, color: s.text }}
    >
      <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: s.dot }} />
      {bucket === "hot" ? "Hot \u226580" : bucket === "warm" ? "Warm 50-79" : "Cold <50"}
    </span>
  );
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    active:  "bg-emerald-50 text-emerald-800",
    draft:   "bg-slate-100 text-slate-600",
    paused:  "bg-amber-50 text-amber-800",
    replied: "bg-emerald-50 text-emerald-800",
    stopped: "bg-slate-100 text-slate-600",
    done:    "bg-slate-100 text-slate-600",
  };
  const cls = map[status] ?? "bg-slate-100 text-slate-600";
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ${cls}`}>
      {status}
    </span>
  );
}

function relTime(iso: string): string {
  const d = new Date(iso);
  const m = Math.floor((d.getTime() - Date.now()) / 60000);
  if (m < 0) return "now";
  if (m < 60) return `in ${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `in ${h}h`;
  return d.toLocaleString("nl-NL", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function Sequences() {
  const qc = useQueryClient();

  const seqQ = useQuery<Sequence[]>({
    queryKey: ["/sequences"],
    queryFn: () => api<Sequence[]>("/sequences"),
  });
  const enrQ = useQuery<Enrollment[]>({
    queryKey: ["/enrollments"],
    queryFn: () => api<Enrollment[]>("/enrollments"),
  });
  const msgQ = useQuery<Message[]>({
    queryKey: ["/messages"],
    queryFn: () => api<Message[]>("/messages?limit=200"),
  });
  const queueQ = useQuery<TodayItem[]>({
    queryKey: ["/sequences/today"],
    queryFn: async () => {
      try {
        return await api<TodayItem[]>("/sequences/today");
      } catch {
        return [];
      }
    },
  });

  const createMut = useMutation({
    mutationFn: () =>
      api<Sequence>("/sequences", {
        method: "POST",
        body: JSON.stringify({
          name: "New sequence",
          status: "draft",
          from_name: "Sales",
          from_email: "",
          daily_limit: 25,
          cooldown_hours: 48,
          stop_on_reply: true,
          send_window_json: {
            days: [2, 3, 4],
            slots: [{ start: "09:00", end: "11:00" }, { start: "14:00", end: "16:00" }],
            timezone: "Europe/Amsterdam",
          },
        }),
      }),
    onSuccess: (seq) => {
      qc.invalidateQueries({ queryKey: ["/sequences"] });
      window.location.href = `/sequences/${seq.id}`;
    },
  });

  const sequences = seqQ.data ?? [];
  const enrollments = enrQ.data ?? [];
  const messages = msgQ.data ?? [];
  const queue = queueQ.data ?? [];

  // Aggregate stats per sequence.
  const statsBySeq = new Map<string, { active: number; replied: number }>();
  for (const e of enrollments) {
    const s = statsBySeq.get(e.sequence_id) ?? { active: 0, replied: 0 };
    if (e.status === "active") s.active += 1;
    if (e.status === "replied") s.replied += 1;
    statsBySeq.set(e.sequence_id, s);
  }

  // Global stats: sent (7d), replies, today.
  const sevenDaysAgo = Date.now() - 7 * 86400e3;
  const sent7d = messages.filter(
    (m) => m.sent_at && new Date(m.sent_at).getTime() > sevenDaysAgo,
  ).length;
  const replied = messages.filter((m) => m.status === "replied").length;
  const activeTotal = enrollments.filter((e) => e.status === "active").length;
  const replyRate = sent7d > 0 ? Math.round((replied / sent7d) * 100 * 10) / 10 : 0;

  // Order sequences: by bucket priority first, then by name.
  const bucketOrder = { hot: 0, warm: 1, cold: 2 } as Record<string, number>;
  const sorted = [...sequences].sort((a, b) => {
    const ao = a.auto_enroll_bucket ? bucketOrder[a.auto_enroll_bucket] ?? 9 : 9;
    const bo = b.auto_enroll_bucket ? bucketOrder[b.auto_enroll_bucket] ?? 9 : 9;
    if (ao !== bo) return ao - bo;
    return a.name.localeCompare(b.name);
  });

  return (
    <div>
      <div className="overflow-hidden rounded-lg bg-white ring-1 ring-slate-200">
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
          <div>
            <h1 className="text-lg font-medium">Sequences</h1>
            <div className="mt-0.5 text-xs text-slate-500">
              Mail autopilot \u00b7 score-driven enrollment
            </div>
          </div>
          <button
            onClick={() => createMut.mutate()}
            disabled={createMut.isPending}
            className="rounded-md bg-brand-500 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-600 disabled:opacity-50"
          >
            + New sequence
          </button>
        </div>

        <div className="grid grid-cols-2 gap-3 border-b border-slate-200 bg-slate-50 p-4 md:grid-cols-4">
          <div className="rounded-md border border-slate-200 bg-white p-3">
            <div className="text-[10px] uppercase tracking-wider text-slate-500">Active enrollments</div>
            <div className="mt-1 text-xl font-medium tabular-nums">{activeTotal}</div>
          </div>
          <div className="rounded-md border border-slate-200 bg-white p-3">
            <div className="text-[10px] uppercase tracking-wider text-slate-500">Sent (7d)</div>
            <div className="mt-1 text-xl font-medium tabular-nums">{sent7d}</div>
          </div>
          <div className="rounded-md border border-slate-200 bg-white p-3">
            <div className="text-[10px] uppercase tracking-wider text-slate-500">Replies</div>
            <div className="mt-1 text-xl font-medium tabular-nums text-emerald-700">{replied}</div>
            <div className="text-[11px] text-slate-500">{replyRate}% rate</div>
          </div>
          <div className="rounded-md border border-slate-200 bg-white p-3">
            <div className="text-[10px] uppercase tracking-wider text-slate-500">Today's queue</div>
            <div className="mt-1 text-xl font-medium tabular-nums">{queue.length}</div>
          </div>
        </div>

        <div className="px-4 pt-4 pb-2 text-[10px] uppercase tracking-wider text-slate-400">
          Campaigns
        </div>

        {seqQ.isLoading && <div className="px-4 pb-6 text-sm text-slate-500">Loading\u2026</div>}

        {!seqQ.isLoading && sorted.length === 0 && (
          <div className="px-4 pb-6 pt-2 text-sm text-slate-500">
            No sequences yet. Click <span className="font-medium">+ New sequence</span> to create one.
          </div>
        )}

        <div className="space-y-2 px-4 pb-4">
          {sorted.map((s) => {
            const stats = statsBySeq.get(s.id) ?? { active: 0, replied: 0 };
            return (
              <Link
                key={s.id}
                to={`/sequences/${s.id}`}
                className="grid grid-cols-[110px_minmax(0,1fr)_auto_auto_auto] items-center gap-3 rounded-md border border-slate-200 px-3 py-3 hover:bg-slate-50"
              >
                <BucketPill bucket={s.auto_enroll_bucket} />
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium">{s.name}</div>
                  <div className="truncate text-xs text-slate-500">
                    {s.description ?? "\u2014"}
                  </div>
                </div>
                <div className="text-right text-xs text-slate-500">
                  <div className="font-medium text-slate-700 tabular-nums">{stats.active}</div>
                  <div>active</div>
                </div>
                <div className="text-right text-xs text-slate-500">
                  <div className="font-medium tabular-nums text-emerald-700">{stats.replied}</div>
                  <div>replied</div>
                </div>
                <StatusBadge status={s.status} />
              </Link>
            );
          })}
        </div>
      </div>

      {/* Today's queue */}
      {queue.length > 0 && (
        <div className="mt-4 overflow-hidden rounded-lg bg-white ring-1 ring-slate-200">
          <div className="border-b border-slate-200 px-4 py-2 text-[10px] uppercase tracking-wider text-slate-500">
            Today's queue
          </div>
          <div className="divide-y divide-slate-100">
            {queue.map((q, i) => (
              <div
                key={i}
                className="grid grid-cols-[80px_minmax(0,1fr)_auto] items-center gap-3 px-4 py-2 text-xs"
              >
                <div className="font-mono text-slate-500">
                  {new Date(q.scheduled_at).toLocaleTimeString("nl-NL", {
                    hour: "2-digit", minute: "2-digit",
                  })}
                </div>
                <div>
                  <span className="font-medium">{q.company_name}</span>{" "}
                  <span className="text-slate-500">
                    \u00b7 {q.bucket ?? "manual"} \u00b7 step {q.step_position} {q.step_kind}
                  </span>
                </div>
                <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] text-slate-600">
                  {relTime(q.scheduled_at)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
