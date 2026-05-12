import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export type Column<T> = {
  header: string;
  /** Cell renderer. Return a primitive or any ReactNode. */
  cell: (row: T) => ReactNode;
  /** Optional tailwind classes for the <td>. */
  className?: string;
};

type Page<T> = { items: T[]; total: number; limit: number; offset: number };

type Props<T extends { id: string }> = {
  title: string;
  endpoint: string;        // e.g. "/contacts"
  newButtonLabel?: string;
  onNew?: () => void;
  columns: Column<T>[];
  emptyMessage?: string;
};

export function ResourcePage<T extends { id: string }>({
  title,
  endpoint,
  newButtonLabel = "+ New",
  onNew,
  columns,
  emptyMessage = "No items yet.",
}: Props<T>) {
  const { data, isLoading, error } = useQuery<Page<T>>({
    queryKey: [endpoint],
    queryFn: () => api<Page<T>>(`${endpoint}?limit=100`),
  });

  return (
    <div>
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">{title}</h1>
        <button
          className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-800"
          onClick={() => (onNew ? onNew() : alert("Form coming soon"))}
        >
          {newButtonLabel}
        </button>
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
                {columns.map((c) => (
                  <th key={c.header} className="px-4 py-2">
                    {c.header}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.items.map((row) => (
                <tr key={row.id} className="border-b border-slate-100 last:border-0">
                  {columns.map((c) => (
                    <td key={c.header} className={`px-4 py-2 ${c.className ?? ""}`}>
                      {c.cell(row)}
                    </td>
                  ))}
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
    </div>
  );
}
