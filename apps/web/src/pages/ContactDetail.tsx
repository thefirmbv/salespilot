import { useState } from "react";
import { Link, useParams, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { FormDialog, type FieldSpec, type FormValues } from "@/components/FormDialog";
import { DetailHeader, FieldList } from "@/components/DetailHeader";
import { ActivityFeed } from "@/components/ActivityFeed";
import { dash, fmtMoney, StatusBadge } from "@/lib/format";
import { loadCompanyOptions } from "@/lib/options";

type Contact = {
  id: string;
  email: string | null;
  first_name: string | null;
  last_name: string | null;
  phone: string | null;
  job_title: string | null;
  company_id: string | null;
  owner_id: string | null;
  created_at: string;
};

type Company = { id: string; name: string };

type Deal = {
  id: string;
  name: string;
  amount: number | null;
  currency: string;
  status: "open" | "won" | "lost";
};

type Page<T> = { items: T[]; total: number };

const editFields: FieldSpec[] = [
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

export function ContactDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);

  const contactQ = useQuery<Contact>({
    queryKey: ["/contacts", id],
    queryFn: () => api<Contact>(`/contacts/${id}`),
    enabled: !!id,
  });

  const companyQ = useQuery<Company | null>({
    queryKey: ["/companies", contactQ.data?.company_id],
    queryFn: () =>
      contactQ.data?.company_id
        ? api<Company>(`/companies/${contactQ.data.company_id}`)
        : Promise.resolve(null),
    enabled: !!contactQ.data?.company_id,
  });

  const dealsQ = useQuery<Page<Deal>>({
    queryKey: ["/deals", { primary_contact_id: id }],
    queryFn: () =>
      api<Page<Deal>>(`/deals?primary_contact_id=${id}&limit=100`),
    enabled: !!id,
  });

  const updateMut = useMutation({
    mutationFn: (body: unknown) =>
      api<Contact>(`/contacts/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["/contacts", id] });
      qc.invalidateQueries({ queryKey: ["/contacts"] });
    },
  });

  const deleteMut = useMutation({
    mutationFn: () => api<void>(`/contacts/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["/contacts"] }),
  });

  if (!id) return <div>Missing id</div>;
  if (contactQ.isLoading) return <div className="text-slate-500">Loading…</div>;
  if (contactQ.error)
    return (
      <div className="text-red-600">
        {contactQ.error instanceof Error ? contactQ.error.message : "failed"}
      </div>
    );
  if (!contactQ.data) return null;

  const c = contactQ.data;
  const name =
    [c.first_name, c.last_name].filter(Boolean).join(" ") || c.email || "Contact";

  return (
    <div className="space-y-6">
      <DetailHeader
        backTo="/contacts"
        backLabel="All contacts"
        title={name}
        subtitle={c.job_title ?? undefined}
        onEdit={() => setEditing(true)}
        onDelete={async () => {
          await deleteMut.mutateAsync();
          navigate("/contacts");
        }}
        deleteConfirmLabel={name}
      />

      <div className="rounded-lg ring-1 ring-slate-200 bg-white p-5">
        <FieldList
          fields={[
            ["Email", dash(c.email)],
            ["Phone", dash(c.phone)],
            ["Job title", dash(c.job_title)],
            [
              "Company",
              companyQ.data ? (
                <Link
                  to={`/companies/${companyQ.data.id}`}
                  className="text-slate-700 hover:underline"
                >
                  {companyQ.data.name}
                </Link>
              ) : (
                "—"
              ),
            ],
          ]}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-[2fr_1fr]">
        <ActivityFeed targetType="contact" targetId={c.id} />

        <div className="rounded-lg ring-1 ring-slate-200 bg-white">
          <div className="border-b border-slate-200 px-4 py-3">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-600">
              Deals
            </h2>
          </div>
          {dealsQ.isLoading && (
            <div className="p-4 text-sm text-slate-500">Loading…</div>
          )}
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

      {editing && (
        <FormDialog
          open
          onClose={() => setEditing(false)}
          title={`Edit ${name}`}
          fields={editFields}
          initialValues={{
            first_name: c.first_name,
            last_name: c.last_name,
            email: c.email,
            phone: c.phone,
            job_title: c.job_title,
            company_id: c.company_id,
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
