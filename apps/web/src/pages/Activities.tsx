import { ResourcePage, type Column } from "@/components/ResourcePage";
import { TypeBadge, dash, fmtDateTime } from "@/lib/format";

type Activity = {
  id: string;
  type: "note" | "call" | "email" | "meeting" | "task" | string;
  target_type: "contact" | "company" | "deal" | string;
  target_id: string;
  subject: string | null;
  due_at: string | null;
  completed_at: string | null;
  created_at: string;
};

const columns: Column<Activity>[] = [
  { header: "Type", cell: (a) => <TypeBadge type={a.type} /> },
  {
    header: "Subject",
    cell: (a) => dash(a.subject),
    className: "font-medium",
  },
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
  {
    header: "Due",
    cell: (a) => fmtDateTime(a.due_at),
    className: "text-slate-700",
  },
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

export function Activities() {
  return (
    <ResourcePage<Activity>
      title="Activities"
      endpoint="/activities"
      newButtonLabel="+ New activity"
      columns={columns}
      emptyMessage="No activities yet. Log a call, note, or task from a contact or deal."
    />
  );
}
