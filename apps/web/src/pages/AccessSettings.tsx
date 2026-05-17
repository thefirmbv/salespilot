import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

type UserRow = {
  user_id: string;
  email: string;
  is_platform_admin: boolean;
  groups: string[];
};

type SectionCatalogEntry = {
  id: string;
  label: string;
  allowed_groups: string[];
  routes: string[];
};

type SectionsCatalog = {
  sections: SectionCatalogEntry[];
  known_groups: string[];
};

const GROUP_DESCRIPTIONS: Record<string, string> = {
  administrators: "Volledige toegang. Mag rechten beheren en koppelingen instellen.",
  financieel: "Alle pagina's met financiële cijfers (Dashboard, SEPA, offertes, mandates).",
  sales: "Acquisitie + Outreach + offertes lezen.",
  marketing: "Acquisitie + Outreach (Wespennest, Sequences, Social, Mail Campaigns).",
  agendagebruikers: "Persoonlijke agenda.",
};

const GROUP_TONES: Record<string, string> = {
  administrators: "bg-rose-50 text-rose-800 border-rose-200",
  financieel: "bg-emerald-50 text-emerald-800 border-emerald-200",
  sales: "bg-blue-50 text-blue-800 border-blue-200",
  marketing: "bg-purple-50 text-purple-800 border-purple-200",
  agendagebruikers: "bg-amber-50 text-amber-800 border-amber-200",
};

export function AccessSettings() {
  const qc = useQueryClient();
  const meQ = useQuery<{ is_admin: boolean }>({
    queryKey: ["/access/me"],
    queryFn: () => api<{ is_admin: boolean }>("/access/me"),
  });
  const usersQ = useQuery<UserRow[]>({
    queryKey: ["/access/users"],
    queryFn: () => api<UserRow[]>("/access/users"),
    enabled: !!meQ.data?.is_admin,
  });
  const catQ = useQuery<SectionsCatalog>({
    queryKey: ["/access/sections"],
    queryFn: () => api<SectionsCatalog>("/access/sections"),
  });

  if (meQ.isLoading) return <div className="p-6 text-sm text-slate-500">Laden…</div>;
  if (meQ.data && !meQ.data.is_admin) {
    return (
      <div className="rounded-md bg-rose-50 border border-rose-200 p-4 text-sm text-rose-900">
        Alleen administrators kunnen rechten beheren.
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div className="rounded-lg bg-white ring-1 ring-slate-200 p-4">
        <h1 className="text-lg font-medium">Rechten beheren</h1>
        <p className="mt-1 text-sm text-slate-600">
          Iedere gebruiker kan meerdere groepen tegelijk hebben. Administrators
          zien sowieso alles. De andere groepen beperken zichtbaarheid van
          sidebar-secties en API-endpoints.
        </p>
      </div>

      {/* Groep-legenda */}
      <div className="rounded-lg bg-white ring-1 ring-slate-200">
        <div className="border-b border-slate-200 px-4 py-2 text-xs uppercase tracking-wider text-slate-500 font-semibold">
          Groepen
        </div>
        <ul className="divide-y divide-slate-100">
          {(catQ.data?.known_groups || []).map((g) => (
            <li key={g} className="px-4 py-2.5 flex items-center gap-3">
              <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${GROUP_TONES[g] || "bg-slate-100 text-slate-700 border-slate-200"}`}>
                {g}
              </span>
              <span className="text-sm text-slate-600">{GROUP_DESCRIPTIONS[g] || "—"}</span>
            </li>
          ))}
        </ul>
      </div>

      {/* Sectie-matrix: welke groep ziet wat */}
      {catQ.data && (
        <div className="rounded-lg bg-white ring-1 ring-slate-200 overflow-hidden">
          <div className="border-b border-slate-200 px-4 py-2 text-xs uppercase tracking-wider text-slate-500 font-semibold">
            Wie ziet welke sectie
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-[10px] uppercase tracking-wider text-slate-500">
                <th className="text-left px-4 py-2">Sectie</th>
                {(catQ.data.known_groups || []).map((g) => (
                  <th key={g} className="text-center px-3 py-2 whitespace-nowrap">{g}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {catQ.data.sections.map((s) => (
                <tr key={s.id} className="border-t border-slate-100">
                  <td className="px-4 py-2">
                    <div className="font-medium">{s.label}</div>
                    <div className="text-[11px] text-slate-500 font-mono">{s.routes.join(", ")}</div>
                  </td>
                  {(catQ.data.known_groups || []).map((g) => (
                    <td key={g} className="text-center px-3 py-2">
                      {s.allowed_groups.includes(g) ? (
                        <span className="text-emerald-600">✓</span>
                      ) : (
                        <span className="text-slate-300">—</span>
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Gebruikers met hun rollen */}
      <div className="rounded-lg bg-white ring-1 ring-slate-200">
        <div className="border-b border-slate-200 px-4 py-2 text-xs uppercase tracking-wider text-slate-500 font-semibold">
          Gebruikers ({usersQ.data?.length ?? 0})
        </div>
        {usersQ.isLoading ? (
          <div className="p-6 text-sm text-slate-500">Laden…</div>
        ) : (
          <ul className="divide-y divide-slate-100">
            {(usersQ.data || []).map((u) => (
              <UserRowEditor key={u.user_id} user={u} knownGroups={catQ.data?.known_groups || []} onChanged={() => qc.invalidateQueries({ queryKey: ["/access/users"] })} />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function UserRowEditor({
  user, knownGroups, onChanged,
}: {
  user: UserRow;
  knownGroups: string[];
  onChanged: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [selected, setSelected] = useState<string[]>(user.groups);
  const qc = useQueryClient();

  const saveMut = useMutation({
    mutationFn: (groups: string[]) =>
      api<UserRow>(`/access/users/${user.user_id}/groups`, {
        method: "PUT",
        body: JSON.stringify({ groups }),
      }),
    onSuccess: () => {
      setEditing(false);
      onChanged();
      qc.invalidateQueries({ queryKey: ["/access/me"] });
    },
  });

  const toggle = (g: string) => {
    setSelected((prev) =>
      prev.includes(g) ? prev.filter((x) => x !== g) : [...prev, g]
    );
  };

  return (
    <li className="px-4 py-3">
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <div className="flex items-baseline gap-3 flex-wrap">
          <span className="font-medium">{user.email}</span>
          {user.is_platform_admin && (
            <span className="text-[10px] uppercase tracking-wider text-slate-500">platform-admin</span>
          )}
        </div>
        {!editing ? (
          <button
            onClick={() => { setSelected(user.groups); setEditing(true); }}
            className="rounded-md bg-slate-100 hover:bg-slate-200 px-3 py-1 text-xs"
          >
            Bewerken
          </button>
        ) : (
          <div className="flex gap-2">
            <button
              onClick={() => setEditing(false)}
              className="rounded-md bg-slate-100 hover:bg-slate-200 px-3 py-1 text-xs"
              disabled={saveMut.isPending}
            >
              Annuleren
            </button>
            <button
              onClick={() => saveMut.mutate(selected)}
              className="rounded-md bg-brand-500 hover:bg-brand-600 text-white px-3 py-1 text-xs disabled:opacity-50"
              disabled={saveMut.isPending}
            >
              {saveMut.isPending ? "Opslaan…" : "Opslaan"}
            </button>
          </div>
        )}
      </div>

      <div className="mt-2 flex flex-wrap gap-1.5">
        {(editing ? knownGroups : user.groups).map((g) => {
          const active = editing ? selected.includes(g) : true;
          const tone = GROUP_TONES[g] || "bg-slate-100 text-slate-700 border-slate-200";
          return (
            <button
              key={g}
              type="button"
              onClick={() => editing && toggle(g)}
              disabled={!editing}
              className={
                editing
                  ? `inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${active ? tone : "bg-white text-slate-400 border-slate-200"} ${active ? "" : "opacity-50"} hover:opacity-100 cursor-pointer`
                  : `inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${tone}`
              }
            >
              {editing && <span className="mr-1">{active ? "☑" : "☐"}</span>}
              {g}
            </button>
          );
        })}
        {!editing && user.groups.length === 0 && (
          <span className="text-xs text-slate-400 italic">geen rollen toegewezen</span>
        )}
      </div>

      {saveMut.isError && (
        <div className="mt-2 text-xs text-rose-700">
          {(saveMut.error as Error).message}
        </div>
      )}
    </li>
  );
}

export default AccessSettings;
