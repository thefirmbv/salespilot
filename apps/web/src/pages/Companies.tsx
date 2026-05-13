import { useQuery } from "@tanstack/react-query";
import { ResourcePage, type Column } from "@/components/ResourcePage";
import type { FieldSpec } from "@/components/FormDialog";
import { api } from "@/lib/api";
import { dash, fmtDate, SourceBadge } from "@/lib/format";

type Company = {
  id: string;
  name: string;
  domain: string | null;
  industry: string | null;
  size: string | null;
  description: string | null;
  source: string;
  halopsa_id: number | null;
  created_at: string;
};

type CommsBadge = {
  company_id: string;
  last_outbound_at: string | null;
  last_open_at: string | null;
  sent_count: number;
  open_count: number;
  click_count: number;
  bounced_count: number;
};

function CommsBadgeCell({ companyId, badges }: { companyId: string; badges: Record<string, CommsBadge> | undefined }) {
  if (!badges) return <span className="text-slate-400">—</span>;
  const b = badges[companyId];
  if (!b || b.sent_count === 0) return <span className="text-slate-400 text-xs">geen</span>;

  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="inline-flex items-center gap-1 rounded bg-slate-100 px-1.5 py-0.5 text-slate-700" title="Verstuurd">
        ✉ {b.sent_count}
      </span>
      {b.open_count > 0 && (
        <span className="inline-flex items-center gap-1 rounded bg-emerald-50 px-1.5 py-0.5 text-emerald-800"
          title={b.last_open_at ? `Laatst geopend ${new Date(b.last_open_at).toLocaleDateString("nl-NL")}` : "Geopend"}>
          👁 {b.open_count}
        </span>
      )}
      {b.click_count > 0 && (
        <span className="inline-flex items-center gap-1 rounded bg-emerald-50 px-1.5 py-0.5 text-emerald-800" title="Geklikt">
          ✋ {b.click_count}
        </span>
      )}
      {b.bounced_count > 0 && (
        <span className="inline-flex items-center gap-1 rounded bg-red-50 px-1.5 py-0.5 text-red-800" title="Bounced">
          ⚠ {b.bounced_count}
        </span>
      )}
    </div>
  );
}

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
  const badgesQ = useQuery<CommsBadge[]>({
    queryKey: ["/companies/communications-summary"],
    queryFn: () => api<CommsBadge[]>("/companies/communications-summary"),
  });

  const badgeMap: Record<string, CommsBadge> = {};
  for (const b of badgesQ.data ?? []) {
    badgeMap[b.company_id] = b;
  }

  const columns: Column<Company>[] = [
    { header: "Name", sortKey: "name", cell: (c) => c.name, className: "font-medium" },
    { header: "Source", cell: (c) => <SourceBadge source={c.source} /> },
    { header: "Domain", sortKey: "domain", cell: (c) => dash(c.domain), className: "text-slate-700" },
    {
      header: "Mailings",
      cell: (c) => <CommsBadgeCell companyId={c.id} badges={badgeMap} />,
    },
    { header: "Industry", sortKey: "industry", cell: (c) => dash(c.industry), className: "text-slate-700" },
    { header: "Size", cell: (c) => dash(c.size), className: "text-slate-700" },
    { header: "Created", sortKey: "created_at", cell: (c) => fmtDate(c.created_at), className: "text-slate-500" },
  ];

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
