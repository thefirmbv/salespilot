import { useState } from "react";
import { Link, useParams, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { FormDialog, type FieldSpec, type FormValues } from "@/components/FormDialog";
import { DetailHeader, FieldList } from "@/components/DetailHeader";
import { ActivityFeed } from "@/components/ActivityFeed";
import { dash, fmtMoney, StatusBadge } from "@/lib/format";

type Company = {
  id: string;
  name: string;
  domain: string | null;
  industry: string | null;
  size: string | null;
  description: string | null;
  created_at: string;
};

type Contact = {
  id: string;
  first_name: string | null;
  last_name: string | null;
  email: string | null;
  job_title: string | null;
};

type Deal = {
  id: string;
  name: string;
  amount: number | null;
  currency: string;
  status: "open" | "won" | "lost";
};

type Page<T> = { items: T[]; total: number };

const editFields: FieldSpec[] = [
  { name: "name", label: "Company name", type: "text", required: true },
  { name: "domain", label: "Domain", type: "text" },
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

export function CompanyDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);

  const companyQ = useQuery<Company>({
    queryKey: ["/companies", id],
    queryFn: () => api<Company>(`/companies/${id}`),
    enabled: !!id,
  });

  const contactsQ = useQuery<Page<Contact>>({
    queryKey: ["/contacts", { company_id: id }],
    queryFn: () => api<Page<Contact>>(`/contacts?company_id=${id}&limit=200`),
    enabled: !!id,
  });

  const dealsQ = useQuery<Page<Deal>>({
    queryKey: ["/deals", { company_id: id }],
    queryFn: () => api<Page<Deal>>(`/deals?company_id=${id}&limit=200`),
    enabled: !!id,
  });

  const updateMut = useMutation({
    mutationFn: (body: unknown) =>
      api<Company>(`/companies/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["/companies", id] });
      qc.invalidateQueries({ queryKey: ["/companies"] });
    },
  });

  const deleteMut = useMutation({
    mutationFn: () => api<void>(`/companies/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["/companies"] }),
  });

  if (!id) return <div>Missing id</div>;
  if (companyQ.isLoading) return <div className="text-slate-500">Loading…</div>;
  if (!companyQ.data) return null;

  const c = companyQ.data;

  return (
    <div className="space-y-6">
      <DetailHeader
        backTo="/companies"
        backLabel="All companies"
        title={c.name}
        subtitle={c.industry ?? undefined}
        onEdit={() => setEditing(true)}
        onDelete={async () => {
          await deleteMut.mutateAsync();
          navigate("/companies");
        }}
      />

      <div className="rounded-lg ring-1 ring-slate-200 bg-white p-5">
        <FieldList
          fields={[
            ["Domain", dash(c.domain)],
            ["Industry", dash(c.industry)],
            ["Size", dash(c.size)],
            ["Description", c.description ? c.description : "—"],
          ]}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-[2fr_1fr]">
        <div className="space-y-6">
          <ActivityFeed targetType="company" targetId={c.id} />

          <div className="rounded-lg ring-1 ring-slate-200 bg-white">
            <div className="border-b border-slate-200 px-4 py-3">
              <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-600">
                Deals
              </h2>
            </div>
            {dealsQ.data && dealsQ.data.items.length === 0 && (
              <div className="p-6 text-center text-sm text-slate-500">
                No deals yet.
              </div>
            )}
            {dealsQ.data && dealsQ.data.items.length > 0 && (
              <ul className="divide-y divide-slate-100">
                {dealsQ.data.items.map((d) => (
                  <li key={d.id}>
                    <Link
                      to={`/deals/${d.id}`}
                      className="flex items-center justify-between px-4 py-3 hover:bg-slate-50"
                    >
                      <span className="font-medium">{d.name}</span>
                      <span className="flex items-center gap-2 text-sm">
                        <span className="tabular-nums text-slate-700">
                          {fmtMoney(d.amount, d.currency)}
                        </span>
                        <StatusBadge status={d.status} />
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>

        <div className="rounded-lg ring-1 ring-slate-200 bg-white">
          <div className="border-b border-slate-200 px-4 py-3">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-600">
              People
            </h2>
          </div>
          {contactsQ.data && contactsQ.data.items.length === 0 && (
            <div className="p-6 text-center text-sm text-slate-500">
              No contacts at this company.
            </div>
          )}
          {contactsQ.data && contactsQ.data.items.length > 0 && (
            <ul className="divide-y divide-slate-100">
              {contactsQ.data.items.map((p) => (
                <li key={p.id}>
                  <Link
                    to={`/contacts/${p.id}`}
                    className="block px-4 py-3 hover:bg-slate-50"
                  >
                    <div className="font-medium">
                      {[p.first_name, p.last_name].filter(Boolean).join(" ") ||
                        p.email ||
                        "—"}
                    </div>
                    <div className="text-xs text-slate-500">
                      {dash(p.job_title)}
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      {editing && (
        <FormDialog
          open
          onClose={() => setEditing(false)}
          title={`Edit ${c.name}`}
          fields={editFields}
          initialValues={{
            name: c.name,
            domain: c.domain,
            industry: c.industry,
            size: c.size,
            description: c.description,
          }}
          submitLabel="Save changes"
          onSubmit={async (values: FormValues) => {
            await updateMut.mutateAsync(values);
          }}
        />
      )}
    </div>
  );
}
