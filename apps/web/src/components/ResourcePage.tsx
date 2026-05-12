import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { FormDialog, type FieldSpec, type FormValues } from "./FormDialog";

export type Column<T> = {
  header: string;
  cell: (row: T) => ReactNode;
  className?: string;
};

type Page<T> = { items: T[]; total: number; limit: number; offset: number };

type Props<T extends { id: string }> = {
  title: string;
  endpoint: string;
  newButtonLabel?: string;
  columns: Column<T>[];
  emptyMessage?: string;

  /** Form schema. If provided, the New button opens a slide-over with these fields. */
  formFields?: FieldSpec[];
  /** Map a row to initial form values when editing. Default: spread the row. */
  rowToFormValues?: (row: T) => FormValues;
  /** Map form values to the request body (e.g. add defaults). Default: pass through. */
  formValuesToBody?: (values: FormValues) => unknown;
  /** Build a short, human label for a row (used in delete-confirm). */
  rowLabel?: (row: T) => string;
  /** If set, the first cell of every row becomes a link to this path. */
  rowLink?: (row: T) => string;
};

export function ResourcePage<T extends { id: string }>({
  title,
  endpoint,
  newButtonLabel = "+ New",
  columns,
  emptyMessage = "No items yet.",
  formFields,
  rowToFormValues = (row) => ({ ...(row as unknown as FormValues) }),
  formValuesToBody = (v) => v,
  rowLink,
  rowLabel = (row) =>
    ((row as unknown as { name?: string; email?: string; subject?: string })
      .name ??
      (row as unknown as { name?: string; email?: string; subject?: string })
        .email ??
      (row as unknown as { name?: string; email?: string; subject?: string })
        .subject ??
      row.id),
}: Props<T>) {
  const qc = useQueryClient();
  const queryKey = [endpoint];

  const { data, isLoading, error } = useQuery<Page<T>>({
    queryKey,
    queryFn: () => api<Page<T>>(`${endpoint}?limit=100`),
  });

  const [dialog, setDialog] = useState<
    | { mode: "create" }
    | { mode: "edit"; row: T }
    | null
  >(null);

  const createMut = useMutation({
    mutationFn: (body: unknown) =>
      api<T>(endpoint, { method: "POST", body: JSON.stringify(body) }),
    onSuccess: () => qc.invalidateQueries({ queryKey }),
  });

  const updateMut = useMutation({
    mutationFn: ({ id, body }: { id: string; body: unknown }) =>
      api<T>(`${endpoint}/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
    onSuccess: () => qc.invalidateQueries({ queryKey }),
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => api<void>(`${endpoint}/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey }),
  });

  const allColumns: Column<T>[] = formFields
    ? [
        ...columns,
        {
          header: "",
          className: "text-right",
          cell: (row) => (
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setDialog({ mode: "edit", row })}
                className="text-xs text-slate-600 hover:text-slate-900 underline"
              >
                Edit
              </button>
              <button
                onClick={() => {
                  if (confirm(`Delete "${rowLabel(row)}"? This cannot be undone.`)) {
                    deleteMut.mutate(row.id);
                  }
                }}
                className="text-xs text-red-600 hover:text-red-800 underline"
              >
                Delete
              </button>
            </div>
          ),
        },
      ]
    : columns;

  async function handleSubmit(values: FormValues): Promise<void> {
    const body = formValuesToBody(values);
    if (dialog?.mode === "edit") {
      await updateMut.mutateAsync({ id: dialog.row.id, body });
    } else {
      await createMut.mutateAsync(body);
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">{title}</h1>
        {formFields && (
          <button
            className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-800"
            onClick={() => setDialog({ mode: "create" })}
          >
            {newButtonLabel}
          </button>
        )}
      </div>

      <div className="mt-6 overflow-hidden rounded-lg ring-1 ring-slate-200 bg-white">
        {isLoading && <div className="p-4 text-slate-500">Loading…</div>}
        {error && (
          <div className="p-4 text-red-600">
            {error instanceof Error ? error.message : "failed to load"}
          </div>
        )}
        {data && data.items.length === 0 && (
          <div className="p-8 text-center text-slate-500">{emptyMessage}</div>
        )}
        {data && data.items.length > 0 && (
          <table className="w-full text-sm">
            <thead className="border-b border-slate-200 bg-slate-50 text-left text-xs uppercase tracking-wider text-slate-600">
              <tr>
                {allColumns.map((c) => (
                  <th key={c.header} className={`px-4 py-2 ${c.className ?? ""}`}>
                    {c.header}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.items.map((row) => (
                <tr key={row.id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50">
                  {allColumns.map((c, idx) => {
                    const content = c.cell(row);
                    // First cell becomes the row link if rowLink is provided.
                    const wrapped = rowLink && idx === 0 ? (
                      <Link to={rowLink(row)} className="hover:underline">
                        {content}
                      </Link>
                    ) : content;
                    return (
                      <td key={c.header} className={`px-4 py-2 ${c.className ?? ""}`}>
                        {wrapped}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {data && data.items.length > 0 && (
          <div className="border-t border-slate-200 bg-slate-50 px-4 py-2 text-xs text-slate-500">
            Showing {data.items.length} of {data.total}
          </div>
        )}
      </div>

      {formFields && dialog && (
        <FormDialog
          open={true}
          onClose={() => setDialog(null)}
          title={
            dialog.mode === "edit"
              ? `Edit ${rowLabel(dialog.row)}`
              : newButtonLabel.replace(/^[+\s]+/, "")
          }
          fields={formFields}
          initialValues={dialog.mode === "edit" ? rowToFormValues(dialog.row) : {}}
          onSubmit={handleSubmit}
          submitLabel={dialog.mode === "edit" ? "Save changes" : "Create"}
        />
      )}
    </div>
  );
}
