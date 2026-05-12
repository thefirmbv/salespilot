import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, API_BASE } from "@/lib/api";

type Org = {
  id: string;
  name: string;
  slug: string;
  logo_url: string | null;
  brand_color: string | null;
};

export function BrandingSettings() {
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement | null>(null);
  const [color, setColor] = useState<string>("");
  const [name, setName] = useState<string>("");

  const orgQ = useQuery<Org>({
    queryKey: ["/branding/org"],
    queryFn: () => api<Org>("/branding/org"),
  });

  // Sync local state once data arrives.
  if (orgQ.data && color === "" && name === "") {
    if (orgQ.data.brand_color) setColor(orgQ.data.brand_color);
    if (orgQ.data.name) setName(orgQ.data.name);
  }

  const saveMut = useMutation({
    mutationFn: () =>
      api<Org>("/branding/org", {
        method: "PATCH",
        body: JSON.stringify({ name: name || undefined, brand_color: color || null }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["/branding/org"] });
      qc.invalidateQueries({ queryKey: ["me"] });
    },
  });

  const uploadMut = useMutation({
    mutationFn: async (file: File) => {
      const fd = new FormData();
      fd.append("file", file);
      const token = localStorage.getItem("access_token");
      const res = await fetch(`${API_BASE}/branding/org/logo`, {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
        body: fd,
      });
      if (!res.ok) {
        let detail = `upload failed (${res.status})`;
        try {
          const j = await res.json();
          if (j.detail) detail = j.detail;
        } catch {
          /* ignore */
        }
        throw new ApiError(res.status, detail);
      }
      return (await res.json()) as Org;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["/branding/org"] });
      qc.invalidateQueries({ queryKey: ["me"] });
      if (fileRef.current) fileRef.current.value = "";
    },
  });

  const deleteMut = useMutation({
    mutationFn: () => api<Org>("/branding/org/logo", { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["/branding/org"] });
      qc.invalidateQueries({ queryKey: ["me"] });
    },
  });

  const org = orgQ.data;

  return (
    <div className="max-w-2xl">
      <h2 className="text-base font-medium">Branding</h2>
      <p className="mt-1 text-xs text-slate-500">
        Logo en kleur worden gebruikt in de zijbalk, op rapporten en in mails.
      </p>

      <div className="mt-4 space-y-4">
        {/* Logo */}
        <div className="rounded-md border border-slate-200 bg-white p-4">
          <div className="mb-2 text-xs font-medium uppercase tracking-wider text-slate-500">
            Logo
          </div>
          <div className="flex items-center gap-4">
            <div className="flex h-20 w-40 items-center justify-center rounded-md bg-slate-50 ring-1 ring-slate-200">
              {org?.logo_url ? (
                <img
                  src={org.logo_url}
                  alt="logo"
                  className="max-h-full max-w-full object-contain"
                />
              ) : (
                <span className="text-xs text-slate-400">geen logo</span>
              )}
            </div>
            <div className="flex flex-1 flex-col gap-2">
              <input
                ref={fileRef}
                type="file"
                accept="image/png,image/jpeg,image/svg+xml,image/webp"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) uploadMut.mutate(f);
                }}
                className="text-xs"
              />
              <div className="text-[11px] text-slate-500">
                PNG, JPG, SVG of WEBP. Max 2 MB. Transparante achtergrond aanbevolen.
              </div>
              {org?.logo_url && (
                <button
                  onClick={() => {
                    if (confirm("Logo verwijderen?")) deleteMut.mutate();
                  }}
                  className="self-start text-xs text-red-700 hover:underline"
                >
                  Verwijder logo
                </button>
              )}
            </div>
          </div>
          {uploadMut.isError && (
            <div className="mt-2 rounded-md bg-red-50 px-3 py-1.5 text-xs text-red-800">
              {uploadMut.error instanceof ApiError
                ? uploadMut.error.detail
                : "Upload failed"}
            </div>
          )}
          {uploadMut.isSuccess && (
            <div className="mt-2 rounded-md bg-emerald-50 px-3 py-1.5 text-xs text-emerald-800">
              Logo geüpload.
            </div>
          )}
        </div>

        {/* Organisation name */}
        <div className="rounded-md border border-slate-200 bg-white p-4">
          <div className="mb-2 text-xs font-medium uppercase tracking-wider text-slate-500">
            Organisatie-naam
          </div>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full rounded-md border border-slate-300 px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
          />
        </div>

        {/* Brand color */}
        <div className="rounded-md border border-slate-200 bg-white p-4">
          <div className="mb-2 text-xs font-medium uppercase tracking-wider text-slate-500">
            Brand kleur
          </div>
          <div className="flex items-center gap-3">
            <input
              type="color"
              value={color || "#128ece"}
              onChange={(e) => setColor(e.target.value)}
              className="h-9 w-12 cursor-pointer rounded-md border border-slate-300"
            />
            <input
              value={color}
              onChange={(e) => setColor(e.target.value)}
              placeholder="#128ece"
              className="w-32 rounded-md border border-slate-300 px-2 py-1.5 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-brand-500"
            />
            <span className="text-xs text-slate-500">
              Hex kleur, bv. <code className="font-mono">#128ece</code>
            </span>
          </div>
          <div className="mt-2 text-[11px] text-slate-500">
            De kleur wordt gebruikt voor actieve menu-items, primaire knoppen en
            badges. Aanpassen vereist een browser-refresh.
          </div>
        </div>

        <div className="flex gap-2">
          <button
            onClick={() => saveMut.mutate()}
            disabled={saveMut.isPending}
            className="rounded-md bg-brand-500 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-600 disabled:opacity-50"
          >
            {saveMut.isPending ? "Opslaan…" : "Opslaan"}
          </button>
          {saveMut.isSuccess && (
            <span className="self-center text-xs text-emerald-700">Opgeslagen.</span>
          )}
        </div>
      </div>
    </div>
  );
}
