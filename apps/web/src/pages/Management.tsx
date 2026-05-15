import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

type Me = {
  user_id: string;
  email: string;
  full_name: string | null;
  is_platform_admin: boolean;
  org_id: string;
  org_role: string;
};

type OrgRow = {
  id: string;
  name: string;
  slug: string;
  member_count: number;
  logo_url: string | null;
  brand_color: string | null;
  created_at: string;
};

type Membership = {
  id: string;
  org_id: string;
  org_name: string | null;
  role: string;
};

type UserRow = {
  id: string;
  email: string;
  full_name: string | null;
  is_active: boolean;
  is_platform_admin: boolean;
  last_login_at: string | null;
  invited_at: string | null;
  has_password: boolean;
  has_pending_invite: boolean;
  created_at: string;
  memberships: Membership[];
};

type InviteResult = {
  ok: boolean;
  user_id: string;
  invite_url: string | null;
  detail: string;
};

const ROLES = ["owner", "admin", "member", "viewer"];

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("nl-NL", { day: "numeric", month: "short", year: "numeric" });
}
function fmtRelative(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const ms = Date.now() - d.getTime();
  const h = Math.floor(ms / 3600000);
  if (h < 1) return "minder dan 1 uur geleden";
  if (h < 24) return `${h} u geleden`;
  const dd = Math.floor(h / 24);
  if (dd < 30) return `${dd} d geleden`;
  return d.toLocaleDateString("nl-NL");
}

export function Management() {
  const [tab, setTab] = useState<"users" | "orgs">("users");
  const meQ = useQuery<Me>({
    queryKey: ["/admin/me"],
    queryFn: () => api<Me>("/admin/me"),
  });
  const me = meQ.data;
  return (
    <div>
      <div className="overflow-hidden rounded-lg bg-white ring-1 ring-slate-200">
        <div className="border-b border-slate-200 px-4 py-3">
          <h1 className="text-lg font-medium">Management</h1>
          <div className="mt-0.5 text-xs text-slate-500">
            {me?.is_platform_admin
              ? "Platform admin — alle organisaties en gebruikers"
              : "Gebruikers van uw organisatie"}
          </div>
        </div>
        <div className="flex gap-1 border-b border-slate-200 px-4">
          <button onClick={() => setTab("users")}
            className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium ${
              tab === "users" ? "border-brand-500 text-slate-900" : "border-transparent text-slate-500 hover:text-slate-800"
            }`}>
            Gebruikers
          </button>
          {me?.is_platform_admin && (
            <button onClick={() => setTab("orgs")}
              className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium ${
                tab === "orgs" ? "border-brand-500 text-slate-900" : "border-transparent text-slate-500 hover:text-slate-800"
              }`}>
              Organisaties
            </button>
          )}
        </div>
        <div className="p-4">
          {tab === "users" && <UsersTab me={me} />}
          {tab === "orgs" && me?.is_platform_admin && <OrgsTab />}
        </div>
      </div>
    </div>
  );
}

function UsersTab({ me }: { me: Me | undefined }) {
  const qc = useQueryClient();
  const [showInvite, setShowInvite] = useState(false);
  const [inviteResult, setInviteResult] = useState<InviteResult | null>(null);
  const usersQ = useQuery<UserRow[]>({
    queryKey: ["/admin/users"],
    queryFn: () => api<UserRow[]>("/admin/users"),
  });
  const orgsQ = useQuery<OrgRow[]>({
    queryKey: ["/admin/organizations"],
    queryFn: () => api<OrgRow[]>("/admin/organizations"),
  });

  const inviteMut = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api<InviteResult>("/admin/users", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: (r) => {
      setInviteResult(r);
      qc.invalidateQueries({ queryKey: ["/admin/users"] });
    },
  });

  const resetMut = useMutation({
    mutationFn: (user_id: string) =>
      api<InviteResult>(`/admin/users/${user_id}/reset-invite`, { method: "POST" }),
    onSuccess: (r) => setInviteResult(r),
  });

  const platformMut = useMutation({
    mutationFn: ({ id, val }: { id: string; val: boolean }) =>
      api(`/admin/users/${id}`, { method: "PATCH", body: JSON.stringify({ is_platform_admin: val }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["/admin/users"] }),
  });

  const activeMut = useMutation({
    mutationFn: ({ id, val }: { id: string; val: boolean }) =>
      api(`/admin/users/${id}`, { method: "PATCH", body: JSON.stringify({ is_active: val }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["/admin/users"] }),
  });

  const roleMut = useMutation({
    mutationFn: ({ user_id, org_id, role }: { user_id: string; org_id: string; role: string }) =>
      api(`/admin/users/${user_id}/memberships/${org_id}`, { method: "PATCH", body: JSON.stringify({ role }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["/admin/users"] }),
  });

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="text-[10px] uppercase tracking-wider text-slate-500">
          {usersQ.data?.length ?? 0} gebruikers
        </div>
        <button
          onClick={() => { setShowInvite((v) => !v); setInviteResult(null); }}
          className="rounded-md bg-brand-500 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-600"
        >
          {showInvite ? "Annuleren" : "+ Gebruiker uitnodigen"}
        </button>
      </div>
      {showInvite && <InviteForm me={me} orgs={orgsQ.data ?? []}
        onSubmit={(body) => inviteMut.mutate(body)}
        pending={inviteMut.isPending} />}
      {inviteResult?.invite_url && (
        <div className="rounded-md border border-emerald-200 bg-emerald-50 p-3 text-sm">
          <div className="font-medium text-emerald-900">{inviteResult.detail}</div>
          <div className="mt-2 text-xs">
            <span className="text-emerald-800">Stuur deze link naar de gebruiker:</span>
            <div className="mt-1 break-all rounded bg-white px-2 py-1 font-mono text-[11px] text-slate-700">
              {window.location.origin}{inviteResult.invite_url}
            </div>
            <button
              onClick={() => navigator.clipboard.writeText(window.location.origin + inviteResult.invite_url)}
              className="mt-2 rounded border border-emerald-300 bg-white px-2 py-0.5 text-[11px] hover:bg-emerald-100"
            >Kopieer link</button>
          </div>
        </div>
      )}

      {usersQ.isLoading && <div className="text-sm text-slate-500">Bezig met laden…</div>}
      <div className="space-y-2">
        {(usersQ.data ?? []).map((u) => (
          <div key={u.id} className="rounded-md border border-slate-200 bg-white p-3">
            <div className="grid grid-cols-[minmax(0,2fr)_minmax(0,2fr)_140px] gap-3">
              <div className="min-w-0">
                <div className="flex items-baseline gap-2">
                  <div className="truncate font-medium">{u.full_name || u.email.split("@")[0]}</div>
                  {u.is_platform_admin && <span className="rounded-full bg-purple-100 px-2 py-0.5 text-[10px] text-purple-800">Platform admin</span>}
                  {!u.is_active && <span className="rounded-full bg-red-100 px-2 py-0.5 text-[10px] text-red-800">Inactive</span>}
                  {u.has_pending_invite && <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] text-amber-800">Pending invite</span>}
                </div>
                <div className="text-[11px] text-slate-500">{u.email}</div>
                <div className="text-[10px] text-slate-500 mt-1">
                  {u.last_login_at ? `Laatst ingelogd: ${fmtRelative(u.last_login_at)}` : "Nog niet ingelogd"}
                </div>
              </div>
              <div className="min-w-0 space-y-1">
                <div className="text-[10px] uppercase tracking-wider text-slate-500">Memberships</div>
                {u.memberships.length === 0 ? (
                  <div className="text-[11px] text-slate-400">geen orgs</div>
                ) : u.memberships.map((m) => (
                  <div key={m.id} className="flex items-center gap-2 text-xs">
                    <span className="truncate">{m.org_name}</span>
                    <select
                      value={m.role}
                      onChange={(e) => roleMut.mutate({ user_id: u.id, org_id: m.org_id, role: e.target.value })}
                      className="rounded border border-slate-300 px-1 py-0.5 text-[11px]"
                    >
                      {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                    </select>
                  </div>
                ))}
              </div>
              <div className="flex flex-col gap-1 text-xs">
                {me?.is_platform_admin && u.id !== me.user_id && (
                  <button
                    onClick={() => platformMut.mutate({ id: u.id, val: !u.is_platform_admin })}
                    className="rounded-md border border-slate-300 px-2 py-1 hover:bg-slate-50"
                  >
                    {u.is_platform_admin ? "Verwijder platform-admin" : "Maak platform-admin"}
                  </button>
                )}
                {u.has_pending_invite ? (
                  <button
                    onClick={() => resetMut.mutate(u.id)}
                    className="rounded-md bg-amber-500 px-2 py-1 text-white hover:bg-amber-600"
                  >
                    Nieuwe invite-link
                  </button>
                ) : (
                  <button
                    onClick={() => resetMut.mutate(u.id)}
                    className="rounded-md border border-slate-300 px-2 py-1 hover:bg-slate-50"
                  >
                    Reset wachtwoord
                  </button>
                )}
                {u.id !== me?.user_id && (
                  <button
                    onClick={() => activeMut.mutate({ id: u.id, val: !u.is_active })}
                    className={`rounded-md border px-2 py-1 ${u.is_active ? "border-red-300 text-red-700 hover:bg-red-50" : "border-emerald-300 text-emerald-700 hover:bg-emerald-50"}`}
                  >
                    {u.is_active ? "Deactiveren" : "Activeren"}
                  </button>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function InviteForm({ me, orgs, onSubmit, pending }: {
  me: Me | undefined; orgs: OrgRow[];
  onSubmit: (body: Record<string, unknown>) => void; pending: boolean
}) {
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [orgId, setOrgId] = useState(me?.org_id ?? "");
  const [role, setRole] = useState("member");
  const [isPlatformAdmin, setIsPlatformAdmin] = useState(false);
  return (
    <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
      <div className="grid grid-cols-2 gap-2">
        <label className="block">
          <span className="block text-[11px] text-slate-600 mb-0.5">E-mail</span>
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)}
            placeholder="kees@it-gemak.nl"
            className="w-full rounded-md border border-slate-300 px-2 py-1 text-sm" />
        </label>
        <label className="block">
          <span className="block text-[11px] text-slate-600 mb-0.5">Volledige naam</span>
          <input value={fullName} onChange={(e) => setFullName(e.target.value)}
            className="w-full rounded-md border border-slate-300 px-2 py-1 text-sm" />
        </label>
        {me?.is_platform_admin && orgs.length > 1 && (
          <label className="block">
            <span className="block text-[11px] text-slate-600 mb-0.5">Organisatie</span>
            <select value={orgId} onChange={(e) => setOrgId(e.target.value)}
              className="w-full rounded-md border border-slate-300 px-2 py-1 text-sm">
              {orgs.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
            </select>
          </label>
        )}
        <label className="block">
          <span className="block text-[11px] text-slate-600 mb-0.5">Rol</span>
          <select value={role} onChange={(e) => setRole(e.target.value)}
            className="w-full rounded-md border border-slate-300 px-2 py-1 text-sm">
            {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
        </label>
      </div>
      {me?.is_platform_admin && (
        <label className="mt-2 flex items-center gap-2 text-sm">
          <input type="checkbox" checked={isPlatformAdmin} onChange={(e) => setIsPlatformAdmin(e.target.checked)} />
          Geef platform-admin rechten (kan alle organisaties beheren)
        </label>
      )}
      <div className="mt-2 flex justify-end">
        <button
          disabled={!email.trim() || pending}
          onClick={() => onSubmit({
            email: email.trim(),
            full_name: fullName.trim() || undefined,
            org_id: orgId || undefined,
            role,
            is_platform_admin: isPlatformAdmin,
          })}
          className="rounded-md bg-brand-500 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-600 disabled:opacity-50">
          {pending ? "Bezig…" : "Stuur uitnodiging"}
        </button>
      </div>
    </div>
  );
}

function OrgsTab() {
  const qc = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const orgsQ = useQuery<OrgRow[]>({
    queryKey: ["/admin/organizations"],
    queryFn: () => api<OrgRow[]>("/admin/organizations"),
  });
  const createMut = useMutation({
    mutationFn: (body: { name: string; slug: string }) =>
      api<OrgRow>("/admin/organizations", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["/admin/organizations"] });
      setShowForm(false);
    },
  });
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="text-[10px] uppercase tracking-wider text-slate-500">
          {orgsQ.data?.length ?? 0} organisaties
        </div>
        <button
          onClick={() => setShowForm((v) => !v)}
          className="rounded-md bg-brand-500 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-600"
        >
          {showForm ? "Annuleren" : "+ Nieuwe organisatie"}
        </button>
      </div>
      {showForm && <OrgForm onSubmit={(d) => createMut.mutate(d)} pending={createMut.isPending} />}
      <div className="space-y-2">
        {(orgsQ.data ?? []).map((o) => (
          <div key={o.id} className="rounded-md border border-slate-200 bg-white p-3">
            <div className="flex items-center justify-between">
              <div>
                <div className="font-medium">{o.name}</div>
                <div className="text-[11px] text-slate-500 font-mono">{o.slug}</div>
              </div>
              <div className="text-right text-xs text-slate-500">
                <div>{o.member_count} {o.member_count === 1 ? "gebruiker" : "gebruikers"}</div>
                <div>aangemaakt {fmtDate(o.created_at)}</div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function OrgForm({ onSubmit, pending }: { onSubmit: (d: { name: string; slug: string }) => void; pending: boolean }) {
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  return (
    <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
      <div className="grid grid-cols-2 gap-2">
        <label className="block">
          <span className="block text-[11px] text-slate-600 mb-0.5">Naam</span>
          <input value={name} onChange={(e) => { setName(e.target.value); if (!slug) setSlug(e.target.value.toLowerCase().replace(/[^a-z0-9]+/g, "-")); }}
            className="w-full rounded-md border border-slate-300 px-2 py-1 text-sm" />
        </label>
        <label className="block">
          <span className="block text-[11px] text-slate-600 mb-0.5">Slug (URL)</span>
          <input value={slug} onChange={(e) => setSlug(e.target.value)}
            className="w-full rounded-md border border-slate-300 px-2 py-1 text-sm font-mono" />
        </label>
      </div>
      <div className="mt-2 flex justify-end">
        <button
          disabled={!name.trim() || !slug.trim() || pending}
          onClick={() => onSubmit({ name: name.trim(), slug: slug.trim() })}
          className="rounded-md bg-brand-500 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-600 disabled:opacity-50">
          {pending ? "Bezig…" : "Aanmaken"}
        </button>
      </div>
    </div>
  );
}
