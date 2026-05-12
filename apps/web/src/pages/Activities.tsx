import type { Column } from "@/components/ResourcePage";
import { ResourcePage } from "@/components/ResourcePage";
import type { FieldSpec, FormValues } from "@/components/FormDialog";
import { TypeBadge, dash, fmtDateTime } from "@/lib/format";
import { api } from "@/lib/api";

type Activity = {
  id: string;
  type: "note" | "call" | "email" | "meeting" | "task";
  target_type: "contact" | "company" | "deal";
  target_id: string;
  subject: string | null;
  body: string | null;
  due_at: string | null;
  completed_at: string | null;
  created_at: string;
};

const columns: Column<Activity>[] = [
  { header: "Type", cell: (a) => <TypeBadge type={a.type} /> },
  { header: "Subject", cell: (a) => dash(a.subject), className: "font-medium" },
  {
    header: "On",
    cell: (a) => (
      <span className="text-slate-600">
        {a.target_type}{" "}
        <span className="text-slate-400">·</span>{" "}
        <span className="font-mono text-xs">{a.target_id.slice(0, 8)}</span>
      </span>
    ),
  },
  { header: "Due", cell: (a) => fmtDateTime(a.due_at), className: "text-slate-700" },
  {
    header: "Done",
    cell: (a) =>
      a.completed_at ? (
        <span className="text-green-700">{fmtDateTime(a.completed_at)}</span>
      ) : (
        <span className="text-slate-400">—</span>
      ),
  },
];

// One "target" loader returns all 3 kinds, tagged with their type.
async function loadAllTargetOptions(): Promise<{ value: string; label: string }[]> {
  type T = { items: Array<{ id: string; name?: string; first_name?: string | null; last_name?: string | null; email?: string | null }> };
  const [contacts, companies, deals] = await Promise.all([
    api<T>("/contacts?limit=200"),
    api<T>("/companies?limit=200"),
    api<T>("/deals?limit=200"),
  ]);
  const out: { value: string; label: string }[] = [];
  for (const c of contacts.items) {
    const name =
      [c.first_name, c.last_name].filter(Boolean).join(" ") || c.email || c.id;
    out.push({ value: `contact:${c.id}`, label: `Contact · ${name}` });
  }
  for (const c of companies.items) {
    out.push({ value: `company:${c.id}`, label: `Company · ${c.name ?? c.id}` });
  }
  for (const d of deals.items) {
    out.push({ value: `deal:${d.id}`, label: `Deal · ${d.name ?? d.id}` });
  }
  return out;
}

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
  {
    name: "target",
    label: "Linked to",
    type: "select-async",
    required: true,
    loadOptions: loadAllTargetOptions,
  },
  { name: "subject", label: "Subject", type: "text" },
  { name: "body", label: "Notes", type: "textarea", rows: 4 },
  { name: "due_at", label: "Due", type: "datetime" },
];

export function Activities() {
  return (
    <ResourcePage<Activity>
      title="Activities"
      endpoint="/activities"
      newButtonLabel="+ New activity"
      columns={columns}
      emptyMessage="No activities yet."
      formFields={fields}
      rowToFormValues={(a) => ({
        type: a.type,
        target: `${a.target_type}:${a.target_id}`,
        subject: a.subject,
        body: a.body,
        due_at: a.due_at?.slice(0, 16),
      })}
      formValuesToBody={(v: FormValues) => {
        // Split "contact:UUID" into target_type + target_id.
        const target = (v.target as string | undefined) ?? "";
        const [target_type, target_id] = target.split(":");
        const body: Record<string, unknown> = {
          type: v.type,
          target_type,
          target_id,
          subject: v.subject,
          body: v.body,
        };
        if (typeof v.due_at === "string" && v.due_at) {
          body.due_at = new Date(v.due_at).toISOString();
        }
        return body;
      }}
      rowLabel={(a) => a.subject ?? `${a.type} on ${a.target_type}`}
    />
  );
}
