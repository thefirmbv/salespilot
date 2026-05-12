import { ResourcePage, type Column } from "@/components/ResourcePage";
import { StatusBadge, fmtDate, fmtMoney } from "@/lib/format";

type Deal = {
  id: string;
  name: string;
  amount: number | null;
  currency: string;
  status: "open" | "won" | "lost";
  expected_close_date: string | null;
  closed_at: string | null;
  created_at: string;
};

const columns: Column<Deal>[] = [
  { header: "Name", cell: (d) => d.name, className: "font-medium" },
  {
    header: "Amount",
    cell: (d) => fmtMoney(d.amount, d.currency),
    className: "text-slate-700 tabular-nums",
  },
  { header: "Status", cell: (d) => <StatusBadge status={d.status} /> },
  {
    header: "Expected close",
    cell: (d) => fmtDate(d.expected_close_date),
    className: "text-slate-700",
  },
  {
    header: "Created",
    cell: (d) => fmtDate(d.created_at),
    className: "text-slate-500",
  },
];

export function Deals() {
  return (
    <ResourcePage<Deal>
      title="Deals"
      endpoint="/deals"
      newButtonLabel="+ New deal"
      columns={columns}
      emptyMessage="No deals yet. Create a pipeline and a deal to start tracking."
    />
  );
}
