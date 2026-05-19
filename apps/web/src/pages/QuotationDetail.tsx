import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

type QuotationLine = {
  id: number | null;
  sort_seq: number | null;
  productcode: string | null;
  name: string;
  description: string;
  quantity: number;
  price: number;
  discount_perc: number;
  total_price: number;
  total_cost: number;
  billingperiod: number | null;
  tax_rate: number | null;
};

type QuotationDetailData = {
  quotation_id: string;
  halopsa_id: number;
  subject: string;
  status: string;
  status_label_halopsa: string | null;
  amount_net: number | null;
  amount_gross: number | null;
  valid_until: string | null;
  sent_at: string | null;
  company_name: string | null;
  halopsa_url: string | null;
  lines: QuotationLine[];
};

const fmtEUR = (v: number | null) =>
  v == null ? "—" : v.toLocaleString("nl-NL", { style: "currency", currency: "EUR" });

const fmtDate = (s: string | null) => {
  if (!s) return "—";
  try {
    return new Date(s).toLocaleDateString("nl-NL", { day: "2-digit", month: "short", year: "numeric" });
  } catch { return s; }
};

const STATUS_LABEL: Record<string, { label: string; bg: string; fg: string }> = {
  draft:    { label: "Concept",  bg: "#F1F5F9", fg: "#475569" },
  sent:     { label: "Verstuurd", bg: "#DBEAFE", fg: "#1E40AF" },
  accepted: { label: "Geaccepteerd", bg: "#DCFCE7", fg: "#15803D" },
  rejected: { label: "Afgewezen", bg: "#FCE7E7", fg: "#9F1239" },
  expired:  { label: "Verlopen",  bg: "#FAEEDA", fg: "#633806" },
  superseded: { label: "Vervallen (revisie)", bg: "#E4E4E7", fg: "#3F3F46" },
};

const billingPeriodLabel = (p: number | null) => {
  if (p == null) return "";
  return ({ 0: "eenmalig", 1: "maand", 2: "kwartaal", 3: "halfjaar", 4: "jaar" } as Record<number, string>)[p] || `period ${p}`;
};

export function QuotationDetail() {
  const { quotationId = "" } = useParams<{ quotationId: string }>();
  const dq = useQuery<QuotationDetailData>({
    queryKey: ["/quotations", quotationId, "lines"],
    queryFn: () => api<QuotationDetailData>(`/quotations/${quotationId}/lines`),
  });

  if (dq.isLoading) return <div className="p-6 text-sm text-slate-500">Offerte ophalen uit HaloPSA…</div>;
  if (dq.isError) {
    return (
      <div className="rounded-md bg-rose-50 border border-rose-200 p-4 text-sm text-rose-900">
        Kon offerte niet ophalen: {(dq.error as Error).message}
        <div className="mt-2"><Link to="/quotations" className="underline">← terug naar offertes</Link></div>
      </div>
    );
  }

  const d = dq.data!;
  const status = STATUS_LABEL[d.status] || STATUS_LABEL.draft;
  const totalLines = d.lines.reduce((s, l) => s + l.total_price, 0);
  const totalCost = d.lines.reduce((s, l) => s + l.total_cost, 0);

  return (
    <div className="space-y-4">
      <div className="rounded-lg bg-white ring-1 ring-slate-200">
        <div className="border-b border-slate-200 px-4 py-3 flex items-baseline justify-between gap-3 flex-wrap">
          <div>
            <div className="flex items-baseline gap-2 flex-wrap">
              <h1 className="text-lg font-medium">{d.subject || "(geen titel)"}</h1>
              <code className="text-xs text-slate-500">HaloPSA #{d.halopsa_id}</code>
              <span className="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium"
                    style={{ backgroundColor: status.bg, color: status.fg }}>{status.label}</span>
            </div>
            <div className="mt-0.5 text-sm text-slate-600">
              {d.company_name || "Onbekende klant"}
            </div>
          </div>
          <div className="flex gap-2">
            {d.halopsa_url && (
              <a href={d.halopsa_url} target="_blank" rel="noopener noreferrer"
                 className="rounded-md bg-slate-100 hover:bg-slate-200 px-3 py-1.5 text-sm">
                Open in HaloPSA ↗
              </a>
            )}
            <Link to="/quotations" className="text-sm text-slate-500 hover:text-slate-800 py-1.5">← terug</Link>
          </div>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 px-4 py-3 text-sm">
          <Field label="Verstuurd" value={fmtDate(d.sent_at)} />
          <Field label="Geldig tot" value={fmtDate(d.valid_until)} />
          <Field label="Bedrag (excl)" value={fmtEUR(d.amount_net)} />
          <Field label="Bedrag (incl)" value={fmtEUR(d.amount_gross)} />
        </div>
      </div>

      <div className="rounded-lg bg-white ring-1 ring-slate-200 overflow-hidden">
        <div className="border-b border-slate-200 px-4 py-2 text-xs uppercase tracking-wider text-slate-500 font-semibold">
          Regels ({d.lines.length})
        </div>
        {d.lines.length === 0 ? (
          <div className="p-8 text-center text-sm text-slate-500">Geen regels in deze offerte.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-[10px] uppercase tracking-wider text-slate-500">
                  <th className="text-left px-4 py-2 w-12">#</th>
                  <th className="text-left px-4 py-2">Omschrijving</th>
                  <th className="text-left px-4 py-2 w-32">Productcode</th>
                  <th className="text-right px-4 py-2 w-20">Aantal</th>
                  <th className="text-right px-4 py-2 w-24">Prijs</th>
                  <th className="text-right px-4 py-2 w-20">Korting</th>
                  <th className="text-left  px-4 py-2 w-24">Frequentie</th>
                  <th className="text-right px-4 py-2 w-28">Totaal</th>
                </tr>
              </thead>
              <tbody>
                {d.lines
                  .slice()
                  .sort((a, b) => (a.sort_seq ?? 0) - (b.sort_seq ?? 0))
                  .map((ln, i) => (
                  <tr key={ln.id || i} className="border-t border-slate-100 hover:bg-slate-50">
                    <td className="px-4 py-2 text-slate-400 text-xs tabular-nums">{ln.sort_seq ?? i + 1}</td>
                    <td className="px-4 py-2">
                      <div className="font-medium">{ln.name}</div>
                      {ln.description && ln.description !== ln.name && (
                        <div className="text-xs text-slate-500 mt-0.5 whitespace-pre-line">{ln.description}</div>
                      )}
                    </td>
                    <td className="px-4 py-2"><code className="text-[11px] text-slate-500">{ln.productcode || "—"}</code></td>
                    <td className="px-4 py-2 text-right tabular-nums">{ln.quantity}</td>
                    <td className="px-4 py-2 text-right tabular-nums">{fmtEUR(ln.price)}</td>
                    <td className="px-4 py-2 text-right tabular-nums">{ln.discount_perc > 0 ? `${ln.discount_perc}%` : "—"}</td>
                    <td className="px-4 py-2 text-xs text-slate-500">{billingPeriodLabel(ln.billingperiod)}</td>
                    <td className="px-4 py-2 text-right tabular-nums font-medium">{fmtEUR(ln.total_price)}</td>
                  </tr>
                ))}
                <tr className="border-t-2 border-slate-300 bg-slate-50">
                  <td colSpan={7} className="px-4 py-2 text-right font-medium">Totaal (excl. BTW)</td>
                  <td className="px-4 py-2 text-right font-bold tabular-nums">{fmtEUR(totalLines)}</td>
                </tr>
                {totalCost > 0 && (
                  <tr className="bg-slate-50">
                    <td colSpan={7} className="px-4 py-2 text-right text-xs text-slate-500">Kostprijs intern</td>
                    <td className="px-4 py-2 text-right text-xs text-slate-500 tabular-nums">{fmtEUR(totalCost)}</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">{label}</div>
      <div className="mt-0.5 text-sm">{value}</div>
    </div>
  );
}

export default QuotationDetail;
