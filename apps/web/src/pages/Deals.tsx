import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { FormDialog, type FieldSpec, type FormValues } from "@/components/FormDialog";
import { StatusBadge, fmtDate, fmtMoney } from "@/lib/format";
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
type Pipeline = { id: string; name: string; is_default: boolean };
type Stage = { id: string; name: string; position: number };
type Page<T> = { items: T[]; total: number; limit: number; offset: number };

/**
 * Deals is bespoke because the form depends on pipeline+stage selection
 * loaded from a separate endpoint. Other resources can use ResourcePage.
 */
export function Deals() {
  const qc = useQueryClient();
  const [dialog, setDialog] = useState<
    | { mode: "create" }
    | { mode: "edit"; row: Deal }
    | null
  >(null);

  const dealsQ = useQuery<Page<Deal>>({
    queryKey: ["/deals"],
    queryFn: () => api<Page<Deal>>("/deals?limit=100"),
  });

  const pipelinesQ = useQuery<Pipeline[]>({
    queryKey: ["pipelines"],
    queryFn: () => api<Pipeline[]>("/pipelines"),
  });
  const defaultPipeline =
    pipelinesQ.data?.find((p) => p.is_default) ?? pipelinesQ.data?.[0];
  const activePipelineId =
    dialog?.mode === "edit" ? dialog.row.pipeline_id : defaultPipeline?.id;

  const stagesQ = useQuery<Stage[]>({
    queryKey: ["stages", activePipelineId],
    queryFn: () => api<Stage[]>(`/pipelines/${activePipelineId}/stages`),
    enabled: !!activePipelineId,
  });

  const createMut = useMutation({
    mutationFn: (body: unknown) =>
      api<Deal>("/deals", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["/deals"] }),
  });
  const updateMut = useMutation({
    mutationFn: ({ id, body }: { id: string; body: unknown }) =>
      api<Deal>(`/deals/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["/deals"] }),
  });
  const deleteMut = useMutation({
    mutationFn: (id: string) => api<void>(`/deals/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["/deals"] }),
  });

  const fields: FieldSpec[] = [
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

  async function handleSubmit(values: FormValues): Promise<void> {
    const body: Record<string, unknown> = { ...values };
    if (typeof body.expected_close_date === "string" && body.expected_close_date) {
      body.expected_close_date = `${body.expected_close_date}T00:00:00Z`;
    }
    if (dialog?.mode === "edit") {
      await updateMut.mutateAsync({ id: dialog.row.id, body });
    } else {
      body.pipeline_id = defaultPipeline?.id;
      await createMut.mutateAsync(body);
    }
    setDialog(null);
  }

  return (
    <div>
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Deals</h1>
        <button
          onClick={() => setDialog({ mode: "create" })}
          disabled={!defaultPipeline}
          className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
        >
          + New deal
        </button>
      </div>

      <div className="mt-6 overflow-hidden rounded-lg ring-1 ring-slate-200 bg-white">
        {dealsQ.isLoading && <div className="p-4 text-slate-500">Loading…</div>}
        {dealsQ.error && (
          <div className="p-4 text-red-600">
            {dealsQ.error instanceof Error ? dealsQ.error.message : "failed"}
          </div>
        )}
        {dealsQ.data?.items.length === 0 && (
          <div className="p-8 text-center text-slate-500">
            No deals yet. Click + New deal to start tracking opportunities.
          </div>
        )}
        {dealsQ.data && dealsQ.data.items.length > 0 && (
          <table className="w-full text-sm">
            <thead className="border-b border-slate-200 bg-slate-50 text-left text-xs uppercase tracking-wider text-slate-600">
              <tr>
                <th className="px-4 py-2">Name</th>
                <th className="px-4 py-2">Amount</th>
                <th className="px-4 py-2">Status</th>
                <th className="px-4 py-2">Expected close</th>
                <th className="px-4 py-2 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {dealsQ.data.items.map((d) => (
                <tr key={d.id} className="border-b border-slate-100 last:border-0">
                  <td className="px-4 py-2 font-medium">{d.name}</td>
                  <td className="px-4 py-2 tabular-nums text-slate-700">
                    {fmtMoney(d.amount, d.currency)}
                  </td>
                  <td className="px-4 py-2">
                    <StatusBadge status={d.status} />
                  </td>
                  <td className="px-4 py-2 text-slate-700">
                    {fmtDate(d.expected_close_date)}
                  </td>
                  <td className="px-4 py-2 text-right">
                    <button
                      onClick={() => setDialog({ mode: "edit", row: d })}
                      className="mr-2 text-xs text-slate-600 hover:text-slate-900 underline"
                    >
                      Edit
                    </button>
                    <button
                      onClick={() => {
                        if (confirm(`Delete deal "${d.name}"?`)) {
                          deleteMut.mutate(d.id);
                        }
                      }}
                      className="text-xs text-red-600 hover:text-red-800 underline"
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {dialog && (
        <FormDialog
          open={true}
          onClose={() => setDialog(null)}
          title={dialog.mode === "edit" ? `Edit ${dialog.row.name}` : "New deal"}
          fields={fields}
          initialValues={
            dialog.mode === "edit"
              ? {
                  name: dialog.row.name,
                  amount: dialog.row.amount,
                  currency: dialog.row.currency,
                  stage_id: dialog.row.stage_id,
                  company_id: dialog.row.company_id,
                  primary_contact_id: dialog.row.primary_contact_id,
                  expected_close_date: dialog.row.expected_close_date?.slice(0, 10),
                }
              : { currency: "EUR" }
          }
          onSubmit={handleSubmit}
          submitLabel={dialog.mode === "edit" ? "Save changes" : "Create"}
        />
      )}
    </div>
  );
}
