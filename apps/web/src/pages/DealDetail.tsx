import { useState } from "react";
import { Link, useParams, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { FormDialog, type FieldSpec, type FormValues } from "@/components/FormDialog";
import { DetailHeader, FieldList } from "@/components/DetailHeader";
import { ActivityFeed } from "@/components/ActivityFeed";
import { dash, fmtDate, fmtMoney, StatusBadge } from "@/lib/format";
import { loadCompanyOptions, loadContactOptions } from "@/lib/options";

type Deal = {
  id: string;
  name: string;
  amount: number | null;
  currency: string;
  status: "open" | "won" | "lost";
  pipeline_id: string;
  stage_id: string;
  company_id: string | null;
  primary_contact_id: string | null;
  expected_close_date: string | null;
  closed_at: string | null;
  created_at: string;
};

type Stage = { id: string; name: string; position: number; is_won: boolean; is_lost: boolean };
type Company = { id: string; name: string };
type Contact = {
  id: string;
  first_name: string | null;
  last_name: string | null;
  email: string | null;
};

export function DealDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);

  const dealQ = useQuery<Deal>({
    queryKey: ["/deals", id],
    queryFn: () => api<Deal>(`/deals/${id}`),
    enabled: !!id,
  });

  const stagesQ = useQuery<Stage[]>({
    queryKey: ["stages", dealQ.data?.pipeline_id],
    queryFn: () =>
      api<Stage[]>(`/pipelines/${dealQ.data!.pipeline_id}/stages`),
    enabled: !!dealQ.data?.pipeline_id,
  });

  const companyQ = useQuery<Company | null>({
    queryKey: ["/companies", dealQ.data?.company_id],
    queryFn: () =>
      dealQ.data?.company_id
        ? api<Company>(`/companies/${dealQ.data.company_id}`)
        : Promise.resolve(null),
    enabled: !!dealQ.data?.company_id,
  });

  const contactQ = useQuery<Contact | null>({
    queryKey: ["/contacts", dealQ.data?.primary_contact_id],
    queryFn: () =>
      dealQ.data?.primary_contact_id
        ? api<Contact>(`/contacts/${dealQ.data.primary_contact_id}`)
        : Promise.resolve(null),
    enabled: !!dealQ.data?.primary_contact_id,
  });

  const updateMut = useMutation({
    mutationFn: (body: unknown) =>
      api<Deal>(`/deals/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["/deals", id] });
      qc.invalidateQueries({ queryKey: ["/deals"] });
    },
  });

  const deleteMut = useMutation({
    mutationFn: () => api<void>(`/deals/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["/deals"] }),
  });

  if (!id) return <div>Missing id</div>;
  if (dealQ.isLoading) return <div className="text-slate-500">Loading…</div>;
  if (!dealQ.data) return null;

  const d = dealQ.data;
  const currentStage = stagesQ.data?.find((s) => s.id === d.stage_id);

  const editFields: FieldSpec[] = [
    { name: "name", label: "Deal name", type: "text", required: true },
    { name: "amount", label: "Amount", type: "number", min: 0 },
    {
      name: "currency",
      label: "Currency",
      type: "select",
      required: true,
      options: [
        { value: "EUR", label: "EUR" },
        { value: "USD", label: "USD" },
        { value: "GBP", label: "GBP" },
      ],
    },
    {
      name: "stage_id",
      label: "Stage",
      type: "select",
      required: true,
      options: (stagesQ.data ?? []).map((s) => ({ value: s.id, label: s.name })),
    },
    {
      name: "status",
      label: "Status",
      type: "select",
      required: true,
      options: [
        { value: "open", label: "Open" },
        { value: "won", label: "Won" },
        { value: "lost", label: "Lost" },
      ],
    },
    {
      name: "company_id",
      label: "Company",
      type: "select-async",
      loadOptions: loadCompanyOptions,
    },
    {
      name: "primary_contact_id",
      label: "Primary contact",
      type: "select-async",
      loadOptions: loadContactOptions,
    },
    { name: "expected_close_date", label: "Expected close", type: "date" },
  ];

  return (
    <div className="space-y-6">
      <DetailHeader
        backTo="/deals"
        backLabel="All deals"
        title={d.name}
        subtitle={fmtMoney(d.amount, d.currency)}
        onEdit={() => setEditing(true)}
        onDelete={async () => {
          await deleteMut.mutateAsync();
          navigate("/deals");
        }}
      />

      {/* Stage strip — quick stage changer */}
      {stagesQ.data && stagesQ.data.length > 0 && (
        <div className="overflow-hidden rounded-lg ring-1 ring-slate-200 bg-white">
          <div className="flex">
            {stagesQ.data.map((s) => {
              const isActive = s.id === d.stage_id;
              const isPast = currentStage && s.position < currentStage.position;
              return (
                <button
                  key={s.id}
                  onClick={() => updateMut.mutate({ stage_id: s.id })}
                  className={`flex-1 px-3 py-3 text-sm font-medium transition-colors ${
                    isActive
                      ? "bg-slate-900 text-white"
                      : isPast
                        ? "bg-slate-100 text-slate-600 hover:bg-slate-200"
                        : "bg-white text-slate-500 hover:bg-slate-50"
                  } ${
                    s.position !== 0 ? "border-l border-slate-200" : ""
                  }`}
                >
                  {s.name}
                </button>
              );
            })}
          </div>
        </div>
      )}

      <div className="rounded-lg ring-1 ring-slate-200 bg-white p-5">
        <FieldList
          fields={[
            ["Amount", fmtMoney(d.amount, d.currency)],
            ["Status", <StatusBadge status={d.status} />],
            ["Stage", dash(currentStage?.name)],
            ["Expected close", fmtDate(d.expected_close_date)],
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
            [
              "Primary contact",
              contactQ.data ? (
                <Link
                  to={`/contacts/${contactQ.data.id}`}
                  className="text-slate-700 hover:underline"
                >
                  {[contactQ.data.first_name, contactQ.data.last_name]
                    .filter(Boolean)
                    .join(" ") || contactQ.data.email || "—"}
                </Link>
              ) : (
                "—"
              ),
            ],
            ["Closed", d.closed_at ? fmtDate(d.closed_at) : "—"],
          ]}
        />
      </div>

      <ActivityFeed targetType="deal" targetId={d.id} />

      {editing && (
        <FormDialog
          open
          onClose={() => setEditing(false)}
          title={`Edit ${d.name}`}
          fields={editFields}
          initialValues={{
            name: d.name,
            amount: d.amount,
            currency: d.currency,
            stage_id: d.stage_id,
            status: d.status,
            company_id: d.company_id,
            primary_contact_id: d.primary_contact_id,
            expected_close_date: d.expected_close_date?.slice(0, 10),
          }}
          submitLabel="Save changes"
          onSubmit={async (values: FormValues) => {
            const body: Record<string, unknown> = { ...values };
            if (
              typeof body.expected_close_date === "string" &&
              body.expected_close_date
            ) {
              body.expected_close_date = `${body.expected_close_date}T00:00:00Z`;
            }
            await updateMut.mutateAsync(body);
          }}
        />
      )}
    </div>
  );
}
