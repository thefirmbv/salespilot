import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

type Summary = {
  total_msps: number;
  msps_with_acquisition: number;
  total_domains: number;
  domains_with_m365: number;
  qualified_leads: number;
  qualified_with_decision_maker: number;
  qualified_within_40km: number;
  qualified_msps_with_recent_acquisition: number;
  avg_km_to_hq: number;
};
type Msp = {
  id: string;
  name: string;
  kvk_number: string | null;
  website: string | null;
  acquired_by: string | null;
  acquired_date: string | null;
  investor: string | null;
  region: string | null;
  source_url: string | null;
  notes: string | null;
  is_active: boolean;
  domain_count: number;
  lead_count: number;
  fingerprint_count: number;
  created_at: string;
  updated_at: string;
};
type Lead = {
  kvk_company_id: string;
  kvk_nummer: string;
  handelsnaam: string;
  rechtsvorm: string | null;
  werkzame_personen: number | null;
  plaats: string | null;
  postcode: string | null;
  km_to_hq: number | null;
  telefoon_bedrijf: string | null;
  domain_id: string | null;
  domain: string | null;
  has_m365: boolean | null;
  m365_tier_hint: string | null;
  msp_id: string | null;
  msp_name: string | null;
  msp_acquired_by: string | null;
  msp_acquired_date: string | null;
  msp_confidence: number | null;
  decision_maker_id: string | null;
  contact_naam: string | null;
  contact_functie: string | null;
  contact_email: string | null;
  contact_email_verified: string | null;
  contact_telefoon: string | null;
  existing_contact_id: string | null;
  in_sequence: boolean;
};
type Signal = {
  id: string;
  source: string;
  source_url: string;
  title: string;
  excerpt: string | null;
  published_at: string | null;
  status: "new" | "confirmed" | "rejected" | "duplicate";
  matched_keywords: string[] | null;
  msp_id: string | null;
  msp_name: string | null;
  notes: string | null;
};
type PipelineRun = {
  id: string;
  job_kind: string;
  status: "running" | "success" | "failed";
  started_at: string;
  finished_at: string | null;
  items_processed: number;
  items_created: number;
  items_failed: number;
  message: string | null;
  duration_seconds: number | null;
};
type PipelineStatus = { jobs: Record<string, PipelineRun | null> };

function fmtDate(iso: string | null): string {
  if (!iso) return "\u2014";
  return new Date(iso).toLocaleDateString("nl-NL", { day: "numeric", month: "short", year: "numeric" });
}
function fmtTime(iso: string | null): string {
  if (!iso) return "\u2014";
  const d = new Date(iso);
  const today = new Date();
  if (d.getDate() === today.getDate() && d.getMonth() === today.getMonth() && d.getFullYear() === today.getFullYear()) {
    return d.toLocaleTimeString("nl-NL", { hour: "2-digit", minute: "2-digit" });
  }
  return d.toLocaleDateString("nl-NL", { day: "numeric", month: "short" });
}

const JOB_LABELS: Record<string, string> = {
  overname_monitor: "Overname-monitor",
  domain_discovery: "Domain discovery",
  m365_scanner: "M365 scanner",
  msp_fingerprint: "MSP fingerprint",
  kvk_geofilter: "KVK + geofilter",
  decision_maker_finder: "Decision-maker finder",
  email_verify: "E-mail verify",
  full_pipeline: "Volledige pipeline",
};
const JOB_ORDER = ["overname_monitor", "domain_discovery", "m365_scanner", "msp_fingerprint", "kvk_geofilter", "decision_maker_finder", "email_verify", "full_pipeline"];

export function Wespennest() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") ?? "dashboard";
  const setTab = (t: string) => {
    const next = new URLSearchParams(params);
    next.set("tab", t);
    setParams(next, { replace: true });
  };
  return (
    <div>
      <div className="overflow-hidden rounded-lg bg-white ring-1 ring-slate-200">
        <div className="border-b border-slate-200 px-4 py-3">
          <h1 className="text-lg font-medium"><span className="mr-1">\ud83d\udc1d</span> Wespennest</h1>
          <div className="mt-0.5 text-xs text-slate-500">
            Acquisitie-engine \u00b7 klanten van overgenomen MSP&apos;s identificeren en benaderen via mail + telefoon
          </div>
        </div>
        <div className="flex gap-1 border-b border-slate-200 px-4">
          {[["dashboard","Dashboard"],["leads","Leads"],["msps","MSP\u2019s"],["feed","Overname-feed"],["pipeline","Pipeline"]].map(([id, label]) => (
            <button key={id} onClick={() => setTab(id)}
              className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium ${tab === id ? "border-brand-500 text-slate-900" : "border-transparent text-slate-500 hover:text-slate-800"}`}>
              {label}
            </button>
          ))}
        </div>
        <div className="p-4">
          {tab === "dashboard" && <DashboardTab />}
          {tab === "leads" && <LeadsTab />}
          {tab === "msps" && <MspsTab />}
          {tab === "feed" && <FeedTab />}
          {tab === "pipeline" && <PipelineTab />}
        </div>
      </div>
    </div>
  );
}

function DashboardTab() {
  const summaryQ = useQuery<Summary>({ queryKey: ["/wespennest/summary"], queryFn: () => api<Summary>("/wespennest/summary") });
  const pipelineQ = useQuery<PipelineStatus>({ queryKey: ["/wespennest/pipeline-status"], queryFn: () => api<PipelineStatus>("/wespennest/pipeline-status") });
  const leadsQ = useQuery<Lead[]>({ queryKey: ["/wespennest/leads", "dashboard"], queryFn: () => api<Lead[]>("/wespennest/leads?has_email=true&max_km=40&limit=10") });
  const s = summaryQ.data;
  const topLeads = leadsQ.data ?? [];
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <KPI label="MSP&apos;s gevolgd" value={String(s?.total_msps ?? 0)} sub={`${s?.msps_with_acquisition ?? 0} met overname-datum`} />
        <KPI label="Gevonden domeinen" value={String(s?.total_domains ?? 0)} sub={`${s?.domains_with_m365 ?? 0} met M365`} />
        <KPI label="Bedrijven (KVK)" value={String(s?.qualified_leads ?? 0)} sub={`${s?.qualified_within_40km ?? 0} binnen 40 km`} tone="emerald" />
        <KPI label="Met decision-maker" value={String(s?.qualified_with_decision_maker ?? 0)} sub="klaar voor outreach" tone={(s?.qualified_with_decision_maker ?? 0) > 0 ? "emerald" : "default"} />
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <div className="rounded-md border border-slate-200 bg-white p-4">
          <div className="mb-3 flex items-center justify-between">
            <div className="text-[10px] uppercase tracking-wider text-slate-500">Pipeline status</div>
            <Link to="?tab=pipeline" className="text-xs text-brand-600 hover:underline">Details &rarr;</Link>
          </div>
          <div className="space-y-1.5">
            {JOB_ORDER.filter((k) => k !== "full_pipeline").map((kind) => {
              const run = pipelineQ.data?.jobs?.[kind] ?? null;
              const tone = run ? (run.status === "success" ? "bg-emerald-50 text-emerald-800" : run.status === "failed" ? "bg-red-50 text-red-800" : "bg-blue-50 text-blue-800") : "bg-slate-100 text-slate-500";
              return (
                <div key={kind} className="flex items-center justify-between text-sm">
                  <span className="truncate">{JOB_LABELS[kind] ?? kind}</span>
                  <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${tone}`}>
                    {run ? `${run.status} \u00b7 ${fmtTime(run.started_at)}` : "nog niet gedraaid"}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
        <div className="rounded-md border border-slate-200 bg-white p-4">
          <div className="mb-3 flex items-center justify-between">
            <div className="text-[10px] uppercase tracking-wider text-slate-500">Top leads (binnen 40 km, met e-mail)</div>
            <Link to="?tab=leads" className="text-xs text-brand-600 hover:underline">Alle leads &rarr;</Link>
          </div>
          {topLeads.length === 0 ? (
            <div className="rounded-md border border-dashed border-slate-300 bg-slate-50 p-4 text-center text-xs text-slate-500">
              Nog geen leads. Activeer eerst de pipeline-jobs of voeg handmatig data toe.
            </div>
          ) : (
            <div className="space-y-1.5">
              {topLeads.slice(0, 8).map((l) => (
                <div key={l.kvk_company_id} className="text-sm">
                  <div className="font-medium truncate">{l.handelsnaam}</div>
                  <div className="text-[11px] text-slate-500">
                    {l.contact_naam ?? "(geen contact)"} \u00b7 {l.km_to_hq?.toFixed(0) ?? "?"} km \u00b7 {l.msp_name ?? "?"}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
      <div className="rounded-md border border-blue-200 bg-blue-50 p-4 text-sm">
        <div className="font-medium text-blue-900">Hoe werkt dit?</div>
        <ol className="mt-2 list-decimal space-y-1 pl-5 text-blue-900">
          <li>Overname-monitor leest RSS van Computable/Dutch IT Channel/Mena/Emerce en vindt nieuwe overnames.</li>
          <li>Per overgenomen MSP zoeken we klant-domeinen via crt.sh + seedlist.</li>
          <li>Elk domein scannen we op M365, mail-config, en MSP-fingerprint.</li>
          <li>Bedrijven verrijken via KVK (basisprofiel + functionarissen) + PDOK geocoding.</li>
          <li>Filter: 20-100 fte, &le;40 km van Breukelen, M365 aanwezig, MSP-confidence &ge;60.</li>
          <li>Decision-maker email genereren (4 NL-patterns) en verifi&euml;ren via SMTP-probe.</li>
          <li>Naar Sequence + Bel-agenda &rarr; nabellen via 3CX.</li>
        </ol>
      </div>
    </div>
  );
}

function MspsTab() {
  const qc = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const mspsQ = useQuery<Msp[]>({ queryKey: ["/wespennest/msps"], queryFn: () => api<Msp[]>("/wespennest/msps") });
  const createMut = useMutation({
    mutationFn: (data: Partial<Msp>) => api<Msp>("/wespennest/msps", { method: "POST", body: JSON.stringify(data) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["/wespennest/msps"] });
      qc.invalidateQueries({ queryKey: ["/wespennest/summary"] });
      setShowForm(false);
    },
  });
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="text-[10px] uppercase tracking-wider text-slate-500">
          Overgenomen MSP&apos;s ({mspsQ.data?.length ?? 0})
        </div>
        <button onClick={() => setShowForm((v) => !v)} className="rounded-md bg-brand-500 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-600">
          {showForm ? "Annuleren" : "+ MSP toevoegen"}
        </button>
      </div>
      {showForm && <MspForm onSubmit={(d) => createMut.mutate(d)} pending={createMut.isPending} />}
      {mspsQ.isLoading && <div className="text-sm text-slate-500">Bezig met laden\u2026</div>}
      {(mspsQ.data ?? []).length > 0 && (
        <div className="overflow-hidden rounded-md border border-slate-200">
          <div className="grid grid-cols-[minmax(0,1.5fr)_minmax(0,1.5fr)_110px_90px_90px_90px] gap-3 bg-slate-50 px-3 py-2 text-[10px] uppercase tracking-wider text-slate-500">
            <div>MSP</div>
            <div>Overgenomen door</div>
            <div>Datum</div>
            <div className="text-right">Fingerprints</div>
            <div className="text-right">Domeinen</div>
            <div className="text-right">Leads</div>
          </div>
          {(mspsQ.data ?? []).map((m) => (
            <div key={m.id} className="grid grid-cols-[minmax(0,1.5fr)_minmax(0,1.5fr)_110px_90px_90px_90px] gap-3 border-t border-slate-100 px-3 py-2 text-sm">
              <div>
                <div className="font-medium">{m.name}</div>
                {m.region && <div className="text-[11px] text-slate-500">{m.region}</div>}
              </div>
              <div>
                <div>{m.acquired_by ?? "\u2014"}</div>
                {m.investor && m.investor !== m.acquired_by && (
                  <div className="text-[11px] text-slate-500">via {m.investor}</div>
                )}
              </div>
              <div className="text-[11px] text-slate-500">{fmtDate(m.acquired_date)}</div>
              <div className="text-right tabular-nums">{m.fingerprint_count}</div>
              <div className="text-right tabular-nums">{m.domain_count}</div>
              <div className="text-right tabular-nums">{m.lead_count}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function MspForm({ onSubmit, pending }: { onSubmit: (d: Partial<Msp>) => void; pending: boolean }) {
  const [name, setName] = useState("");
  const [acquiredBy, setAcquiredBy] = useState("");
  const [acquiredDate, setAcquiredDate] = useState("");
  const [website, setWebsite] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const [notes, setNotes] = useState("");
  return (
    <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
      <div className="grid grid-cols-2 gap-2">
        <FormField label="Naam MSP">
          <input value={name} onChange={(e) => setName(e.target.value)} className="w-full rounded-md border border-slate-300 px-2 py-1 text-sm" />
        </FormField>
        <FormField label="Overgenomen door">
          <input value={acquiredBy} onChange={(e) => setAcquiredBy(e.target.value)} className="w-full rounded-md border border-slate-300 px-2 py-1 text-sm" placeholder="bv. TSH (Strikwerda)" />
        </FormField>
        <FormField label="Overname-datum">
          <input type="date" value={acquiredDate} onChange={(e) => setAcquiredDate(e.target.value)} className="w-full rounded-md border border-slate-300 px-2 py-1 text-sm" />
        </FormField>
        <FormField label="Website">
          <input value={website} onChange={(e) => setWebsite(e.target.value)} placeholder="https://..." className="w-full rounded-md border border-slate-300 px-2 py-1 text-sm" />
        </FormField>
        <FormField label="Bronlink (computable, etc.)">
          <input value={sourceUrl} onChange={(e) => setSourceUrl(e.target.value)} placeholder="https://www.computable.nl/..." className="w-full rounded-md border border-slate-300 px-2 py-1 text-sm" />
        </FormField>
        <FormField label="Notities">
          <input value={notes} onChange={(e) => setNotes(e.target.value)} className="w-full rounded-md border border-slate-300 px-2 py-1 text-sm" />
        </FormField>
      </div>
      <div className="mt-2 flex justify-end">
        <button
          disabled={!name.trim() || pending}
          onClick={() => onSubmit({
            name: name.trim(),
            acquired_by: acquiredBy.trim() || undefined,
            acquired_date: acquiredDate || undefined,
            website: website.trim() || undefined,
            source_url: sourceUrl.trim() || undefined,
            notes: notes.trim() || undefined,
          })}
          className="rounded-md bg-brand-500 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-600 disabled:opacity-50">
          {pending ? "Opslaan\u2026" : "Opslaan"}
        </button>
      </div>
    </div>
  );
}

function FormField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="block text-[11px] text-slate-600 mb-0.5">{label}</span>
      {children}
    </label>
  );
}

function LeadsTab() {
  const qc = useQueryClient();
  const [maxKm, setMaxKm] = useState<number | "">("");
  const [minFte, setMinFte] = useState<number | "">(20);
  const [maxFte, setMaxFte] = useState<number | "">(100);
  const [hasEmail, setHasEmail] = useState<boolean | null>(null);
  const [hasM365, setHasM365] = useState<boolean | null>(null);
  const [search, setSearch] = useState("");
  const params = new URLSearchParams();
  if (maxKm !== "") params.set("max_km", String(maxKm));
  if (minFte !== "") params.set("min_fte", String(minFte));
  if (maxFte !== "") params.set("max_fte", String(maxFte));
  if (hasEmail !== null) params.set("has_email", hasEmail ? "true" : "false");
  if (hasM365 !== null) params.set("has_m365", hasM365 ? "true" : "false");
  params.set("limit", "300");
  const leadsQ = useQuery<Lead[]>({
    queryKey: ["/wespennest/leads", params.toString()],
    queryFn: () => api<Lead[]>(`/wespennest/leads?${params}`),
  });
  const convertMut = useMutation({
    mutationFn: (id: string) => api(`/wespennest/leads/${id}/convert-to-prospect`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["/wespennest/leads"] }),
  });
  const items = (leadsQ.data ?? []).filter((l) => {
    if (!search) return true;
    const t = search.toLowerCase();
    return (l.handelsnaam.toLowerCase().includes(t) || (l.contact_naam ?? "").toLowerCase().includes(t) || (l.msp_name ?? "").toLowerCase().includes(t) || (l.plaats ?? "").toLowerCase().includes(t));
  });
  return (
    <div className="space-y-3">
      <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
        <div className="grid grid-cols-2 gap-2 md:grid-cols-5">
          <FilterField label="Max km">
            <input type="number" min={0} max={500} value={maxKm} onChange={(e) => setMaxKm(e.target.value === "" ? "" : Number(e.target.value))} className="w-full rounded-md border border-slate-300 px-2 py-1 text-sm" placeholder="40" />
          </FilterField>
          <FilterField label="Min fte">
            <input type="number" min={0} value={minFte} onChange={(e) => setMinFte(e.target.value === "" ? "" : Number(e.target.value))} className="w-full rounded-md border border-slate-300 px-2 py-1 text-sm" />
          </FilterField>
          <FilterField label="Max fte">
            <input type="number" min={0} value={maxFte} onChange={(e) => setMaxFte(e.target.value === "" ? "" : Number(e.target.value))} className="w-full rounded-md border border-slate-300 px-2 py-1 text-sm" />
          </FilterField>
          <FilterField label="Heeft M365">
            <select value={hasM365 === null ? "" : hasM365 ? "yes" : "no"} onChange={(e) => setHasM365(e.target.value === "" ? null : e.target.value === "yes")} className="w-full rounded-md border border-slate-300 px-2 py-1 text-sm">
              <option value="">Alles</option><option value="yes">Ja</option><option value="no">Nee</option>
            </select>
          </FilterField>
          <FilterField label="Heeft e-mail">
            <select value={hasEmail === null ? "" : hasEmail ? "yes" : "no"} onChange={(e) => setHasEmail(e.target.value === "" ? null : e.target.value === "yes")} className="w-full rounded-md border border-slate-300 px-2 py-1 text-sm">
              <option value="">Alles</option><option value="yes">Ja</option><option value="no">Nee</option>
            </select>
          </FilterField>
        </div>
        <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Zoek op bedrijf, contact, MSP of plaats\u2026" className="mt-2 w-full rounded-md border border-slate-300 px-2 py-1 text-sm" />
      </div>
      <div className="text-[11px] text-slate-500">{leadsQ.isLoading ? "Bezig met laden\u2026" : `${items.length} leads`}</div>
      {!leadsQ.isLoading && items.length === 0 && (
        <div className="rounded-md border border-dashed border-slate-300 bg-slate-50 p-10 text-center text-sm text-slate-500">
          <div className="text-3xl mb-2">\ud83d\udd0d</div>
          <div className="font-medium text-slate-700">Nog geen leads gevonden</div>
          <div className="mt-1">De pipeline staat klaar maar heeft nog geen data verzameld. Activeer eerst de Python-modules op de Pipeline-tab, of voeg test-data toe via de API.</div>
        </div>
      )}
      {items.map((l) => (<LeadCard key={l.kvk_company_id} lead={l} onConvert={() => convertMut.mutate(l.kvk_company_id)} converting={convertMut.isPending} />))}
    </div>
  );
}

function LeadCard({ lead, onConvert, converting }: { lead: Lead; onConvert: () => void; converting: boolean }) {
  return (
    <div className="rounded-md border border-slate-200 bg-white p-3">
      <div className="grid grid-cols-[minmax(0,2fr)_minmax(0,1.5fr)_180px] gap-3">
        <div className="min-w-0">
          <div className="flex items-baseline gap-2 flex-wrap">
            <div className="truncate font-medium">{lead.handelsnaam}</div>
            {lead.werkzame_personen && <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] text-slate-700">{lead.werkzame_personen} fte</span>}
            {lead.has_m365 === true && <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] text-emerald-800">M365 \u2713</span>}
            {lead.km_to_hq != null && <span className="rounded-full bg-blue-50 px-2 py-0.5 text-[10px] text-blue-800">{lead.km_to_hq.toFixed(0)} km</span>}
          </div>
          <div className="text-[11px] text-slate-500">
            {lead.rechtsvorm && <>{lead.rechtsvorm} \u00b7 </>}{lead.plaats}{lead.domain && <> \u00b7 {lead.domain}</>}
          </div>
          {lead.msp_name && (
            <div className="mt-1 text-[11px] text-amber-900">
              <span className="rounded bg-amber-50 px-1.5 py-0.5">\ud83d\udc1d {lead.msp_name}{lead.msp_acquired_by && lead.msp_acquired_by !== lead.msp_name && <> &rarr; {lead.msp_acquired_by}</>}{lead.msp_acquired_date && <> ({fmtDate(lead.msp_acquired_date)})</>}</span>
            </div>
          )}
        </div>
        <div className="min-w-0 text-sm">
          {lead.contact_naam ? (
            <>
              <div className="font-medium">{lead.contact_naam}</div>
              <div className="text-[11px] text-slate-500">{lead.contact_functie ?? "\u2014"}</div>
              {lead.contact_email && <a href={`mailto:${lead.contact_email}`} className="block text-[11px] text-brand-600 hover:underline truncate">{lead.contact_email} {lead.contact_email_verified === "verified" && <span className="text-emerald-700">\u2713</span>}</a>}
              {lead.contact_telefoon && <a href={`tel:${lead.contact_telefoon}`} className="block text-[11px] text-slate-700 font-mono hover:text-brand-600">{lead.contact_telefoon}</a>}
            </>
          ) : (
            <div className="text-slate-400 text-xs">Geen decision-maker gevonden</div>
          )}
          {lead.telefoon_bedrijf && !lead.contact_telefoon && <a href={`tel:${lead.telefoon_bedrijf}`} className="block text-[11px] text-slate-700 font-mono hover:text-brand-600">\ud83d\udcde {lead.telefoon_bedrijf}</a>}
        </div>
        <div className="flex flex-col gap-1 text-xs">
          {lead.existing_contact_id ? (
            <Link to={`/companies/${lead.existing_contact_id}`} className="rounded-md border border-slate-300 px-2 py-1 text-center hover:bg-slate-50">Bekijk in CRM \u2197</Link>
          ) : (
            <button onClick={onConvert} disabled={converting} className="rounded-md bg-brand-500 px-2 py-1 text-white hover:bg-brand-600 disabled:opacity-50">{converting ? "Bezig\u2026" : "Maak prospect"}</button>
          )}
          {lead.contact_email && <a href={`mailto:${lead.contact_email}`} className="rounded-md border border-slate-300 px-2 py-1 text-center hover:bg-slate-50">\u2709 Mail</a>}
          {(lead.contact_telefoon || lead.telefoon_bedrijf) && <a href={`tel:${lead.contact_telefoon || lead.telefoon_bedrijf}`} className="rounded-md border border-slate-300 px-2 py-1 text-center hover:bg-slate-50">\ud83d\udcde Bel</a>}
        </div>
      </div>
    </div>
  );
}

function FilterField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="block text-[10px] uppercase tracking-wider text-slate-500 mb-0.5">{label}</span>
      {children}
    </label>
  );
}

function FeedTab() {
  const qc = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<string>("new");
  const signalsQ = useQuery<Signal[]>({
    queryKey: ["/wespennest/acquisition-signals", statusFilter],
    queryFn: () => api<Signal[]>(statusFilter ? `/wespennest/acquisition-signals?status=${statusFilter}` : "/wespennest/acquisition-signals"),
  });
  const triggerMut = useMutation({
    mutationFn: () => api("/wespennest/pipeline/overname_monitor/run", { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["/wespennest/acquisition-signals"] }),
  });
  const updateMut = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) =>
      api(`/wespennest/acquisition-signals/${id}`, { method: "PATCH", body: JSON.stringify({ status }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["/wespennest/acquisition-signals"] }),
  });
  const items = signalsQ.data ?? [];
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex gap-1">
          {[["new","Nieuw"],["confirmed","Bevestigd"],["rejected","Afgewezen"],["","Alles"]].map(([id, label]) => (
            <button key={id} onClick={() => setStatusFilter(id)}
              className={`rounded-md px-2.5 py-1 text-xs ${statusFilter === id ? "bg-brand-500 text-white" : "text-slate-600 hover:bg-slate-100"}`}>
              {label}
            </button>
          ))}
        </div>
        <button onClick={() => triggerMut.mutate()} disabled={triggerMut.isPending}
          className="rounded-md border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50 disabled:opacity-50">
          {triggerMut.isPending ? "Bezig\u2026" : "Scan RSS-bronnen"}
        </button>
      </div>
      {signalsQ.isLoading && <div className="text-sm text-slate-500">Bezig met laden\u2026</div>}
      {!signalsQ.isLoading && items.length === 0 && (
        <div className="rounded-md border border-dashed border-slate-300 bg-slate-50 p-10 text-center text-sm text-slate-500">
          <div className="text-3xl mb-2">\ud83d\udcf0</div>
          <div className="font-medium text-slate-700">Geen overname-signalen</div>
          <div className="mt-1">Klik op &laquo;Scan RSS-bronnen&raquo; om Computable, Dutch IT Channel, Mena en Emerce af te zoeken.<br />
            Later wordt dit elke 4 uur automatisch gedaan via Claude.</div>
        </div>
      )}
      {items.map((s) => (
        <div key={s.id} className="rounded-md border border-slate-200 bg-white p-3">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <a href={s.source_url} target="_blank" rel="noreferrer" className="text-sm font-medium hover:text-brand-600">{s.title}</a>
              <div className="text-[11px] text-slate-500">
                {s.source} \u00b7 {fmtDate(s.published_at)}
                {s.matched_keywords && s.matched_keywords.length > 0 && <> \u00b7 {s.matched_keywords.map((k) => `#${k}`).join(" ")}</>}
              </div>
              {s.excerpt && <div className="mt-1 text-xs text-slate-700 line-clamp-2">{s.excerpt}</div>}
            </div>
            <div className="flex gap-1 shrink-0">
              {s.status === "new" && (
                <>
                  <button onClick={() => updateMut.mutate({ id: s.id, status: "confirmed" })}
                    className="rounded-md bg-emerald-50 px-2 py-1 text-[11px] text-emerald-800 hover:bg-emerald-100">
                    Bevestigen
                  </button>
                  <button onClick={() => updateMut.mutate({ id: s.id, status: "rejected" })}
                    className="rounded-md bg-red-50 px-2 py-1 text-[11px] text-red-800 hover:bg-red-100">
                    Afwijzen
                  </button>
                </>
              )}
              <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
                s.status === "confirmed" ? "bg-emerald-50 text-emerald-800" :
                s.status === "rejected" ? "bg-red-50 text-red-800" :
                "bg-slate-100 text-slate-600"
              }`}>{s.status}</span>
            </div>
          </div>
          {s.msp_name && <div className="mt-2 text-[11px] text-slate-500">\ud83d\udc1d Toegevoegd als MSP: {s.msp_name}</div>}
        </div>
      ))}
    </div>
  );
}

function PipelineTab() {
  const qc = useQueryClient();
  const statusQ = useQuery<PipelineStatus>({
    queryKey: ["/wespennest/pipeline-status"],
    queryFn: () => api<PipelineStatus>("/wespennest/pipeline-status"),
    refetchInterval: 5000,
  });
  const runsQ = useQuery<PipelineRun[]>({
    queryKey: ["/wespennest/pipeline-runs"],
    queryFn: () => api<PipelineRun[]>("/wespennest/pipeline-runs?limit=20"),
    refetchInterval: 5000,
  });
  const triggerMut = useMutation({
    mutationFn: (kind: string) => api(`/wespennest/pipeline/${kind}/run`, { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["/wespennest/pipeline-status"] });
      qc.invalidateQueries({ queryKey: ["/wespennest/pipeline-runs"] });
      qc.invalidateQueries({ queryKey: ["/wespennest/summary"] });
    },
  });
  return (
    <div className="space-y-4">
      <div>
        <div className="mb-2 text-[10px] uppercase tracking-wider text-slate-500">Jobs</div>
        <div className="overflow-hidden rounded-md border border-slate-200">
          <div className="grid grid-cols-[minmax(0,1fr)_120px_100px_120px_80px] gap-3 bg-slate-50 px-3 py-2 text-[10px] uppercase tracking-wider text-slate-500">
            <div>Job</div><div>Laatste status</div><div className="text-right">Verwerkt</div><div className="text-right">Duur</div><div></div>
          </div>
          {JOB_ORDER.map((kind) => {
            const run = statusQ.data?.jobs?.[kind] ?? null;
            return (
              <div key={kind} className="grid grid-cols-[minmax(0,1fr)_120px_100px_120px_80px] gap-3 border-t border-slate-100 px-3 py-2 text-sm items-center">
                <div>
                  <div className="font-medium">{JOB_LABELS[kind] ?? kind}</div>
                  {run?.message && <div className="text-[11px] text-slate-500 line-clamp-1">{run.message}</div>}
                </div>
                <div>
                  {run ? (
                    <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
                      run.status === "success" ? "bg-emerald-50 text-emerald-800" :
                      run.status === "failed" ? "bg-red-50 text-red-800" :
                      "bg-blue-50 text-blue-800 animate-pulse"
                    }`}>{run.status}</span>
                  ) : <span className="text-[11px] text-slate-400">nog niet gedraaid</span>}
                </div>
                <div className="text-right tabular-nums text-xs">{run?.items_processed ?? "\u2014"}</div>
                <div className="text-right tabular-nums text-xs text-slate-500">{run?.duration_seconds != null ? `${run.duration_seconds.toFixed(1)}s` : "\u2014"}</div>
                <div className="text-right">
                  <button onClick={() => triggerMut.mutate(kind)} disabled={triggerMut.isPending}
                    className="rounded-md border border-slate-300 px-2 py-0.5 text-[11px] hover:bg-slate-50 disabled:opacity-50">Run</button>
                </div>
              </div>
            );
          })}
        </div>
      </div>
      <div>
        <div className="mb-2 text-[10px] uppercase tracking-wider text-slate-500">Recente runs</div>
        <div className="overflow-hidden rounded-md border border-slate-200">
          {(runsQ.data ?? []).length === 0 && <div className="p-4 text-center text-xs text-slate-500">Nog geen runs.</div>}
          {(runsQ.data ?? []).map((r) => (
            <div key={r.id} className="grid grid-cols-[150px_100px_minmax(0,1fr)_60px_70px] gap-3 border-t border-slate-100 px-3 py-2 text-xs items-center first:border-t-0">
              <div className="text-slate-500">{fmtTime(r.started_at)}</div>
              <div>
                <span className={`rounded-full px-1.5 py-0.5 text-[10px] font-medium ${
                  r.status === "success" ? "bg-emerald-50 text-emerald-800" :
                  r.status === "failed" ? "bg-red-50 text-red-800" :
                  "bg-blue-50 text-blue-800"
                }`}>{r.status}</span>
              </div>
              <div className="truncate">
                <span className="font-medium">{JOB_LABELS[r.job_kind] ?? r.job_kind}</span>
                {r.message && <span className="text-slate-500"> \u00b7 {r.message}</span>}
              </div>
              <div className="text-right tabular-nums">{r.items_processed}</div>
              <div className="text-right tabular-nums text-slate-500">{r.duration_seconds != null ? `${r.duration_seconds.toFixed(1)}s` : "\u2014"}</div>
            </div>
          ))}
        </div>
      </div>
      <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
        <div className="font-medium">Status: stubs actief</div>
        <div className="mt-1">
          De echte scanner-modules (m365_scanner, msp_fingerprint, kvk_geofilter, decision_maker_finder, overname_monitor) staan als stubs ingebouwd. Je kunt al wel job-runs starten om te zien hoe de pipeline werkt. De echte HTTP/DNS-calls worden gevuld zodra de Python-modules zijn gedeployd. Vereisten daarvoor:
          <ul className="mt-1 ml-4 list-disc space-y-0.5">
            <li>KVK API-key + abonnement (\u20ac6,40/mnd + verbruik)</li>
            <li>Uitgaande SMTP poort 25 voor RCPT probe</li>
            <li>2-3 secondary domeinen in Mailgun</li>
          </ul>
        </div>
      </div>
    </div>
  );
}

function KPI({ label, value, sub, tone = "default" }: { label: string; value: string; sub?: string; tone?: "default" | "amber" | "red" | "emerald" }) {
  const toneCls = { default: "text-slate-900", amber: "text-amber-700", red: "text-red-700", emerald: "text-emerald-700" }[tone];
  return (
    <div className="rounded-md border border-slate-200 bg-white p-3">
      <div className="text-[10px] uppercase tracking-wider text-slate-500">{label}</div>
      <div className={`mt-1 text-xl font-medium tabular-nums ${toneCls}`}>{value}</div>
      {sub && <div className="text-[11px] text-slate-500">{sub}</div>}
    </div>
  );
}
