import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";

type AssetType = "vehicle" | "phone" | "laptop" | "other";

type Asset = {
  id: string;
  employee_id: string;
  asset_type: AssetType;
  label: string;
  identifier: string | null;
  details: Record<string, unknown>;
  assigned_at: string | null;
  returned_at: string | null;
  created_at: string;
  updated_at: string;
};

type HaloPSAAgent = {
  id: number;
  name: string;
  email: string | null;
  inactive: boolean;
};

type Employee = {
  id: string;
  halopsa_agent_id: number | null;
  halopsa_agent_name: string | null;
  full_name: string;
  email: string | null;
  phone: string | null;
  role: string | null;
  status: "active" | "inactive" | "leave";
  started_at: string | null;
  ended_at: string | null;
  notes: string | null;
  nmbrs_employee_id: string | null;
  nmbrs_company_id: string | null;
  asset_count: number;
  created_at: string;
  updated_at: string;
};

type EmployeeDetail = Employee & { assets: Asset[] };

const ASSET_TYPE_LABELS: Record<AssetType, string> = {
  vehicle: "Auto",
  phone: "Telefoon",
  laptop: "Laptop",
  other: "Overig",
};

const ASSET_TYPE_ICONS: Record<AssetType, string> = {
  vehicle: "🚗",
  phone: "📱",
  laptop: "💻",
  other: "📦",
};

/** Per asset-type welke velden in details staan, voor mooie weergave/edit. */
const ASSET_FIELDS: Record<AssetType, Array<{key: string; label: string; type?: string}>> = {
  vehicle: [
    {key: "brand", label: "Merk"},
    {key: "model", label: "Model"},
    {key: "fuel", label: "Brandstof"},
    {key: "year", label: "Bouwjaar", type: "number"},
  ],
  phone: [
    {key: "brand", label: "Merk"},
    {key: "model", label: "Model"},
    {key: "phone_number", label: "Tel.nummer"},
  ],
  laptop: [
    {key: "brand", label: "Merk"},
    {key: "model", label: "Model"},
    {key: "processor", label: "Processor"},
    {key: "ram_gb", label: "RAM (GB)", type: "number"},
  ],
  other: [
    {key: "category", label: "Categorie"},
  ],
};

const ASSET_IDENTIFIER_LABEL: Record<AssetType, string> = {
  vehicle: "Kenteken",
  phone: "IMEI",
  laptop: "Serienummer",
  other: "ID / Serial",
};

export function Inventory() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [filter, setFilter] = useState("");

  const empsQ = useQuery<Employee[]>({
    queryKey: ["/inventory/employees"],
    queryFn: () => api<Employee[]>("/inventory/employees"),
  });

  const emps = (empsQ.data ?? []).filter((e) =>
    !filter || [e.full_name, e.email, e.role].filter(Boolean).some((s) =>
      s!.toLowerCase().includes(filter.toLowerCase())
    )
  );

  return (
    <div className="grid md:grid-cols-[360px_1fr] gap-4 h-full">
      {/* Lijst */}
      <section className="rounded-lg bg-white ring-1 ring-slate-200 overflow-hidden flex flex-col">
        <div className="px-4 py-3 border-b border-slate-200 flex items-center justify-between gap-2">
          <h2 className="text-base font-medium">Medewerkers</h2>
          <button
            onClick={() => setSelectedId("new")}
            className="text-xs px-2 py-1 rounded bg-blue-600 text-white hover:bg-blue-700"
          >
            + Nieuw
          </button>
        </div>
        <div className="p-2 border-b border-slate-100">
          <input
            value={filter} onChange={(e) => setFilter(e.target.value)}
            placeholder="Zoek op naam, email, rol…"
            className="w-full text-sm rounded border border-slate-300 px-2 py-1"
          />
        </div>
        {empsQ.isLoading && <div className="p-4 text-sm text-slate-500">Laden…</div>}
        {emps.length === 0 && !empsQ.isLoading && (
          <div className="p-4 text-sm text-slate-500">
            Geen medewerkers. Klik op + Nieuw om er een toe te voegen.
          </div>
        )}
        <ul className="flex-1 overflow-y-auto divide-y divide-slate-100">
          {emps.map((e) => (
            <li key={e.id}>
              <button
                onClick={() => setSelectedId(e.id)}
                className={`w-full text-left px-3 py-2 hover:bg-slate-50 ${
                  selectedId === e.id ? "bg-blue-50" : ""
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="truncate">
                    <div className="text-sm font-medium truncate">{e.full_name}</div>
                    <div className="text-xs text-slate-500 truncate">
                      {e.role || e.email || "–"}
                    </div>
                  </div>
                  <div className="flex items-center gap-1 text-xs">
                    {e.status !== "active" && (
                      <span className="text-amber-700 bg-amber-100 px-1.5 py-0.5 rounded text-[10px]">
                        {e.status === "leave" ? "verlof" : "inactief"}
                      </span>
                    )}
                    {e.asset_count > 0 && (
                      <span className="bg-slate-100 px-1.5 py-0.5 rounded tabular-nums">
                        {e.asset_count}
                      </span>
                    )}
                  </div>
                </div>
              </button>
            </li>
          ))}
        </ul>
      </section>

      {/* Detail */}
      <section className="rounded-lg bg-white ring-1 ring-slate-200 overflow-hidden">
        {selectedId === "new" && <EmployeeForm onSaved={(id) => setSelectedId(id)} onCancel={() => setSelectedId(null)} />}
        {selectedId && selectedId !== "new" && <EmployeeDetailPanel employeeId={selectedId} onDeleted={() => setSelectedId(null)} />}
        {!selectedId && (
          <div className="p-8 text-sm text-slate-500 text-center">
            Selecteer links een medewerker of maak een nieuwe aan.
          </div>
        )}
      </section>
    </div>
  );
}

// -------------- Detail panel ------------------------------------------

function EmployeeDetailPanel({ employeeId, onDeleted }: {
  employeeId: string;
  onDeleted: () => void;
}) {
  const qc = useQueryClient();
  const empQ = useQuery<EmployeeDetail>({
    queryKey: ["/inventory/employees", employeeId],
    queryFn: () => api<EmployeeDetail>(`/inventory/employees/${employeeId}`),
  });
  const [editing, setEditing] = useState(false);
  const [addingAsset, setAddingAsset] = useState(false);

  const delMut = useMutation({
    mutationFn: () => api(`/inventory/employees/${employeeId}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({queryKey: ["/inventory/employees"]});
      onDeleted();
    },
  });

  if (empQ.isLoading) return <div className="p-4 text-sm text-slate-500">Laden…</div>;
  if (!empQ.data) return <div className="p-4 text-sm text-rose-700">Niet gevonden</div>;
  const e = empQ.data;

  if (editing) {
    return <EmployeeForm
      employee={e}
      onSaved={() => { setEditing(false); qc.invalidateQueries({queryKey: ["/inventory/employees"]}); qc.invalidateQueries({queryKey: ["/inventory/employees", employeeId]}); }}
      onCancel={() => setEditing(false)}
    />;
  }

  return (
    <div className="h-full flex flex-col">
      <div className="px-4 py-3 border-b border-slate-200 flex items-baseline justify-between gap-2">
        <div>
          <h2 className="text-lg font-medium">{e.full_name}</h2>
          <div className="text-xs text-slate-500">
            {[e.role, e.email, e.phone].filter(Boolean).join(" · ")}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => setEditing(true)} className="text-xs px-2 py-1 rounded ring-1 ring-slate-300 hover:bg-slate-50">Bewerken</button>
          <button onClick={() => { if (confirm(`Medewerker ${e.full_name} + ${e.assets.length} assets verwijderen?`)) delMut.mutate(); }} className="text-xs px-2 py-1 rounded text-rose-700 ring-1 ring-rose-300 hover:bg-rose-50">Verwijderen</button>
        </div>
      </div>

      {e.notes && <div className="px-4 py-2 text-xs text-slate-600 bg-amber-50 border-b border-amber-100">{e.notes}</div>}

      {/* HaloPSA agent matching */}
      <HaloPSAMatchPanel employee={e} />

      <div className="px-4 py-3 border-b border-slate-200 flex items-center justify-between">
        <div className="text-sm font-medium">Assets ({e.assets.length})</div>
        <button onClick={() => setAddingAsset(true)} className="text-xs px-2 py-1 rounded bg-blue-600 text-white hover:bg-blue-700">+ Asset</button>
      </div>

      {addingAsset && (
        <AssetForm employeeId={employeeId} onCancel={() => setAddingAsset(false)} onSaved={() => { setAddingAsset(false); qc.invalidateQueries({queryKey: ["/inventory/employees", employeeId]}); qc.invalidateQueries({queryKey: ["/inventory/employees"]}); }} />
      )}

      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        {e.assets.length === 0 && !addingAsset && (
          <div className="text-sm text-slate-500 text-center p-6">
            Nog geen assets. Klik op "+ Asset" om er een toe te voegen.
          </div>
        )}
        {e.assets.map((a) => (
          <AssetCard key={a.id} asset={a} employeeId={employeeId} />
        ))}
      </div>
    </div>
  );
}

// -------------- Asset card ----------------------------------------

function AssetCard({ asset, employeeId }: { asset: Asset; employeeId: string }) {
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const delMut = useMutation({
    mutationFn: () => api(`/inventory/assets/${asset.id}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({queryKey: ["/inventory/employees", employeeId]});
      qc.invalidateQueries({queryKey: ["/inventory/employees"]});
    },
  });

  if (editing) {
    return <AssetForm
      employeeId={employeeId} asset={asset}
      onCancel={() => setEditing(false)}
      onSaved={() => { setEditing(false); qc.invalidateQueries({queryKey: ["/inventory/employees", employeeId]}); }}
    />;
  }

  const fields = ASSET_FIELDS[asset.asset_type];
  return (
    <div className="rounded-md ring-1 ring-slate-200 bg-slate-50 p-3">
      <div className="flex items-baseline justify-between gap-2">
        <div className="flex items-baseline gap-2">
          <span className="text-xl">{ASSET_TYPE_ICONS[asset.asset_type]}</span>
          <div>
            <div className="text-sm font-medium">{asset.label}</div>
            <div className="text-xs text-slate-500">
              {ASSET_TYPE_LABELS[asset.asset_type]}
              {asset.identifier && <> · {ASSET_IDENTIFIER_LABEL[asset.asset_type]}: <span className="font-mono">{asset.identifier}</span></>}
            </div>
          </div>
        </div>
        <div className="flex gap-1">
          <button onClick={() => setEditing(true)} className="text-xs px-2 py-0.5 rounded ring-1 ring-slate-300 bg-white hover:bg-slate-100">Edit</button>
          <button onClick={() => { if (confirm(`Verwijder ${asset.label}?`)) delMut.mutate(); }} className="text-xs px-2 py-0.5 rounded ring-1 ring-rose-300 bg-white text-rose-700 hover:bg-rose-50">×</button>
        </div>
      </div>
      {fields.some(f => asset.details[f.key] !== undefined && asset.details[f.key] !== "") && (
        <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-0.5 text-xs">
          {fields.map(f => {
            const v = asset.details[f.key];
            if (v === undefined || v === "" || v === null) return null;
            return (
              <div key={f.key}>
                <span className="text-slate-500">{f.label}: </span>
                <span>{String(v)}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// -------------- Forms --------------------------------------------

function EmployeeForm({ employee, onSaved, onCancel }: {
  employee?: Employee;
  onSaved: (id: string) => void;
  onCancel: () => void;
}) {
  const qc = useQueryClient();
  const [form, setForm] = useState({
    full_name: employee?.full_name ?? "",
    email: employee?.email ?? "",
    phone: employee?.phone ?? "",
    role: employee?.role ?? "",
    status: employee?.status ?? "active",
    started_at: employee?.started_at ?? "",
    notes: employee?.notes ?? "",
  });

  const mut = useMutation({
    mutationFn: () => {
      const payload = {
        full_name: form.full_name,
        email: form.email || null,
        phone: form.phone || null,
        role: form.role || null,
        status: form.status,
        started_at: form.started_at || null,
        notes: form.notes || null,
      };
      if (employee) {
        return api<Employee>(`/inventory/employees/${employee.id}`, {
          method: "PUT", body: JSON.stringify(payload),
        });
      }
      return api<Employee>("/inventory/employees", {
        method: "POST", body: JSON.stringify(payload),
      });
    },
    onSuccess: (data) => {
      qc.invalidateQueries({queryKey: ["/inventory/employees"]});
      onSaved(data.id);
    },
  });

  return (
    <div className="p-4 space-y-3">
      <h3 className="text-base font-medium">
        {employee ? "Medewerker bewerken" : "Nieuwe medewerker"}
      </h3>
      <FormRow label="Naam *">
        <input
          value={form.full_name} onChange={(e) => setForm({...form, full_name: e.target.value})}
          className="w-full text-sm rounded border border-slate-300 px-2 py-1"
        />
      </FormRow>
      <div className="grid grid-cols-2 gap-3">
        <FormRow label="E-mail">
          <input type="email" value={form.email} onChange={(e) => setForm({...form, email: e.target.value})}
            className="w-full text-sm rounded border border-slate-300 px-2 py-1"
          />
        </FormRow>
        <FormRow label="Telefoon">
          <input value={form.phone} onChange={(e) => setForm({...form, phone: e.target.value})}
            className="w-full text-sm rounded border border-slate-300 px-2 py-1"
          />
        </FormRow>
        <FormRow label="Functie">
          <input value={form.role} onChange={(e) => setForm({...form, role: e.target.value})}
            className="w-full text-sm rounded border border-slate-300 px-2 py-1"
          />
        </FormRow>
        <FormRow label="Status">
          <select value={form.status} onChange={(e) => setForm({...form, status: e.target.value as "active"|"inactive"|"leave"})}
            className="w-full text-sm rounded border border-slate-300 px-2 py-1"
          >
            <option value="active">Actief</option>
            <option value="leave">Verlof</option>
            <option value="inactive">Inactief</option>
          </select>
        </FormRow>
        <FormRow label="In dienst sinds">
          <input type="date" value={form.started_at} onChange={(e) => setForm({...form, started_at: e.target.value})}
            className="w-full text-sm rounded border border-slate-300 px-2 py-1"
          />
        </FormRow>
      </div>
      <FormRow label="Notities">
        <textarea value={form.notes} onChange={(e) => setForm({...form, notes: e.target.value})}
          rows={3} className="w-full text-sm rounded border border-slate-300 px-2 py-1"
        />
      </FormRow>
      {mut.isError && <div className="text-xs text-rose-700">Fout: {(mut.error as ApiError)?.message || "onbekend"}</div>}
      <div className="flex justify-end gap-2 pt-2">
        <button onClick={onCancel} className="text-sm px-3 py-1 rounded ring-1 ring-slate-300 hover:bg-slate-50">Annuleren</button>
        <button
          onClick={() => mut.mutate()} disabled={!form.full_name || mut.isPending}
          className="text-sm px-3 py-1 rounded bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {mut.isPending ? "Opslaan…" : "Opslaan"}
        </button>
      </div>
    </div>
  );
}

function AssetForm({ employeeId, asset, onCancel, onSaved }: {
  employeeId: string;
  asset?: Asset;
  onCancel: () => void;
  onSaved: () => void;
}) {
  const [type, setType] = useState<AssetType>(asset?.asset_type ?? "laptop");
  const [label, setLabel] = useState(asset?.label ?? "");
  const [identifier, setIdentifier] = useState(asset?.identifier ?? "");
  const [details, setDetails] = useState<Record<string, unknown>>(asset?.details ?? {});
  const [assigned, setAssigned] = useState(asset?.assigned_at ?? "");

  const mut = useMutation({
    mutationFn: () => {
      const payload = {
        asset_type: type, label, identifier: identifier || null,
        details, assigned_at: assigned || null, returned_at: null,
      };
      if (asset) {
        return api(`/inventory/assets/${asset.id}`, { method: "PUT", body: JSON.stringify(payload) });
      }
      return api(`/inventory/employees/${employeeId}/assets`, {
        method: "POST", body: JSON.stringify(payload),
      });
    },
    onSuccess: () => onSaved(),
  });

  const fields = ASSET_FIELDS[type];

  return (
    <div className="m-3 p-3 rounded-md ring-1 ring-blue-200 bg-blue-50 space-y-2">
      <div className="grid grid-cols-2 gap-2">
        <FormRow label="Type">
          <select value={type} onChange={(e) => setType(e.target.value as AssetType)}
            className="w-full text-sm rounded border border-slate-300 px-2 py-1"
          >
            <option value="laptop">Laptop</option>
            <option value="phone">Telefoon</option>
            <option value="vehicle">Auto</option>
            <option value="other">Overig</option>
          </select>
        </FormRow>
        <FormRow label={ASSET_IDENTIFIER_LABEL[type]}>
          <input value={identifier} onChange={(e) => setIdentifier(e.target.value)}
            className="w-full text-sm rounded border border-slate-300 px-2 py-1 font-mono"
          />
        </FormRow>
      </div>
      <FormRow label="Label *">
        <input value={label} onChange={(e) => setLabel(e.target.value)}
          placeholder={type === "vehicle" ? "BMW i4 leaseauto" : type === "phone" ? "iPhone 15 Pro" : type === "laptop" ? "MacBook Pro 16\"" : "Beschrijving"}
          className="w-full text-sm rounded border border-slate-300 px-2 py-1"
        />
      </FormRow>
      <div className="grid grid-cols-2 gap-2">
        {fields.map((f) => (
          <FormRow key={f.key} label={f.label}>
            <input
              type={f.type ?? "text"}
              value={(details[f.key] as string | number) ?? ""}
              onChange={(e) => setDetails({...details, [f.key]: f.type === "number" ? (e.target.value ? Number(e.target.value) : "") : e.target.value})}
              className="w-full text-sm rounded border border-slate-300 px-2 py-1"
            />
          </FormRow>
        ))}
        <FormRow label="Toegewezen op">
          <input type="date" value={assigned} onChange={(e) => setAssigned(e.target.value)}
            className="w-full text-sm rounded border border-slate-300 px-2 py-1"
          />
        </FormRow>
      </div>
      {mut.isError && <div className="text-xs text-rose-700">Fout: {(mut.error as ApiError)?.message || "onbekend"}</div>}
      <div className="flex justify-end gap-2 pt-1">
        <button onClick={onCancel} className="text-xs px-2 py-1 rounded ring-1 ring-slate-300 bg-white hover:bg-slate-100">Annuleren</button>
        <button onClick={() => mut.mutate()} disabled={!label || mut.isPending}
          className="text-xs px-2 py-1 rounded bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {mut.isPending ? "Opslaan…" : "Opslaan"}
        </button>
      </div>
    </div>
  );
}


function HaloPSAMatchPanel({ employee }: { employee: EmployeeDetail }) {
  const qc = useQueryClient();
  const agentsQ = useQuery<HaloPSAAgent[]>({
    queryKey: ["/inventory/halopsa-agents"],
    queryFn: () => api<HaloPSAAgent[]>("/inventory/halopsa-agents"),
    staleTime: 10 * 60 * 1000,
  });

  const linkMut = useMutation({
    mutationFn: (agentId: number | null) =>
      api(`/inventory/employees/${employee.id}/halopsa-link`, {
        method: "PUT",
        body: JSON.stringify({ halopsa_agent_id: agentId }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["/inventory/employees", employee.id] });
      qc.invalidateQueries({ queryKey: ["/inventory/employees"] });
    },
  });

  // Auto-suggest: zoek agent met match op naam (case-insensitive, beide kanten op)
  const agents = agentsQ.data || [];
  const empNameLower = employee.full_name.toLowerCase();
  const suggested = agents.find((a) => {
    const aLower = a.name.toLowerCase();
    return aLower.includes(empNameLower) || empNameLower.includes(aLower.split(" | ")[0]);
  });

  return (
    <div className="px-4 py-3 border-b border-slate-200 bg-amber-50/30">
      <div className="text-[10px] uppercase tracking-wider text-slate-600 font-semibold mb-2">
        HaloPSA-agent voor verlof-sync
      </div>
      {employee.halopsa_agent_id ? (
        <div className="flex items-baseline justify-between gap-2">
          <div className="text-sm">
            <span className="text-emerald-700">✓ Gekoppeld:</span>{" "}
            <strong>{employee.halopsa_agent_name}</strong>
            <span className="text-xs text-slate-500 ml-2">(id {employee.halopsa_agent_id})</span>
          </div>
          <button
            onClick={() => linkMut.mutate(null)}
            disabled={linkMut.isPending}
            className="text-xs px-2 py-0.5 rounded ring-1 ring-slate-300 hover:bg-slate-100"
          >
            Ontkoppelen
          </button>
        </div>
      ) : (
        <div className="space-y-2">
          {agentsQ.isLoading && (
            <div className="text-xs text-slate-500">Agents laden…</div>
          )}
          {agentsQ.data && (
            <>
              <select
                onChange={(ev) => {
                  const v = ev.target.value;
                  if (v) linkMut.mutate(Number(v));
                }}
                className="w-full text-sm rounded border border-slate-300 px-2 py-1"
                defaultValue=""
                disabled={linkMut.isPending}
              >
                <option value="">— Kies HaloPSA-agent —</option>
                {suggested && (
                  <option value={suggested.id}>
                    💡 {suggested.name} (suggestie op naam)
                  </option>
                )}
                <optgroup label="Alle agents">
                  {agents
                    .filter((a) => !suggested || a.id !== suggested.id)
                    .map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.name}
                        {a.inactive ? " (inactief)" : ""}
                        {a.email ? ` — ${a.email}` : ""}
                      </option>
                    ))}
                </optgroup>
              </select>
              <div className="text-xs text-slate-500">
                Nodig voor verlof-doorpush naar Outlook-agenda. Niet alle medewerkers hoeven gekoppeld te zijn — zonder match wordt verlof voor die persoon gewoon overgeslagen.
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function FormRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-0.5">{label}</div>
      {children}
    </label>
  );
}
