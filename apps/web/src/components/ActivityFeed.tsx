/** Activity feed for a specific target (contact / company / deal).
 *
 *  Used by all three detail pages. Shows the chronological list plus a
 *  "+ Log activity" button that opens FormDialog with the target prefilled.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { FormDialog, type FieldSpec, type FormValues } from "./FormDialog";
import { TypeBadge, fmtDateTime, dash } from "@/lib/format";

type Activity = {
  id: string;
  type: string;
  target_type: string;
  target_id: string;
  subject: string | null;
  body: string | null;
  due_at: string | null;
  completed_at: string | null;
  created_at: string;
};

type Page<T> = { items: T[]; total: number };

type Props = {
  targetType: "contact" | "company" | "deal";
  targetId: string;
};

const fields: FieldSpec[] = [
  {
    name: "type",
    label: "Type",
    type: "select",
    required: true,
    options: [
      { value: "note", label: "Note" },
      { value: "call", label: "Call" },
      { value: "email", label: "Email" },
      { value: "meeting", label: "Meeting" },
      { value: "task", label: "Task" },
    ],
  },
  { name: "subject", label: "Subject", type: "text" },
  { name: "body", label: "Notes", type: "textarea", rows: 4 },
  { name: "due_at", label: "Due", type: "datetime" },
];

export function ActivityFeed({ targetType, targetId }: Props) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);

  const queryKey = ["/activities", { target_type: targetType, target_id: targetId }];
  const { data, isLoading } = useQuery<Page<Activity>>({
    queryKey,
    queryFn: () =>
      api<Page<Activity>>(
        `/activities?target_type=${targetType}&target_id=${targetId}&limit=200`,
      ),
  });

  const createMut = useMutation({
    mutationFn: (body: unknown) =>
      api<Activity>("/activities", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: () => qc.invalidateQueries({ queryKey }),
  });

  const toggleDone = useMutation({
    mutationFn: ({ id, completed }: { id: string; completed: boolean }) =>
      api<Activity>(`/activities/${id}`, {
        method: "PATCH",
        body: JSON.stringify({
          completed_at: completed ? new Date().toISOString() : null,
        }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey }),
  });

  async function handleSubmit(values: FormValues): Promise<void> {
    const body: Record<string, unknown> = {
      type: values.type,
      target_type: targetType,
      target_id: targetId,
      subject: values.subject,
      body: values.body,
    };
    if (typeof values.due_at === "string" && values.due_at) {
      body.due_at = new Date(values.due_at).toISOString();
    }
    await createMut.mutateAsync(body);
    setOpen(false);
  }

  return (
    <div className="rounded-lg ring-1 ring-slate-200 bg-white">
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-600">
          Activity
        </h2>
        <button
          onClick={() => setOpen(true)}
          className="rounded-md bg-slate-900 px-2.5 py-1 text-xs font-medium text-white hover:bg-slate-800"
        >
          + Log activity
        </button>
      </div>

      {isLoading && <div className="p-4 text-sm text-slate-500">Loading…</div>}

      {data && data.items.length === 0 && (
        <div className="p-6 text-center text-sm text-slate-500">
          No activity yet. Log a note, call, or task.
        </div>
      )}

      {data && data.items.length > 0 && (
        <ul className="divide-y divide-slate-100">
          {data.items.map((a) => (
            <li key={a.id} className="px-4 py-3">
              <div className="flex items-start gap-3">
                <input
                  type="checkbox"
                  checked={!!a.completed_at}
                  onChange={(e) =>
                    toggleDone.mutate({ id: a.id, completed: e.target.checked })
                  }
                  className="mt-1"
                  aria-label="Toggle completed"
                />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <TypeBadge type={a.type} />
                    <span
                      className={`text-sm font-medium ${
                        a.completed_at ? "text-slate-400 line-through" : "text-slate-900"
                      }`}
                    >
                      {dash(a.subject)}
                    </span>
                  </div>
                  {a.body && (
                    <p className="mt-1 whitespace-pre-wrap text-sm text-slate-600">
                      {a.body}
                    </p>
                  )}
                  <div className="mt-1 flex gap-3 text-xs text-slate-500">
                    <span>Created {fmtDateTime(a.created_at)}</span>
                    {a.due_at && <span>Due {fmtDateTime(a.due_at)}</span>}
                    {a.completed_at && (
                      <span className="text-green-700">
                        Done {fmtDateTime(a.completed_at)}
                      </span>
                    )}
                  </div>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}

      {open && (
        <FormDialog
          open
          onClose={() => setOpen(false)}
          title="Log activity"
          fields={fields}
          onSubmit={handleSubmit}
          submitLabel="Log"
        />
      )}
    </div>
  );
}
