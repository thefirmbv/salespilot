import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

type LinkedInTask = {
  id: string;
  company_id: string;
  company_name: string | null;
  contact_id: string | null;
  contact_name: string | null;
  contact_linkedin_url: string | null;
  kind: "connect" | "dm" | "like" | "visit";
  status: "todo" | "sent" | "connected" | "replied" | "skipped";
  suggested_text: string | null;
  external_url: string | null;
  scheduled_at: string | null;
  sent_at: string | null;
  replied_at: string | null;
  created_at: string;
};

type LinkedInPost = {
  id: string;
  title: string;
  body: string;
  status: "draft" | "scheduled" | "published" | "failed";
  scheduled_at: string | null;
  published_at: string | null;
  target: "person" | "organization";
};

const KIND_LABELS: Record<string, string> = {
  connect: "Connect",
  dm: "DM",
  like: "Like post",
  visit: "Profile visit",
};

const STATUSES: { id: LinkedInTask["status"]; label: string; tone: string }[] = [
  { id: "todo",      label: "To do",     tone: "bg-slate-100 text-slate-700" },
  { id: "sent",      label: "Sent",      tone: "bg-blue-50 text-blue-800"    },
  { id: "connected", label: "Connected", tone: "bg-amber-50 text-amber-800"  },
  { id: "replied",   label: "Replied",   tone: "bg-emerald-50 text-emerald-800" },
];

function relDate(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  if (diff < 30 * 86400) return `${Math.floor(diff / 86400)}d ago`;
  return d.toLocaleDateString("nl-NL");
}

function TaskCard({ t, onPatch, onDelete }: {
  t: LinkedInTask;
  onPatch: (patch: Partial<LinkedInTask>) => void;
  onDelete: () => void;
}) {
  const [showCopied, setShowCopied] = useState(false);
  const copy = async () => {
    if (!t.suggested_text) return;
    try {
      await navigator.clipboard.writeText(t.suggested_text);
      setShowCopied(true);
      setTimeout(() => setShowCopied(false), 1500);
    } catch {
      /* ignore */
    }
  };

  return (
    <div className="mb-2 rounded-md border border-slate-200 bg-white p-2.5">
      <div className="text-xs font-medium">{t.company_name ?? "Unknown company"}</div>
      <div className="mt-0.5 text-[11px] text-slate-500">
        {KIND_LABELS[t.kind]}
        {t.contact_name && <> · {t.contact_name}</>}
      </div>
      {t.suggested_text && (
        <div className="mt-2 rounded bg-slate-50 px-2 py-1.5 text-[11px] text-slate-700 leading-relaxed font-mono">
          {t.suggested_text}
        </div>
      )}
      <div className="mt-2 flex gap-1.5">
        {t.suggested_text && (
          <button
            onClick={copy}
            className="flex-1 rounded border border-slate-300 px-2 py-1 text-[10px] hover:bg-slate-50"
          >
            {showCopied ? "Copied" : "Copy"}
          </button>
        )}
        {t.contact_linkedin_url && (
          <a
            href={t.contact_linkedin_url}
            target="_blank"
            rel="noreferrer"
            className="flex-1 rounded border border-slate-300 px-2 py-1 text-center text-[10px] hover:bg-slate-50"
          >
            Open ↗
          </a>
        )}
      </div>
      <div className="mt-2 flex gap-1.5">
        <select
          value={t.status}
          onChange={(e) => onPatch({ status: e.target.value as LinkedInTask["status"] })}
          className="flex-1 rounded border border-slate-300 px-1 py-0.5 text-[10px]"
        >
          {STATUSES.map((s) => (
            <option key={s.id} value={s.id}>Set: {s.label}</option>
          ))}
          <option value="skipped">Set: Skipped</option>
        </select>
        <button
          onClick={onDelete}
          className="rounded border border-slate-200 px-1.5 py-0.5 text-[10px] text-slate-400 hover:bg-red-50 hover:text-red-700"
          aria-label="Delete task"
        >
          ✕
        </button>
      </div>
      {t.replied_at && (
        <div className="mt-1 text-[10px] text-emerald-700">replied {relDate(t.replied_at)}</div>
      )}
    </div>
  );
}

export function LinkedInOutreach() {
  const qc = useQueryClient();
  const [tab, setTab] = useState<"tasks" | "posts">("tasks");

  const tasksQ = useQuery<LinkedInTask[]>({
    queryKey: ["/linkedin_tasks"],
    queryFn: () => api<LinkedInTask[]>("/linkedin_tasks?limit=200"),
  });
  const postsQ = useQuery<LinkedInPost[]>({
    queryKey: ["/linkedin_posts"],
    queryFn: async () => {
      try {
        return await api<LinkedInPost[]>("/linkedin_posts");
      } catch {
        return [];
      }
    },
    enabled: tab === "posts",
  });

  const integrationQ = useQuery<{ is_configured: boolean; is_enabled: boolean } | null>({
    queryKey: ["/integrations/linkedin-summary"],
    queryFn: async () => {
      try {
        const all = await api<{ kind: string; is_configured: boolean; is_enabled: boolean }[]>("/integrations");
        return all.find((i) => i.kind === "linkedin") ?? null;
      } catch {
        return null;
      }
    },
  });

  const patchMut = useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: Partial<LinkedInTask> }) =>
      api(`/linkedin_tasks/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["/linkedin_tasks"] }),
  });
  const deleteMut = useMutation({
    mutationFn: (id: string) => api(`/linkedin_tasks/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["/linkedin_tasks"] }),
  });

  const tasks = tasksQ.data ?? [];
  const byStatus: Record<string, LinkedInTask[]> = { todo: [], sent: [], connected: [], replied: [] };
  for (const t of tasks) {
    if (t.status in byStatus) byStatus[t.status].push(t);
  }

  return (
    <div>
      <div className="overflow-hidden rounded-lg bg-white ring-1 ring-slate-200">
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
          <div>
            <h1 className="text-lg font-medium">LinkedIn</h1>
            <div className="mt-0.5 text-xs text-slate-500">
              Posts &amp; outreach tasks
              {integrationQ.data?.is_configured ? (
                <> · <span className="text-emerald-700">connected</span></>
              ) : (
                <> · <span className="text-amber-700">not connected</span></>
              )}
            </div>
          </div>
          {!integrationQ.data?.is_configured && (
            <a
              href="/settings/integrations/linkedin"
              className="rounded-md bg-brand-500 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-600"
            >
              Connect LinkedIn
            </a>
          )}
        </div>

        <div className="flex gap-1 border-b border-slate-200 px-4">
          <button
            onClick={() => setTab("tasks")}
            className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium ${
              tab === "tasks"
                ? "border-brand-500 text-slate-900"
                : "border-transparent text-slate-500 hover:text-slate-800"
            }`}
          >
            Outreach tasks
          </button>
          <button
            onClick={() => setTab("posts")}
            className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium ${
              tab === "posts"
                ? "border-brand-500 text-slate-900"
                : "border-transparent text-slate-500 hover:text-slate-800"
            }`}
          >
            Scheduled posts
          </button>
        </div>

        {tab === "tasks" && (
          <div className="p-4">
            {tasksQ.isLoading && (
              <div className="text-sm text-slate-500">Loading…</div>
            )}
            {!tasksQ.isLoading && tasks.length === 0 && (
              <div className="rounded-md border border-dashed border-slate-300 bg-slate-50 p-10 text-center text-sm text-slate-500">
                No outreach tasks yet. LinkedIn-steps in your sequences will create tasks here as prospects move through the cadence.
              </div>
            )}
            {tasks.length > 0 && (
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-4">
                {STATUSES.map((s) => (
                  <div key={s.id} className="rounded-md bg-slate-50 p-2.5">
                    <div className="mb-2 flex items-center justify-between px-1">
                      <div className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${s.tone}`}>
                        {s.label}
                      </div>
                      <div className="text-[11px] text-slate-500 tabular-nums">{byStatus[s.id].length}</div>
                    </div>
                    {byStatus[s.id].map((t) => (
                      <TaskCard
                        key={t.id}
                        t={t}
                        onPatch={(patch) => patchMut.mutate({ id: t.id, patch })}
                        onDelete={() => {
                          if (confirm("Delete task?")) deleteMut.mutate(t.id);
                        }}
                      />
                    ))}
                  </div>
                ))}
              </div>
            )}
            <div className="mt-4 rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-900">
              Verzending niet automatisch. Tasks zijn voorbereid; je markeert ze handmatig als Sent zodra je ze in LinkedIn hebt uitgevoerd. Een externe tool of webhook kan later de status bijwerken.
            </div>
          </div>
        )}

        {tab === "posts" && (
          <div className="p-4">
            {(postsQ.data ?? []).length === 0 && (
              <div className="rounded-md border border-dashed border-slate-300 bg-slate-50 p-10 text-center text-sm text-slate-500">
                {integrationQ.data?.is_configured
                  ? "No scheduled posts yet."
                  : "Connect LinkedIn first to schedule posts."}
              </div>
            )}
            <div className="mt-2 text-xs text-slate-500">
              Posts gebruiken de officiële LinkedIn API — nul ban-risico.
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
