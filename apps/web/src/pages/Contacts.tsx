import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

type Contact = {
  id: string;
  email: string | null;
  first_name: string | null;
  last_name: string | null;
  job_title: string | null;
  created_at: string;
};

type Page<T> = { items: T[]; total: number; limit: number; offset: number };

export function Contacts() {
  const { data, isLoading, error } = useQuery<Page<Contact>>({
    queryKey: ["contacts"],
    queryFn: () => api<Page<Contact>>("/contacts?limit=100"),
  });

  return (
    <div>
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Contacts</h1>
        <button
          className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-800"
          onClick={() => alert("New-contact dialog coming soon")}
        >
          + New contact
        </button>
      </div>

      <div className="mt-6 overflow-hidden rounded-lg ring-1 ring-slate-200 bg-white">
        {isLoading && <div className="p-4 text-slate-500">Loading…</div>}
        {error && (
          <div className="p-4 text-red-600">
            {error instanceof Error ? error.message : "failed to load contacts"}
          </div>
        )}
        {data && data.items.length === 0 && (
          <div className="p-8 text-center text-slate-500">
            No contacts yet. Create your first one to get started.
          </div>
        )}
        {data && data.items.length > 0 && (
          <table className="w-full text-sm">
            <thead className="border-b border-slate-200 bg-slate-50 text-left text-xs uppercase tracking-wider text-slate-600">
              <tr>
                <th className="px-4 py-2">Name</th>
                <th className="px-4 py-2">Email</th>
                <th className="px-4 py-2">Job title</th>
                <th className="px-4 py-2">Created</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((c) => {
                const name =
                  [c.first_name, c.last_name].filter(Boolean).join(" ") || "—";
                return (
                  <tr key={c.id} className="border-b border-slate-100 last:border-0">
                    <td className="px-4 py-2 font-medium">{name}</td>
                    <td className="px-4 py-2 text-slate-700">{c.email ?? "—"}</td>
                    <td className="px-4 py-2 text-slate-700">{c.job_title ?? "—"}</td>
                    <td className="px-4 py-2 text-slate-500">
                      {new Date(c.created_at).toLocaleDateString()}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
