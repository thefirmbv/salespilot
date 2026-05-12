import { ResourcePage, type Column } from "@/components/ResourcePage";
import { dash, fmtDate } from "@/lib/format";

type Company = {
  id: string;
  name: string;
  domain: string | null;
  industry: string | null;
  size: string | null;
  created_at: string;
};

const columns: Column<Company>[] = [
  { header: "Name", cell: (c) => c.name, className: "font-medium" },
  {
    header: "Domain",
    cell: (c) => dash(c.domain),
    className: "text-slate-700",
  },
  {
    header: "Industry",
    cell: (c) => dash(c.industry),
    className: "text-slate-700",
  },
  { header: "Size", cell: (c) => dash(c.size), className: "text-slate-700" },
  {
    header: "Created",
    cell: (c) => fmtDate(c.created_at),
    className: "text-slate-500",
  },
];

export function Companies() {
  return (
    <ResourcePage<Company>
      title="Companies"
      endpoint="/companies"
      newButtonLabel="+ New company"
      columns={columns}
      emptyMessage="No companies yet."
    />
  );
}
