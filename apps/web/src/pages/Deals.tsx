import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useDebounce } from "@/lib/useDebounce";
import { FormDialog, type FieldSpec, type FormValues } from "@/components/FormDialog";
import { StatusBadge, fmtDate, fmtMoney } from "@/lib/format";
import { loadCompanyOptions, loadContactOptions } from "@/lib/options";
import { DealsKanban } from "@/components/DealsKanban";

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

type View = "list" | "kanban";

export function Deals() {
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const view: View = params.get("view") === "kanban" ? "kanban" : "list";
  const [dialog, setDialog] = useState<
    | { mode: "create" }
    | { mode: "edit"; row: Deal }
    | null
  >(null);

  // Search + status filter — only relevant in list view, but they live
  // in the URL so they survive a view toggle round trip.
  const [q, setQ] = useState(params.get("q") ?? "");
  const debouncedQ = useDebounce(q, 300);
  if (debouncedQ !== (params.get("q") ?? "")) {
    const next = new URLSearchParams(params);
    if (debouncedQ) next.set("q", debouncedQ);
    else next.delete("q");
    setParams(next, { replace: true });
  }
  const statusFilter = params.get("status") ?? "";
  const sort = params.get("sort") ?? "";
  const offset = Math.max(0, parseInt(params.get("offset") ?? "0", 10) || 0);
  const PAGE_SIZE = 50;

  function cycleSort(key: string) {
    let nextValue: string | null;
    if (sort === `-${key}`) nextValue = key;
    else if (sort === key) nextValue = null;
    else nextValue = `-${key}`;
    const next = new URLSearchParams(params);
    if (nextValue) next.set("sort", nextValue);
    else next.delete("sort");
    next.delete("offset");
    setParams(next, { replace: true });
  }

  function setOffset(o: number) {
    const next = new URLSearchParams(params);
    if (o > 0) next.set("offset", String(o));
    else next.delete("offset");
    setParams(next, { replace: true });
  }

  function sortableTh(label: string, key: string) {
    const arrow = sort === key ? "↑" : sort === `-${key}` ? "↓" : "";
    return (
      <th
        className="px-4 py-2 cursor-pointer select-none hover:bg-slate-100"
        onClick={() => cycleSort(key)}
      >
        {label}{arrow && <span className="ml-1">{arrow}</span>}
      </th>
    );
  }

  // Build list-view query string.
  const listParams = new URLSearchParams();
  listParams.set("limit", String(50));
  if (offset) listParams.set("offset", String(offset));
  if (debouncedQ) listParams.set("q", debouncedQ);
  if (statusFilter) listParams.set("status", statusFilter);
  if (sort) listParams.set("sort", sort);
  const listParamsString = listParams.toString();

  const dealsQ = useQuery<Page<Deal>>({
    queryKey: ["/deals", listParamsString],
    queryFn: () => api<Page<Deal>>(`/deals?${listParamsString}`),
    enabled: view === "list",
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

  function setView(v: View) {
    const next = new URLSearchParams(params);
    if (v === "list") next.delete("view");
    else next.set("view", v);
    setParams(next, { replace: true });
  }

  function setStatus(s: string) {
    const next = new URLSearchParams(params);
    if (s) next.set("status", s);
    else next.delete("status");
    setParams(next, { replace: true });
  }

  const inputCls =
    "rounded-md border border-slate-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-slate-900";
  const hasFilter = debouncedQ || statusFilter;

  return (
    <div>
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Deals</h1>
        <div className="flex items-center gap-2">
          <div className="flex rounded-md ring-1 ring-slate-300 overflow-hidden text-sm">
            <button
              onClick={() => setView("list")}
              className={`px-3 py-1.5 ${
                view === "list" ? "bg-slate-900 text-white" : "bg-white text-slate-700 hover:bg-slate-50"
              }`}
            >
              List
            </button>
            <button
              onClick={() => setView("kanban")}
              className={`px-3 py-1.5 border-l border-slate-300 ${
                view === "kanban" ? "bg-slate-900 text-white" : "bg-white text-slate-700 hover:bg-slate-50"
              }`}
            >
              Kanban
            </button>
          </div>
          <button
            onClick={() => setDialog({ mode: "create" })}
            disabled={!defaultPipeline}
            className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
          >
            + New deal
          </button>
        </div>
      </div>

      {view === "list" && (
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <input
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search by deal name"
            className={`${inputCls} flex-1 min-w-[200px] max-w-md`}
          />
          <select
            value={statusFilter}
            onChange={(e) => setStatus(e.target.value)}
            className={inputCls}
          >
            <option value="">Status: any</option>
            <option value="open">Status: open</option>
            <option value="won">Status: won</option>
            <option value="lost">Status: lost</option>
          </select>
          {hasFilter && (
            <button
              onClick={() => {
                setQ("");
                setStatus("");
              }}
              className="text-xs text-slate-500 hover:text-slate-900 underline"
            >
              Clear
            </button>
          )}
        </div>
      )}

      <div className="mt-6">
        {view === "kanban" ? (
          <DealsKanban />
        ) : (
          <div className="overflow-hidden rounded-lg ring-1 ring-slate-200 bg-white">
            {dealsQ.isLoading && <div className="p-4 text-slate-500">Loading…</div>}
            {dealsQ.error && (
              <div className="p-4 text-red-600">
                {dealsQ.error instanceof Error ? dealsQ.error.message : "failed"}
              </div>
            )}
            {dealsQ.data?.items.length === 0 && (
              <div className="p-8 text-center text-slate-500">
                {hasFilter ? "No deals match your filters." : "No deals yet. Click + New deal to start."}
              </div>
            )}
            {dealsQ.data && dealsQ.data.items.length > 0 && (
              <>
                <table className="w-full text-sm">
                  <thead className="border-b border-slate-200 bg-slate-50 text-left text-xs uppercase tracking-wider text-slate-600">
                    <tr>
                      {sortableTh("Name", "name")}
                      {sortableTh("Amount", "amount")}
                      {sortableTh("Status", "status")}
                      {sortableTh("Expected close", "expected_close_date")}
                      <th className="px-4 py-2 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {dealsQ.data.items.map((d) => (
                      <tr key={d.id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50">
                        <td className="px-4 py-2 font-medium">
                          <Link to={`/deals/${d.id}`} className="hover:underline">
                            {d.name}
                          </Link>
                        </td>
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
                <div className="flex items-center justify-between border-t border-slate-200 bg-slate-50 px-4 py-2 text-xs text-slate-500">
                  <span>
                    Showing {offset + 1}–{offset + dealsQ.data.items.length} of {dealsQ.data.total}
                  </span>
                  {dealsQ.data.total > PAGE_SIZE && (
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                        disabled={offset === 0}
                        className="rounded-md bg-white px-2 py-1 ring-1 ring-slate-300 hover:bg-slate-100 disabled:opacity-40 disabled:cursor-not-allowed"
                      >
                        ← Prev
                      </button>
                      <span className="px-2">
                        Page {Math.floor(offset / PAGE_SIZE) + 1} of {Math.max(1, Math.ceil(dealsQ.data.total / PAGE_SIZE))}
                      </span>
                      <button
                        onClick={() => setOffset(offset + PAGE_SIZE)}
                        disabled={offset + PAGE_SIZE >= dealsQ.data.total}
                        className="rounded-md bg-white px-2 py-1 ring-1 ring-slate-300 hover:bg-slate-100 disabled:opacity-40 disabled:cursor-not-allowed"
                      >
                        Next →
                      </button>
                    </div>
                  )}
                </div>
              </>
            )}
          </div>
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
