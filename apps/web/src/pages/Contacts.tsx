import { ResourcePage, type Column } from "@/components/ResourcePage";
import type { FieldSpec } from "@/components/FormDialog";
import { dash, fmtDate } from "@/lib/format";
import { loadCompanyOptions } from "@/lib/options";

type Contact = {
  id: string;
  email: string | null;
  first_name: string | null;
  last_name: string | null;
  job_title: string | null;
  phone: string | null;
  company_id: string | null;
  created_at: string;
};

const columns: Column<Contact>[] = [
  {
    header: "Name",
    cell: (c) => [c.first_name, c.last_name].filter(Boolean).join(" ") || "—",
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

const fields: FieldSpec[] = [
  { name: "first_name", label: "First name", type: "text" },
  { name: "last_name", label: "Last name", type: "text" },
  { name: "email", label: "Email", type: "email" },
  { name: "phone", label: "Phone", type: "tel" },
  { name: "job_title", label: "Job title", type: "text" },
  {
    name: "company_id",
    label: "Company",
    type: "select-async",
    loadOptions: loadCompanyOptions,
  },
];

export function Contacts() {
  return (
    <ResourcePage<Contact>
      title="Contacts"
      endpoint="/contacts"
      newButtonLabel="+ New contact"
      columns={columns}
      emptyMessage="No contacts yet. Click + New contact to start."
      formFields={fields}
      rowLink={(c) => `/contacts/${c.id}`}
      searchable
      searchPlaceholder="Search by name, email, phone, job title"
      rowLabel={(c) =>
        [c.first_name, c.last_name].filter(Boolean).join(" ") || c.email || c.id
      }
    />
  );
}
