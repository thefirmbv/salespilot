import { useEffect, useState } from "react";
import { Link, useParams, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

type Sequence = {
  id: string;
  name: string;
  description: string | null;
  status: "draft" | "active" | "paused";
  auto_enroll_bucket: "hot" | "warm" | "cold" | null;
  auto_enroll_min_score: number | null;
  auto_enroll_max_score: number | null;
  from_name: string;
  from_email: string;
  reply_to_email: string | null;
  daily_limit: number;
  cooldown_hours: number;
  stop_on_reply: boolean;
  send_window_json: {
    days: number[];
    slots: { start: string; end: string }[];
    timezone: string;
  };
  updated_at: string;
};

type Step = {
  id: string;
  sequence_id: string;
  position: number;
  kind:
    | "email"
    | "linkedin_connect"
    | "linkedin_dm"
    | "linkedin_like"
    | "linkedin_visit";
  wait_days: number;
  template_subject: string | null;
  template_body: string | null;
  reply_in_thread: boolean;
};

const STEP_KIND_LABELS: Record<string, string> = {
  email: "Email",
  linkedin_connect: "LinkedIn connect",
  linkedin_dm: "LinkedIn DM",
  linkedin_like: "LinkedIn like",
  linkedin_visit: "LinkedIn visit",
};

const DAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

function BucketPill({ bucket }: { bucket: string | null }) {
  if (!bucket) {
    return (
      <span className="inline-flex items-center rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-600">
        Manual enrollment
      </span>
    );
  }
  const styles: Record<string, { bg: string; text: string; dot: string }> = {
    hot:  { bg: "#FCEBEB", text: "#791F1F", dot: "#A32D2D" },
    warm: { bg: "#FAEEDA", text: "#633806", dot: "#BA7517" },
    cold: { bg: "#F1F5F9", text: "#475569", dot: "#64748B" },
  };
  const s = styles[bucket] ?? styles.cold;
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium"
      style={{ backgroundColor: s.bg, color: s.text }}
    >
      <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: s.dot }} />
      {bucket === "hot" ? "Hot ≥80" : bucket === "warm" ? "Warm 50-79" : "Cold <50"}
    </span>
  );
}

export function SequenceEditor() {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const navigate = useNavigate();

  const seqQ = useQuery<Sequence>({
    queryKey: [`/sequences/${id}`],
    queryFn: () => api<Sequence>(`/sequences/${id}`),
  });
  const stepsQ = useQuery<Step[]>({
    queryKey: [`/sequences/${id}/steps`],
    queryFn: () => api<Step[]>(`/sequences/${id}/steps`),
  });

  const [draft, setDraft] = useState<Sequence | null>(null);
  useEffect(() => {
    if (seqQ.data) setDraft(seqQ.data);
  }, [seqQ.data]);

  const updateSeqMut = useMutation({
    mutationFn: (patch: Partial<Sequence>) =>
      api<Sequence>(`/sequences/${id}`, {
        method: "PATCH",
        body: JSON.stringify(patch),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [`/sequences/${id}`] });
      qc.invalidateQueries({ queryKey: ["/sequences"] });
    },
  });

  const deleteSeqMut = useMutation({
    mutationFn: () => api(`/sequences/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["/sequences"] });
      navigate("/sequences");
    },
  });

  const addStepMut = useMutation({
    mutationFn: () => {
      const nextPos = (stepsQ.data?.length ?? 0) + 1;
      return api<Step>(`/sequences/${id}/steps`, {
        method: "POST",
        body: JSON.stringify({
          position: nextPos,
          kind: "email",
          wait_days: nextPos === 1 ? 0 : 5,
          template_subject: "",
          template_body: "",
          reply_in_thread: nextPos > 1,
        }),
      });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: [`/sequences/${id}/steps`] }),
  });

  const updateStepMut = useMutation({
    mutationFn: ({ stepId, patch }: { stepId: string; patch: Partial<Step> }) =>
      api<Step>(`/sequences/${id}/steps/${stepId}`, {
        method: "PATCH",
        body: JSON.stringify(patch),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: [`/sequences/${id}/steps`] }),
  });

  const deleteStepMut = useMutation({
    mutationFn: (stepId: string) =>
      api(`/sequences/${id}/steps/${stepId}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: [`/sequences/${id}/steps`] }),
  });

  if (seqQ.isLoading || !draft) {
    return <div className="text-sm text-slate-500">Loading…</div>;
  }
  if (seqQ.isError) {
    return (
      <div className="text-sm text-red-700">
        Failed to load sequence. <Link to="/sequences" className="underline">Back</Link>
      </div>
    );
  }

  const steps = (stepsQ.data ?? []).slice().sort((a, b) => a.position - b.position);
  const dirty =
    JSON.stringify({
      name: draft.name,
      description: draft.description,
      status: draft.status,
      auto_enroll_bucket: draft.auto_enroll_bucket,
      from_name: draft.from_name,
      from_email: draft.from_email,
      reply_to_email: draft.reply_to_email,
      daily_limit: draft.daily_limit,
      cooldown_hours: draft.cooldown_hours,
      stop_on_reply: draft.stop_on_reply,
      send_window_json: draft.send_window_json,
    }) !==
    JSON.stringify({
      name: seqQ.data?.name,
      description: seqQ.data?.description,
      status: seqQ.data?.status,
      auto_enroll_bucket: seqQ.data?.auto_enroll_bucket,
      from_name: seqQ.data?.from_name,
      from_email: seqQ.data?.from_email,
      reply_to_email: seqQ.data?.reply_to_email,
      daily_limit: seqQ.data?.daily_limit,
      cooldown_hours: seqQ.data?.cooldown_hours,
      stop_on_reply: seqQ.data?.stop_on_reply,
      send_window_json: seqQ.data?.send_window_json,
    });

  return (
    <div>
      <div className="overflow-hidden rounded-lg bg-white ring-1 ring-slate-200">
        <div className="border-b border-slate-200 px-4 py-3">
          <Link to="/sequences" className="text-xs text-slate-500 hover:text-slate-900">
            ← All sequences
          </Link>
          <div className="mt-1 flex items-center gap-2">
            <BucketPill bucket={draft.auto_enroll_bucket} />
            <input
              value={draft.name}
              onChange={(e) => setDraft({ ...draft, name: e.target.value })}
              className="flex-1 rounded-md border border-transparent px-1 text-base font-medium focus:border-slate-300 focus:outline-none"
            />
            <div className="flex gap-2">
              {dirty && (
                <button
                  onClick={() =>
                    updateSeqMut.mutate({
                      name: draft.name,
                      description: draft.description,
                      status: draft.status,
                      auto_enroll_bucket: draft.auto_enroll_bucket,
                      from_name: draft.from_name,
                      from_email: draft.from_email,
                      reply_to_email: draft.reply_to_email,
                      daily_limit: draft.daily_limit,
                      cooldown_hours: draft.cooldown_hours,
                      stop_on_reply: draft.stop_on_reply,
                      send_window_json: draft.send_window_json,
                    })
                  }
                  className="rounded-md bg-brand-500 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-600"
                >
                  Save
                </button>
              )}
              <select
                value={draft.status}
                onChange={(e) => setDraft({ ...draft, status: e.target.value as Sequence["status"] })}
                className="rounded-md border border-slate-300 px-2 py-1.5 text-sm"
              >
                <option value="draft">Draft</option>
                <option value="active">Active</option>
                <option value="paused">Paused</option>
              </select>
              <button
                onClick={() => {
                  if (confirm("Delete sequence and all its enrollments?")) {
                    deleteSeqMut.mutate();
                  }
                }}
                className="rounded-md border border-red-300 px-2.5 py-1.5 text-sm text-red-700 hover:bg-red-50"
              >
                Delete
              </button>
            </div>
          </div>
          <input
            value={draft.description ?? ""}
            placeholder="Description (optional)"
            onChange={(e) => setDraft({ ...draft, description: e.target.value })}
            className="mt-1 w-full rounded-md border border-transparent px-1 text-xs text-slate-500 focus:border-slate-300 focus:outline-none"
          />
        </div>

        <div className="grid grid-cols-1 md:grid-cols-[1fr_300px]">
          {/* LEFT: Steps */}
          <div className="border-b border-slate-200 p-4 md:border-b-0 md:border-r">
            <div className="mb-2 text-[10px] uppercase tracking-wider text-slate-400">
              Steps
            </div>

            {stepsQ.isLoading && (
              <div className="text-sm text-slate-500">Loading steps…</div>
            )}

            {steps.length === 0 && !stepsQ.isLoading && (
              <div className="rounded-md border border-dashed border-slate-300 bg-slate-50 p-6 text-center text-xs text-slate-500">
                No steps yet. Click <span className="font-medium">Add step</span> to start.
              </div>
            )}

            <div className="space-y-2">
              {steps.map((s, i) => (
                <div key={s.id}>
                  {i > 0 && (
                    <div className="ml-3 flex items-center gap-1.5 py-1 text-[11px] text-slate-400">
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>
                      wait {s.wait_days} day{s.wait_days === 1 ? "" : "s"}
                    </div>
                  )}
                  <StepCard
                    step={s}
                    onPatch={(patch) => updateStepMut.mutate({ stepId: s.id, patch })}
                    onDelete={() => {
                      if (confirm(`Delete step ${s.position}?`)) deleteStepMut.mutate(s.id);
                    }}
                  />
                </div>
              ))}
            </div>

            <button
              onClick={() => addStepMut.mutate()}
              disabled={addStepMut.isPending}
              className="mt-3 inline-flex items-center gap-1.5 rounded-md border border-slate-300 px-3 py-1.5 text-xs hover:bg-slate-50 disabled:opacity-50"
            >
              + Add step
            </button>
          </div>

          {/* RIGHT: Settings panel */}
          <div className="bg-slate-50 p-4 space-y-3">
            <div className="text-[10px] uppercase tracking-wider text-slate-400">
              Settings
            </div>

            <div className="rounded-md border border-slate-200 bg-white p-3">
              <div className="text-[11px] text-slate-500">Auto-enroll</div>
              <select
                value={draft.auto_enroll_bucket ?? ""}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    auto_enroll_bucket: (e.target.value || null) as Sequence["auto_enroll_bucket"],
                  })
                }
                className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1 text-sm"
              >
                <option value="">Manual only</option>
                <option value="hot">Hot prospects (≥80)</option>
                <option value="warm">Warm prospects (50-79)</option>
                <option value="cold">Cold prospects (&lt;50)</option>
              </select>
              <div className="mt-1 text-[10px] text-slate-500">
                Score is frozen on enrollment.
              </div>
            </div>

            <div className="rounded-md border border-slate-200 bg-white p-3">
              <div className="text-[11px] text-slate-500">Sender</div>
              <input
                value={draft.from_name}
                onChange={(e) => setDraft({ ...draft, from_name: e.target.value })}
                placeholder="From name"
                className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1 text-sm"
              />
              <input
                value={draft.from_email}
                onChange={(e) => setDraft({ ...draft, from_email: e.target.value })}
                placeholder="from@your-domain.nl"
                className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1 text-sm"
              />
              <input
                value={draft.reply_to_email ?? ""}
                onChange={(e) => setDraft({ ...draft, reply_to_email: e.target.value || null })}
                placeholder="Reply-to (optional)"
                className="mt-1 w-full rounded-md border border-slate-300 px-2 py-1 text-sm"
              />
              <div className="mt-1 text-[10px] text-slate-500">
                Sending domain is set in Settings → Mailgun.
              </div>
            </div>

            <div className="rounded-md border border-slate-200 bg-white p-3">
              <div className="text-[11px] text-slate-500 mb-1">Send window</div>
              <div className="flex flex-wrap gap-1 mb-2">
                {DAY_LABELS.map((d, idx) => {
                  const on = draft.send_window_json.days.includes(idx);
                  return (
                    <button
                      key={idx}
                      onClick={() => {
                        const days = on
                          ? draft.send_window_json.days.filter((x) => x !== idx)
                          : [...draft.send_window_json.days, idx].sort();
                        setDraft({
                          ...draft,
                          send_window_json: { ...draft.send_window_json, days },
                        });
                      }}
                      className={`rounded px-2 py-0.5 text-[11px] ${
                        on
                          ? "bg-brand-500 text-white"
                          : "border border-slate-300 text-slate-600 hover:bg-slate-100"
                      }`}
                    >
                      {d}
                    </button>
                  );
                })}
              </div>
              {draft.send_window_json.slots.map((slot, idx) => (
                <div key={idx} className="mt-1 flex items-center gap-1">
                  <input
                    type="time"
                    value={slot.start}
                    onChange={(e) => {
                      const slots = [...draft.send_window_json.slots];
                      slots[idx] = { ...slots[idx], start: e.target.value };
                      setDraft({
                        ...draft,
                        send_window_json: { ...draft.send_window_json, slots },
                      });
                    }}
                    className="flex-1 rounded-md border border-slate-300 px-1 py-0.5 text-xs"
                  />
                  <span className="text-slate-400">–</span>
                  <input
                    type="time"
                    value={slot.end}
                    onChange={(e) => {
                      const slots = [...draft.send_window_json.slots];
                      slots[idx] = { ...slots[idx], end: e.target.value };
                      setDraft({
                        ...draft,
                        send_window_json: { ...draft.send_window_json, slots },
                      });
                    }}
                    className="flex-1 rounded-md border border-slate-300 px-1 py-0.5 text-xs"
                  />
                </div>
              ))}
            </div>

            <div className="rounded-md border border-slate-200 bg-white p-3">
              <div className="text-[11px] text-slate-500">Cooldown between actions</div>
              <div className="mt-1 flex items-center gap-1">
                <input
                  type="number"
                  min={0}
                  value={draft.cooldown_hours}
                  onChange={(e) => setDraft({ ...draft, cooldown_hours: Number(e.target.value) })}
                  className="w-16 rounded-md border border-slate-300 px-2 py-1 text-sm"
                />
                <span className="text-xs text-slate-500">hours</span>
              </div>
            </div>

            <div className="rounded-md border border-slate-200 bg-white p-3">
              <div className="text-[11px] text-slate-500">Daily limit</div>
              <div className="mt-1 flex items-center gap-1">
                <input
                  type="number"
                  min={1}
                  value={draft.daily_limit}
                  onChange={(e) => setDraft({ ...draft, daily_limit: Number(e.target.value) })}
                  className="w-20 rounded-md border border-slate-300 px-2 py-1 text-sm"
                />
                <span className="text-xs text-slate-500">mails / day</span>
              </div>
            </div>

            <div className="rounded-md border border-slate-200 bg-white p-3">
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={draft.stop_on_reply}
                  onChange={(e) => setDraft({ ...draft, stop_on_reply: e.target.checked })}
                />
                <span>Stop on reply</span>
              </label>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function StepCard({
  step,
  onPatch,
  onDelete,
}: {
  step: Step;
  onPatch: (patch: Partial<Step>) => void;
  onDelete: () => void;
}) {
  const [localBody, setLocalBody] = useState(step.template_body ?? "");
  const [localSubject, setLocalSubject] = useState(step.template_subject ?? "");
  useEffect(() => {
    setLocalBody(step.template_body ?? "");
    setLocalSubject(step.template_subject ?? "");
  }, [step.id]);

  const isEmail = step.kind === "email";

  return (
    <div className="rounded-md border border-slate-200 p-3">
      <div className="flex items-center gap-2 mb-2">
        <div className="flex h-6 w-6 items-center justify-center rounded-full bg-brand-50 text-xs font-medium text-brand-700">
          {step.position}
        </div>
        <select
          value={step.kind}
          onChange={(e) => onPatch({ kind: e.target.value as Step["kind"] })}
          className="rounded-md border border-slate-300 px-2 py-0.5 text-xs"
        >
          {Object.entries(STEP_KIND_LABELS).map(([v, lbl]) => (
            <option key={v} value={v}>{lbl}</option>
          ))}
        </select>
        <div className="text-xs text-slate-500">
          wait{" "}
          <input
            type="number"
            min={0}
            value={step.wait_days}
            onChange={(e) => onPatch({ wait_days: Number(e.target.value) })}
            className="w-12 rounded-md border border-slate-300 px-1 py-0.5 text-xs"
          />{" "}
          day{step.wait_days === 1 ? "" : "s"}
        </div>
        {isEmail && step.position > 1 && (
          <label className="flex items-center gap-1 text-[11px] text-slate-500">
            <input
              type="checkbox"
              checked={step.reply_in_thread}
              onChange={(e) => onPatch({ reply_in_thread: e.target.checked })}
            />
            same thread
          </label>
        )}
        <button
          onClick={onDelete}
          className="ml-auto rounded p-1 text-slate-400 hover:bg-red-50 hover:text-red-700"
          aria-label="Delete step"
        >
          ✕
        </button>
      </div>

      {isEmail ? (
        <>
          <input
            value={localSubject}
            onChange={(e) => setLocalSubject(e.target.value)}
            onBlur={() => {
              if (localSubject !== step.template_subject) onPatch({ template_subject: localSubject });
            }}
            placeholder="Subject"
            className="mb-1 w-full rounded-md border border-slate-200 bg-slate-50 px-2 py-1 text-sm focus:bg-white focus:border-slate-300"
          />
          <textarea
            value={localBody}
            onChange={(e) => setLocalBody(e.target.value)}
            onBlur={() => {
              if (localBody !== step.template_body) onPatch({ template_body: localBody });
            }}
            placeholder="Body — supports {{contact.first_name}}, {{company.name}}, {{company.mail_platform_label}}, {{company.industry}}"
            rows={6}
            className="w-full rounded-md border border-slate-200 bg-slate-50 px-2 py-1 text-sm font-mono focus:bg-white focus:border-slate-300"
          />
        </>
      ) : (
        <>
          <textarea
            value={localBody}
            onChange={(e) => setLocalBody(e.target.value)}
            onBlur={() => {
              if (localBody !== step.template_body) onPatch({ template_body: localBody });
            }}
            placeholder={
              step.kind === "linkedin_connect"
                ? "Connect message (≤ 200 chars)"
                : step.kind === "linkedin_dm"
                  ? "DM message"
                  : step.kind === "linkedin_like" || step.kind === "linkedin_visit"
                    ? "Optional note for this task"
                    : ""
            }
            rows={3}
            className="w-full rounded-md border border-slate-200 bg-slate-50 px-2 py-1 text-sm focus:bg-white focus:border-slate-300"
          />
          <div className="mt-1 text-[10px] text-slate-500">
            LinkedIn actions create tasks on the LinkedIn outreach board.
            Verzending niet automatisch.
          </div>
        </>
      )}
    </div>
  );
}
