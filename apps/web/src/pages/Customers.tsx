import { ResourcePage, type Column } from "@/components/ResourcePage";
import { dash, fmtDate, SourceBadge } from "@/lib/format";

type Company = {
  id: string;
  name: string;
  domain: string | null;
  industry: string | null;
  source: string;
  halopsa_id: number | null;
  halopsa_synced_at: string | null;
  city: string | null;
  employees: number | null;
  created_at: string;
};

const columns: Column<Company>[] = [
  { header: "Name", sortKey: "name", cell: (c) => c.name, className: "font-medium" },
  {
    header: "Source",
    cell: (c) => <SourceBadge source={c.source} />,
  },
  {
    header: "HaloPSA id",
    cell: (c) =>
      c.halopsa_id ? (
        <span className="font-mono text-xs text-slate-600">{c.halopsa_id}</span>
      ) : (
        "—"
      ),
  },
  {
    header: "Domain",
    sortKey: "domain",
    cell: (c) => dash(c.domain),
    className: "text-slate-700",
  },
  {
    header: "Synced",
    cell: (c) => fmtDate(c.halopsa_synced_at),
    className: "text-slate-500",
  },
];

/**
 * Customers = companies that originated in or have been pushed to HaloPSA.
 * Read-only edits for source=halopsa; halopsa_pushed remains editable
 * (already handled by the detail page).
 */
export function Customers() {
  return (
    <ResourcePage<Company>
      title="Customers"
      endpoint="/companies"
      newButtonLabel="+ New customer"
      columns={columns}
      emptyMessage="No customers yet. Connect HaloPSA and run a sync from Settings → Integrations."
      rowLink={(c) => `/companies/${c.id}`}
      searchable
      searchPlaceholder="Search by name, domain, industry"
      baseQuery={{ source__in: "halopsa,halopsa_pushed" }}
      filters={[
        {
          param: "source",
          label: "Source",
          options: [
            { value: "halopsa", label: "Synced from HaloPSA" },
            { value: "halopsa_pushed", label: "Pushed to HaloPSA" },
          ],
        },
      ]}
      // Limit to HaloPSA-known companies via the new __in filter.
      // We pass it via the URL/the filters props above? No — the page-level
      // filter is opt-in by the user. We need a baseline filter that's
      // always applied. Easiest: encode source__in on the endpoint string.
    />
  );
}
