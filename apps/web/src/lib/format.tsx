/** Small UI / format helpers shared by resource pages. */

import type { ReactNode } from "react";

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString();
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

const moneyFmt = new Intl.NumberFormat(undefined, {
  style: "decimal",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

export function fmtMoney(amount: number | null | undefined, currency: string): string {
  if (amount === null || amount === undefined) return "—";
  return `${currency} ${moneyFmt.format(Number(amount))}`;
}

export function dash(value: string | null | undefined): string {
  return value && value.length > 0 ? value : "—";
}

type StatusKind = "open" | "won" | "lost" | string;

export function StatusBadge({ status }: { status: StatusKind }): ReactNode {
  const colors: Record<string, string> = {
    open: "bg-blue-100 text-blue-800",
    won: "bg-green-100 text-green-800",
    lost: "bg-red-100 text-red-700",
  };
  const className = colors[status] ?? "bg-slate-100 text-slate-700";
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${className}`}
    >
      {status}
    </span>
  );
}

const typeColors: Record<string, string> = {
  note: "bg-slate-100 text-slate-700",
  call: "bg-purple-100 text-purple-700",
  email: "bg-sky-100 text-sky-700",
  meeting: "bg-amber-100 text-amber-700",
  task: "bg-emerald-100 text-emerald-700",
};

export function TypeBadge({ type }: { type: string }): ReactNode {
  const className = typeColors[type] ?? "bg-slate-100 text-slate-700";
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${className}`}
    >
      {type}
    </span>
  );
}


const sourceLabels: Record<string, { label: string; cls: string }> = {
  salespilot:     { label: "Prospect",      cls: "bg-slate-100 text-slate-700" },
  halopsa:        { label: "HaloPSA",       cls: "bg-indigo-100 text-indigo-700" },
  halopsa_pushed: { label: "→ HaloPSA",     cls: "bg-emerald-100 text-emerald-700" },
};

export function SourceBadge({ source }: { source: string }): ReactNode {
  const meta = sourceLabels[source] ?? {
    label: source,
    cls: "bg-slate-100 text-slate-700",
  };
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${meta.cls}`}
    >
      {meta.label}
    </span>
  );
}
