import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { api } from "@/lib/api";

type CheckResult = {
  status: string;
  premium?: boolean;
  price?: any;
  reason?: string;
};

export function OpenproviderRegister() {
  const navigate = useNavigate();
  const [step, setStep] = useState<1 | 2 | 3>(1);

  // Step 1: name + availability
  const [name, setName] = useState("");
  const [extension, setExtension] = useState("nl");
  const [period, setPeriod] = useState(1);
  const [autoRenew, setAutoRenew] = useState(true);
  const [check, setCheck] = useState<CheckResult | null>(null);

  // Step 2: contacts + nameservers
  const [ownerHandle, setOwnerHandle] = useState("");
  const [adminHandle, setAdminHandle] = useState("");
  const [techHandle, setTechHandle] = useState("");
  const [billingHandle, setBillingHandle] = useState("");
  const [nameservers, setNameservers] = useState("");
  const [companyId, setCompanyId] = useState("");

  const checkMut = useMutation({
    mutationFn: () =>
      api<CheckResult>("/openprovider/domains/check", {
        method: "POST",
        body: JSON.stringify({ name, extension }),
      }),
    onSuccess: (r) => {
      setCheck(r);
      if (r.status === "free") setStep(2);
    },
  });

  const registerMut = useMutation({
    mutationFn: () =>
      api<{ ok: boolean; domain_id: string }>("/openprovider/domains/register", {
        method: "POST",
        body: JSON.stringify({
          name, extension, period,
          owner_handle: ownerHandle || null,
          admin_handle: adminHandle || null,
          tech_handle: techHandle || null,
          billing_handle: billingHandle || null,
          name_servers: nameservers ? nameservers.split(/[\s,]+/).filter(Boolean) : null,
          auto_renew: autoRenew,
          confirm_premium: check?.premium || false,
          company_id: companyId || null,
        }),
      }),
    onSuccess: (r) => {
      alert(`✓ Domein geregistreerd! ID: ${r.domain_id}`);
      navigate("/openprovider?tab=domains");
    },
    onError: (e: Error) => alert("Registratie mislukt: " + e.message),
  });

  return (
    <div className="space-y-4 max-w-3xl">
      <div className="rounded-lg bg-white ring-1 ring-slate-200 p-4">
        <div className="flex items-baseline justify-between">
          <h1 className="text-lg font-medium">Nieuw domein registreren</h1>
          <Link to="/openprovider" className="text-sm text-slate-500 hover:underline">← terug</Link>
        </div>
        <div className="mt-3 flex items-center gap-2 text-xs">
          {[1, 2, 3].map((n) => (
            <div key={n} className={`px-2 py-0.5 rounded-full ${step === n ? "bg-brand-500 text-white" : step > n ? "bg-emerald-100 text-emerald-800" : "bg-slate-100 text-slate-500"}`}>
              {n}. {n === 1 ? "Beschikbaarheid" : n === 2 ? "Contact + NS" : "Bevestigen"}
            </div>
          ))}
        </div>
      </div>

      {step === 1 && (
        <div className="rounded-lg bg-white ring-1 ring-slate-200 p-4 space-y-4">
          <div className="grid grid-cols-[1fr_120px] gap-3">
            <div>
              <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1">Domein-naam (zonder extensie)</label>
              <input value={name} onChange={(e) => setName(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, ""))}
                placeholder="bv. mijn-bedrijf"
                className="w-full rounded border border-slate-300 px-2 py-1.5 text-sm" />
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1">Extensie</label>
              <select value={extension} onChange={(e) => setExtension(e.target.value)}
                className="w-full rounded border border-slate-300 px-2 py-1.5 text-sm bg-white">
                {["nl", "com", "net", "eu", "be", "de", "io", "co"].map(e => <option key={e}>{e}</option>)}
              </select>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1">Periode (jaren)</label>
              <select value={period} onChange={(e) => setPeriod(Number(e.target.value))}
                className="w-full rounded border border-slate-300 px-2 py-1.5 text-sm bg-white">
                {[1, 2, 3, 5, 10].map(n => <option key={n} value={n}>{n}</option>)}
              </select>
            </div>
            <label className="flex items-center gap-2 text-sm mt-6">
              <input type="checkbox" checked={autoRenew} onChange={(e) => setAutoRenew(e.target.checked)} />
              Auto-renew aan
            </label>
          </div>
          <button onClick={() => checkMut.mutate()} disabled={!name || checkMut.isPending}
            className="rounded-md bg-brand-500 hover:bg-brand-600 text-white px-4 py-2 text-sm disabled:opacity-50">
            {checkMut.isPending ? "Bezig…" : `Check beschikbaarheid van ${name || "..."}.${extension}`}
          </button>

          {check && check.status !== "free" && (
            <div className="rounded bg-rose-50 border border-rose-200 p-3 text-sm">
              <strong>Niet beschikbaar.</strong> Status: <code>{check.status}</code>
              {check.reason && <div className="text-xs mt-1">{check.reason}</div>}
            </div>
          )}
          {check?.premium && (
            <div className="rounded bg-amber-50 border border-amber-300 p-3 text-sm">
              <strong>⚠ Premium-domein.</strong> Prijs: {JSON.stringify(check.price)}.
              Je moet expliciet bevestigen in stap 3.
            </div>
          )}
          {check?.status === "free" && (
            <div className="rounded bg-emerald-50 border border-emerald-200 p-3 text-sm">
              <strong>✓ Beschikbaar!</strong> Klik door naar stap 2.
              <button onClick={() => setStep(2)} className="ml-2 text-emerald-700 underline">Volgende →</button>
            </div>
          )}
        </div>
      )}

      {step === 2 && (
        <div className="rounded-lg bg-white ring-1 ring-slate-200 p-4 space-y-3">
          <div className="text-sm text-slate-600">
            Vul je Openprovider contact-handles in (bestaande handles). Eén handle voor alle 4 rollen mag.
          </div>
          <Field label="Owner handle *" value={ownerHandle} onChange={setOwnerHandle} placeholder="ITG000001-NL" />
          <Field label="Admin handle (leeg = owner)" value={adminHandle} onChange={setAdminHandle} />
          <Field label="Tech handle (leeg = owner)" value={techHandle} onChange={setTechHandle} />
          <Field label="Billing handle (leeg = owner)" value={billingHandle} onChange={setBillingHandle} />
          <div>
            <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1">
              Nameservers (1 per regel of komma-gescheiden, leeg = Openprovider defaults)
            </label>
            <textarea value={nameservers} onChange={(e) => setNameservers(e.target.value)} rows={3}
              placeholder="ns1.cloudflare.com&#10;ns2.cloudflare.com"
              className="w-full rounded border border-slate-300 px-2 py-1.5 text-sm font-mono" />
          </div>
          <Field label="SalesPilot company ID (optioneel)" value={companyId} onChange={setCompanyId}
            placeholder="leave blank, link later" />
          <div className="flex gap-2 justify-between">
            <button onClick={() => setStep(1)} className="rounded bg-slate-100 hover:bg-slate-200 px-3 py-1.5 text-sm">← Terug</button>
            <button onClick={() => setStep(3)} disabled={!ownerHandle}
              className="rounded bg-brand-500 hover:bg-brand-600 text-white px-3 py-1.5 text-sm disabled:opacity-50">
              Volgende: bevestigen →
            </button>
          </div>
        </div>
      )}

      {step === 3 && (
        <div className="rounded-lg bg-white ring-1 ring-slate-200 p-4 space-y-3">
          <div className="text-base font-medium">Bevestig registratie</div>
          <div className="rounded-md bg-slate-50 p-3 text-sm space-y-1">
            <div><strong>Domein:</strong> {name}.{extension}</div>
            <div><strong>Periode:</strong> {period} jaar</div>
            <div><strong>Auto-renew:</strong> {autoRenew ? "Ja" : "Nee"}</div>
            <div><strong>Owner:</strong> {ownerHandle}</div>
            <div><strong>Nameservers:</strong> {nameservers || "(Openprovider defaults)"}</div>
            {check?.premium && <div className="text-amber-700"><strong>⚠ PREMIUM:</strong> {JSON.stringify(check.price)}</div>}
          </div>
          <div className="rounded-md bg-rose-50 border border-rose-200 p-3 text-sm text-rose-900">
            <strong>Let op:</strong> deze actie kost geld. Registratie wordt onmiddellijk
            uitgevoerd bij Openprovider en gefactureerd op jouw Openprovider-account.
          </div>
          <div className="flex gap-2 justify-between">
            <button onClick={() => setStep(2)} className="rounded bg-slate-100 hover:bg-slate-200 px-3 py-1.5 text-sm">← Terug</button>
            <button
              onClick={() => {
                if (confirm(`Domein ${name}.${extension} registreren voor ${period} jaar. Dit kost geld. Doorgaan?`)) {
                  registerMut.mutate();
                }
              }}
              disabled={registerMut.isPending}
              className="rounded bg-rose-600 hover:bg-rose-700 text-white px-4 py-2 text-sm font-medium disabled:opacity-50"
            >
              {registerMut.isPending ? "Bezig…" : `Registreer ${name}.${extension}`}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function Field({ label, value, onChange, placeholder }: any) {
  return (
    <div>
      <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1">{label}</label>
      <input value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder}
        className="w-full rounded border border-slate-300 px-2 py-1.5 text-sm" />
    </div>
  );
}

export default OpenproviderRegister;
