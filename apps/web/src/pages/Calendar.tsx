import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";

type EventPublic = {
  id: string;
  title: string;
  notes: string | null;
  kind: string;
  color_hex: string | null;
  start_at: string;
  end_at: string;
  all_day: boolean;
  location: string | null;
  recurrence_template_id: string | null;
  outlook_event_id: string | null;
  reflection_outcome: "green" | "yellow" | "red" | null;
  reflection_note: string | null;
};

type RecurrencePublic = {
  id: string;
  title: string;
  kind: string;
  weekdays: number[];
  weekdays_label: string;
  start_time: string;
  end_time: string;
  is_active: boolean;
};

type DaySummary = {
  date: string;
  total_events: number;
  reflected: number;
  green: number;
  yellow: number;
  red: number;
  streak_green_days: number;
};

type ImportResult = {
  created: RecurrencePublic[];
  errors: { line: string; reason: string }[];
  materialized_event_count: number;
};

const KIND_COLORS: Record<string, { bg: string; border: string; text: string }> = {
  focus:    { bg: "#EEF2FF", border: "#6366F1", text: "#3730A3" },
  meeting:  { bg: "#FCE7F3", border: "#EC4899", text: "#9D174D" },
  client:   { bg: "#FEF3C7", border: "#F59E0B", text: "#92400E" },
  admin:    { bg: "#E0E7FF", border: "#4F46E5", text: "#3730A3" },
  break:    { bg: "#D1FAE5", border: "#10B981", text: "#065F46" },
  personal: { bg: "#FCE7F3", border: "#DB2777", text: "#831843" },
  other:    { bg: "#F1F5F9", border: "#64748B", text: "#334155" },
};

const KIND_LABELS: Record<string, string> = {
  focus: "Focus", meeting: "Overleg", client: "Klant",
  admin: "Admin", break: "Pauze", personal: "Privé", other: "Anders",
};

function fmtDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function fmtTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString("nl-NL", { hour: "2-digit", minute: "2-digit" });
}

function startOfWeek(d: Date): Date {
  const out = new Date(d);
  const day = (out.getDay() + 6) % 7; // ma=0
  out.setDate(out.getDate() - day);
  out.setHours(0, 0, 0, 0);
  return out;
}

function addDays(d: Date, n: number): Date {
  const out = new Date(d);
  out.setDate(out.getDate() + n);
  return out;
}

function sameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

export function Calendar() {
  const [anchor, setAnchor] = useState<Date>(() => startOfWeek(new Date()));
  const [view, setView] = useState<"week" | "day">(window.innerWidth < 768 ? "day" : "week");
  const [showImport, setShowImport] = useState(false);
  const [reflectingEvent, setReflectingEvent] = useState<EventPublic | null>(null);

  const weekStart = view === "week" ? anchor : new Date(anchor);
  if (view === "day") weekStart.setHours(0, 0, 0, 0);
  const weekEnd = view === "week" ? addDays(anchor, 6) : anchor;

  const eventsQ = useQuery<EventPublic[]>({
    queryKey: ["/calendar/events", fmtDate(weekStart), fmtDate(weekEnd)],
    queryFn: () => api<EventPublic[]>(
      `/calendar/events?from_=${fmtDate(weekStart)}&to=${fmtDate(weekEnd)}`,
    ),
  });

  const summaryQ = useQuery<DaySummary>({
    queryKey: ["/calendar/day-summary"],
    queryFn: () => api<DaySummary>("/calendar/day-summary"),
    refetchInterval: 60_000,
  });

  const recurrencesQ = useQuery<RecurrencePublic[]>({
    queryKey: ["/calendar/recurrences"],
    queryFn: () => api<RecurrencePublic[]>("/calendar/recurrences"),
  });

  const days = useMemo(() => {
    const result: Date[] = [];
    const count = view === "week" ? 7 : 1;
    for (let i = 0; i < count; i++) result.push(addDays(weekStart, i));
    return result;
  }, [weekStart, view]);

  const eventsByDay = useMemo(() => {
    const map = new Map<string, EventPublic[]>();
    for (const e of eventsQ.data ?? []) {
      const key = fmtDate(new Date(e.start_at));
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(e);
    }
    return map;
  }, [eventsQ.data]);


  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Mijn agenda</h1>
          <p className="mt-1 text-sm text-slate-500">
            Vaste patronen, één-klik reflectie, en streak-zicht — gemaakt voor wie structuur fijn vindt.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button onClick={() => setShowImport(true)}
            className="rounded-md bg-brand-500 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-600">
            📓 Importeer uit boekje
          </button>
        </div>
      </div>

      {/* Streak / day summary strip */}
      {summaryQ.data && (
        <div className="flex flex-wrap gap-2 rounded-lg bg-white ring-1 ring-slate-200 p-3">
          <SummaryPill label="Vandaag" value={`${summaryQ.data.total_events} blokken`} />
          <SummaryPill label="Gelogd" value={`${summaryQ.data.reflected} / ${summaryQ.data.total_events}`} />
          {summaryQ.data.green > 0 && <SummaryPill label="🟢 Goed" value={String(summaryQ.data.green)} tone="green" />}
          {summaryQ.data.yellow > 0 && <SummaryPill label="🟡 Lastig" value={String(summaryQ.data.yellow)} tone="yellow" />}
          {summaryQ.data.red > 0 && <SummaryPill label="🔴 Niet gelukt" value={String(summaryQ.data.red)} tone="red" />}
          {summaryQ.data.streak_green_days >= 2 && (
            <SummaryPill label="🔥 Reeks" value={`${summaryQ.data.streak_green_days} dagen op rij`} tone="green" />
          )}
        </div>
      )}

      {/* Navigation */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <button onClick={() => setAnchor(addDays(anchor, view === "week" ? -7 : -1))}
            className="rounded-md border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50">‹</button>
          <button onClick={() => setAnchor(startOfWeek(new Date()))}
            className="rounded-md border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50">Vandaag</button>
          <button onClick={() => setAnchor(addDays(anchor, view === "week" ? 7 : 1))}
            className="rounded-md border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50">›</button>
          <span className="ml-2 text-sm font-medium text-slate-700">
            {view === "week"
              ? `${weekStart.toLocaleDateString("nl-NL", { day: "numeric", month: "short" })} – ${weekEnd.toLocaleDateString("nl-NL", { day: "numeric", month: "short" })}`
              : weekStart.toLocaleDateString("nl-NL", { weekday: "long", day: "numeric", month: "long" })}
          </span>
        </div>
        <div className="flex rounded-md ring-1 ring-slate-200 overflow-hidden text-sm">
          <button onClick={() => setView("day")}
            className={`px-3 py-1.5 ${view === "day" ? "bg-brand-500 text-white" : "bg-white text-slate-700 hover:bg-slate-50"}`}>Dag</button>
          <button onClick={() => setView("week")}
            className={`px-3 py-1.5 ${view === "week" ? "bg-brand-500 text-white" : "bg-white text-slate-700 hover:bg-slate-50"}`}>Week</button>
        </div>
      </div>

      {/* Day/week grid */}
      <div className="rounded-lg bg-white ring-1 ring-slate-200 overflow-hidden">
        {eventsQ.isLoading && <div className="p-6 text-sm text-slate-500">Bezig met laden…</div>}
        {!eventsQ.isLoading && (
          <div className={view === "week"
            ? "grid grid-cols-1 md:grid-cols-7 divide-y md:divide-y-0 md:divide-x divide-slate-200"
            : "block"
          }>
            {days.map((d) => {
              const key = fmtDate(d);
              const dayEvents = eventsByDay.get(key) ?? [];
              const isToday = sameDay(d, new Date());
              return (
                <div key={key} className={`min-h-[140px] ${isToday ? "bg-amber-50/30" : ""}`}>
                  <div className={`sticky top-0 z-10 border-b border-slate-200 px-3 py-2 text-xs font-medium ${isToday ? "bg-amber-100 text-amber-900" : "bg-slate-50 text-slate-700"}`}>
                    {d.toLocaleDateString("nl-NL", { weekday: "short", day: "numeric", month: "short" })}
                    {isToday && <span className="ml-1 text-[10px] uppercase tracking-wider">Vandaag</span>}
                  </div>
                  <div className="p-2 space-y-1">
                    {dayEvents.length === 0 && (
                      <div className="text-xs text-slate-400 italic p-2">Geen blokken</div>
                    )}
                    {dayEvents.map((e) => (
                      <EventCard key={e.id} event={e} onReflect={() => setReflectingEvent(e)} />
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Recurrence templates list */}
      {recurrencesQ.data && recurrencesQ.data.length > 0 && (
        <div className="rounded-lg bg-white ring-1 ring-slate-200">
          <div className="border-b border-slate-200 px-4 py-3">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-600">Vaste patronen</h2>
            <p className="text-xs text-slate-500 mt-1">Deze blokken plannen we automatisch elke week voor je in.</p>
          </div>
          <ul className="divide-y divide-slate-100">
            {recurrencesQ.data.map((r) => {
              const c = KIND_COLORS[r.kind] || KIND_COLORS.other;
              return (
                <li key={r.id} className="flex items-center gap-3 px-4 py-2.5">
                  <span className="inline-block w-1.5 h-8 rounded" style={{ background: c.border }}></span>
                  <div className="flex-1 min-w-0">
                    <div className="flex flex-wrap items-baseline gap-2">
                      <span className="font-medium">{r.title}</span>
                      <span className="inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium"
                        style={{ background: c.bg, color: c.text }}>
                        {KIND_LABELS[r.kind] ?? r.kind}
                      </span>
                    </div>
                    <div className="text-xs text-slate-500">{r.weekdays_label} · {r.start_time.slice(0, 5)}–{r.end_time.slice(0, 5)}</div>
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {showImport && <ImportModal onClose={() => setShowImport(false)} />}
      {reflectingEvent && <ReflectionModal event={reflectingEvent} onClose={() => setReflectingEvent(null)} />}
    </div>
  );
}

function SummaryPill({ label, value, tone = "default" }: { label: string; value: string; tone?: "default" | "green" | "yellow" | "red" }) {
  const cls = tone === "green" ? "bg-emerald-50 text-emerald-800"
    : tone === "yellow" ? "bg-amber-50 text-amber-800"
    : tone === "red" ? "bg-red-50 text-red-800"
    : "bg-slate-100 text-slate-700";
  return (
    <div className={`inline-flex items-center gap-2 rounded-md px-3 py-1.5 text-sm ${cls}`}>
      <span className="font-medium">{value}</span>
      <span className="text-xs opacity-75">{label}</span>
    </div>
  );
}

function EventCard({ event, onReflect }: { event: EventPublic; onReflect: () => void }) {
  const c = KIND_COLORS[event.kind] || KIND_COLORS.other;
  const past = new Date(event.end_at) < new Date();

  return (
    <div
      className="rounded-md border-l-4 px-2 py-1.5 cursor-pointer hover:shadow-sm transition"
      style={{ background: c.bg, borderLeftColor: c.border, color: c.text }}
      onClick={onReflect}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="font-medium text-sm truncate">{event.title}</div>
        {event.reflection_outcome && (
          <span className="shrink-0 text-base leading-none">
            {event.reflection_outcome === "green" ? "🟢" : event.reflection_outcome === "yellow" ? "🟡" : "🔴"}
          </span>
        )}
      </div>
      <div className="text-xs opacity-75 tabular-nums">{fmtTime(event.start_at)}–{fmtTime(event.end_at)}</div>
      {past && !event.reflection_outcome && (
        <div className="text-[10px] mt-0.5 opacity-60 italic">Tik om te loggen</div>
      )}
      {event.reflection_note && <div className="text-[11px] mt-1 italic opacity-80">{event.reflection_note}</div>}
    </div>
  );
}

function ImportModal({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const [weeks, setWeeks] = useState(4);
  const [result, setResult] = useState<ImportResult | null>(null);

  const importMut = useMutation({
    mutationFn: () => api<ImportResult>("/calendar/recurrences/import", {
      method: "POST",
      body: JSON.stringify({ text, auto_materialize_weeks: weeks }),
    }),
    onSuccess: (r) => {
      setResult(r);
      qc.invalidateQueries({ queryKey: ["/calendar/recurrences"] });
      qc.invalidateQueries({ queryKey: ["/calendar/events"] });
    },
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4" onClick={onClose}>
      <div className="w-full max-w-xl rounded-lg bg-white shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
          <h2 className="text-base font-semibold">Patronen uit boekje</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700 text-xl">×</button>
        </div>
        <div className="p-4 space-y-3 max-h-[70vh] overflow-y-auto">
          {!result ? (
            <>
              <p className="text-sm text-slate-600">
                Schrijf één blok per regel in vrije tekst — wij maken er herhaal-afspraken van.
              </p>
              <div className="rounded-md bg-slate-50 p-3 text-xs text-slate-600">
                <div className="font-medium mb-1">Voorbeelden:</div>
                <code className="block">Elke maandag 9:00-9:30 standup</code>
                <code className="block">Doordeweeks 8:30 ochtendcheck 15 min</code>
                <code className="block">Dinsdag en donderdag 13-15 deep work</code>
                <code className="block">Vrijdag 16:00 weekreview 30 minuten</code>
                <code className="block">Ma wo vr 17:00-17:15 dagafsluiting</code>
              </div>
              <textarea
                value={text} onChange={(e) => setText(e.target.value)}
                rows={10} placeholder="Eén blok per regel…"
                className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-brand-500"
              />
              <label className="flex items-center gap-2 text-sm">
                <span>Plan vooruit voor</span>
                <input type="number" min={1} max={12} value={weeks}
                  onChange={(e) => setWeeks(Math.max(1, Math.min(12, +e.target.value || 1)))}
                  className="w-16 rounded border border-slate-300 px-2 py-1" />
                <span>weken</span>
              </label>
              {importMut.error && (
                <div className="rounded bg-red-50 px-3 py-2 text-sm text-red-700">
                  {importMut.error instanceof ApiError ? importMut.error.detail : "Er ging iets mis."}
                </div>
              )}
            </>
          ) : (
            <>
              <div className="rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
                ✅ <strong>{result.created.length} patronen</strong> aangemaakt — <strong>{result.materialized_event_count} afspraken</strong> ingepland.
              </div>
              {result.errors.length > 0 && (
                <div className="rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-900">
                  <div className="font-medium mb-1">⚠ Niet kunnen plaatsen:</div>
                  <ul className="text-xs space-y-1">
                    {result.errors.map((e, i) => (
                      <li key={i}><code className="font-mono">{e.line}</code> — <em>{e.reason}</em></li>
                    ))}
                  </ul>
                </div>
              )}
              <ul className="text-xs space-y-1">
                {result.created.map((c) => (
                  <li key={c.id}>✓ {c.weekdays_label} {c.start_time.slice(0, 5)}–{c.end_time.slice(0, 5)} — {c.title}</li>
                ))}
              </ul>
            </>
          )}
        </div>
        <div className="flex justify-end gap-2 border-t border-slate-200 px-4 py-3">
          {result ? (
            <button onClick={onClose} className="rounded-md bg-brand-500 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-600">Klaar</button>
          ) : (
            <>
              <button onClick={onClose} className="rounded-md border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50">Annuleren</button>
              <button onClick={() => importMut.mutate()} disabled={!text.trim() || importMut.isPending}
                className="rounded-md bg-brand-500 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-600 disabled:opacity-50">
                {importMut.isPending ? "Bezig…" : "Importeren"}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function ReflectionModal({ event, onClose }: { event: EventPublic; onClose: () => void }) {
  const qc = useQueryClient();
  const [outcome, setOutcome] = useState<"green" | "yellow" | "red" | null>(event.reflection_outcome);
  const [note, setNote] = useState(event.reflection_note ?? "");

  const saveMut = useMutation({
    mutationFn: () => api(`/calendar/events/${event.id}/reflection`, {
      method: "PUT",
      body: JSON.stringify({ outcome, note: note || null }),
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["/calendar/events"] });
      qc.invalidateQueries({ queryKey: ["/calendar/day-summary"] });
      onClose();
    },
  });

  const clearMut = useMutation({
    mutationFn: () => api(`/calendar/events/${event.id}/reflection`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["/calendar/events"] });
      qc.invalidateQueries({ queryKey: ["/calendar/day-summary"] });
      onClose();
    },
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4" onClick={onClose}>
      <div className="w-full max-w-md rounded-lg bg-white shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
          <div>
            <div className="text-[10px] uppercase tracking-wider text-slate-500">Hoe ging dit blok?</div>
            <h2 className="text-base font-semibold">{event.title}</h2>
            <div className="text-xs text-slate-500">{fmtTime(event.start_at)}–{fmtTime(event.end_at)}</div>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700 text-xl">×</button>
        </div>
        <div className="p-4 space-y-3">
          <div className="grid grid-cols-3 gap-2">
            {([
              ["green", "🟢", "Ging goed"],
              ["yellow", "🟡", "Was lastig"],
              ["red", "🔴", "Niet gelukt"],
            ] as const).map(([v, emoji, label]) => (
              <button key={v}
                onClick={() => setOutcome(v)}
                className={`rounded-lg border-2 p-3 text-center transition ${
                  outcome === v ? "border-brand-500 bg-brand-50" : "border-slate-200 hover:border-slate-300"
                }`}>
                <div className="text-3xl">{emoji}</div>
                <div className="text-xs mt-1">{label}</div>
              </button>
            ))}
          </div>
          <label className="block">
            <span className="block text-[11px] uppercase tracking-wider text-slate-500 mb-1">Eén zin (optioneel)</span>
            <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2}
              placeholder="bv. Onverwacht telefoontje halverwege"
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm" />
          </label>
        </div>
        <div className="flex justify-between gap-2 border-t border-slate-200 px-4 py-3">
          {event.reflection_outcome && (
            <button onClick={() => clearMut.mutate()} disabled={clearMut.isPending}
              className="text-sm text-slate-500 hover:text-slate-700">Wissen</button>
          )}
          <div className="flex gap-2 ml-auto">
            <button onClick={onClose} className="rounded-md border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50">Annuleren</button>
            <button onClick={() => saveMut.mutate()} disabled={!outcome || saveMut.isPending}
              className="rounded-md bg-brand-500 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-600 disabled:opacity-50">
              {saveMut.isPending ? "Bezig…" : "Opslaan"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
