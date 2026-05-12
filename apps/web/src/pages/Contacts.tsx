import { ResourcePage, type Column } from "@/components/ResourcePage";
import { dash, fmtDate } from "@/lib/format";

type Contact = {
  id: string;
  email: string | null;
  first_name: string | null;
  last_name: string | null;
  job_title: string | null;
  created_at: string;
};

const columns: Column<Contact>[] = [
  {
    header: "Name",
    cell: (c) =>
      [c.first_name, c.last_name].filter(Boolean).join(" ") || "—",
    className: "font-medium",
  },
  { header: "Email", cell: (c) => dash(c.email), className: "text-slate-700" },
  { header: "Job title", cell: (c) => dash(c.job_title), className: "text-slate-700" },
  {
    header: "Created",
    cell: (c) => fmtDate(c.created_at),
    className: "text-slate-500",
  },
];

export function Contacts() {
  return (
    <ResourcePage<Contact>
      title="Contacts"
      endpoint="/contacts"
      newButtonLabel="+ New contact"
      columns={columns}
      emptyMessage="No contacts yet. Create your first one to get started."
    />
  );
}
