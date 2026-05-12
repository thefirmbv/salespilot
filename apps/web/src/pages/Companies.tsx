import { ResourcePage, type Column } from "@/components/ResourcePage";
import type { FieldSpec } from "@/components/FormDialog";
import { dash, fmtDate } from "@/lib/format";

type Company = {
  id: string;
  name: string;
  domain: string | null;
  industry: string | null;
  size: string | null;
  description: string | null;
  created_at: string;
};

const columns: Column<Company>[] = [
  { header: "Name", sortKey: "name", cell: (c) => c.name, className: "font-medium" },
  { header: "Domain",
    sortKey: "domain", cell: (c) => dash(c.domain), className: "text-slate-700" },
  { header: "Industry",
    sortKey: "industry", cell: (c) => dash(c.industry), className: "text-slate-700" },
  { header: "Size", cell: (c) => dash(c.size), className: "text-slate-700" },
  {
    header: "Created",
    sortKey: "created_at",
    cell: (c) => fmtDate(c.created_at),
    className: "text-slate-500",
  },
];

const fields: FieldSpec[] = [
  { name: "name", label: "Company name", type: "text", required: true },
  { name: "domain", label: "Domain", type: "text", placeholder: "example.com" },
  { name: "industry", label: "Industry", type: "text" },
  {
    name: "size",
    label: "Size",
    type: "select",
    options: [
      { value: "1-10", label: "1-10" },
      { value: "11-50", label: "11-50" },
      { value: "51-200", label: "51-200" },
      { value: "201-1000", label: "201-1000" },
      { value: "1000+", label: "1000+" },
    ],
  },
  { name: "description", label: "Description", type: "textarea", rows: 3 },
];

export function Companies() {
  return (
    <ResourcePage<Company>
      title="Companies"
      endpoint="/companies"
      newButtonLabel="+ New company"
      columns={columns}
      emptyMessage="No companies yet."
      formFields={fields}
      rowLink={(c) => `/companies/${c.id}`}
      searchable
      searchPlaceholder="Search by name, domain, industry"
    />
  );
}
