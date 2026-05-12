/** Slide-over dialog used for New / Edit forms.
 *
 *  Schema-driven: pass an array of FieldSpec and `FormDialog` renders them
 *  using sensible defaults per type. Submit calls the provided `onSubmit`
 *  with a plain object of values.
 *
 *  Keeping all field types in one file (rather than per-type components)
 *  trades a slightly longer file for far less file-jumping when adjusting
 *  layout, validation, or styling later.
 */

import { useEffect, useState, type ReactNode } from "react";

export type FieldSpec =
  | { name: string; label: string; type: "text" | "email" | "tel" | "url"; placeholder?: string; required?: boolean }
  | { name: string; label: string; type: "number"; min?: number; max?: number; step?: number; required?: boolean }
  | { name: string; label: string; type: "textarea"; rows?: number; required?: boolean }
  | { name: string; label: string; type: "date"; required?: boolean }
  | { name: string; label: string; type: "datetime"; required?: boolean }
  | { name: string; label: string; type: "select"; options: { value: string; label: string }[]; required?: boolean }
  | { name: string; label: string; type: "select-async"; loadOptions: () => Promise<{ value: string; label: string }[]>; required?: boolean }
  | { name: string; label: string; type: "hidden" };

export type FormValues = Record<string, unknown>;

type Props = {
  open: boolean;
  onClose: () => void;
  title: string;
  fields: FieldSpec[];
  /** Pre-fill values (edit mode). Use {} for create. */
  initialValues?: FormValues;
  onSubmit: (values: FormValues) => Promise<void>;
  submitLabel?: string;
};

export function FormDialog({
  open,
  onClose,
  title,
  fields,
  initialValues = {},
  onSubmit,
  submitLabel = "Save",
}: Props) {
  const [values, setValues] = useState<FormValues>(initialValues);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Reset state when the dialog opens (or initialValues change).
  useEffect(() => {
    if (open) {
      setValues(initialValues);
      setError(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  if (!open) return null;

  function update(name: string, value: unknown): void {
    setValues((prev) => ({ ...prev, [name]: value }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      // Drop empty strings — let the API treat them as omitted.
      const clean: FormValues = {};
      for (const [k, v] of Object.entries(values)) {
        if (v === "" || v === undefined) continue;
        clean[k] = v;
      }
      await onSubmit(clean);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "save failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex">
      {/* backdrop */}
      <div
        className="flex-1 bg-slate-900/40"
        onClick={() => !busy && onClose()}
      />
      {/* panel */}
      <form
        onSubmit={handleSubmit}
        className="flex w-full max-w-md flex-col bg-white shadow-xl"
      >
        <div className="flex items-center justify-between border-b border-slate-200 px-6 py-4">
          <h2 className="text-lg font-semibold">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="text-slate-400 hover:text-slate-700 disabled:opacity-50"
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        <div className="flex-1 space-y-4 overflow-auto px-6 py-5">
          {fields.map((f) => (
            <FieldRow
              key={f.name}
              spec={f}
              value={values[f.name]}
              onChange={(v) => update(f.name, v)}
            />
          ))}
          {error && <div className="text-sm text-red-600">{error}</div>}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-slate-200 bg-slate-50 px-6 py-4">
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="rounded-md bg-white px-3 py-1.5 text-sm font-medium text-slate-700 ring-1 ring-slate-300 hover:bg-slate-100 disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={busy}
            className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
          >
            {busy ? "Saving…" : submitLabel}
          </button>
        </div>
      </form>
    </div>
  );
}

type FieldRowProps = {
  spec: FieldSpec;
  value: unknown;
  onChange: (v: unknown) => void;
};

function FieldRow({ spec, value, onChange }: FieldRowProps): ReactNode {
  if (spec.type === "hidden") {
    return <input type="hidden" name={spec.name} value={String(value ?? "")} />;
  }

  const labelEl = (
    <span className="block text-sm font-medium text-slate-700">
      {spec.label}
      {"required" in spec && spec.required ? <span className="text-red-500"> *</span> : null}
    </span>
  );

  const inputCls =
    "mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-slate-900";

  if (spec.type === "textarea") {
    return (
      <label className="block">
        {labelEl}
        <textarea
          rows={spec.rows ?? 3}
          required={spec.required}
          value={(value as string) ?? ""}
          onChange={(e) => onChange(e.target.value)}
          className={inputCls}
        />
      </label>
    );
  }

  if (spec.type === "select") {
    return (
      <label className="block">
        {labelEl}
        <select
          required={spec.required}
          value={(value as string) ?? ""}
          onChange={(e) => onChange(e.target.value)}
          className={inputCls}
        >
          <option value="">— select —</option>
          {spec.options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </label>
    );
  }

  if (spec.type === "select-async") {
    return (
      <AsyncSelectRow
        spec={spec}
        value={value as string}
        onChange={onChange}
        labelEl={labelEl}
        inputCls={inputCls}
      />
    );
  }

  if (spec.type === "number") {
    return (
      <label className="block">
        {labelEl}
        <input
          type="number"
          min={spec.min}
          max={spec.max}
          step={spec.step ?? "any"}
          required={spec.required}
          value={(value as number | string) ?? ""}
          onChange={(e) => onChange(e.target.value === "" ? "" : Number(e.target.value))}
          className={inputCls}
        />
      </label>
    );
  }

  if (spec.type === "date") {
    return (
      <label className="block">
        {labelEl}
        <input
          type="date"
          required={spec.required}
          value={(value as string) ?? ""}
          onChange={(e) => onChange(e.target.value)}
          className={inputCls}
        />
      </label>
    );
  }

  if (spec.type === "datetime") {
    return (
      <label className="block">
        {labelEl}
        <input
          type="datetime-local"
          required={spec.required}
          value={(value as string) ?? ""}
          onChange={(e) => onChange(e.target.value)}
          className={inputCls}
        />
      </label>
    );
  }

  // text, email, tel, url
  return (
    <label className="block">
      {labelEl}
      <input
        type={spec.type}
        placeholder={spec.placeholder}
        required={spec.required}
        value={(value as string) ?? ""}
        onChange={(e) => onChange(e.target.value)}
        className={inputCls}
      />
    </label>
  );
}

function AsyncSelectRow(props: {
  spec: Extract<FieldSpec, { type: "select-async" }>;
  value: string;
  onChange: (v: unknown) => void;
  labelEl: ReactNode;
  inputCls: string;
}): ReactNode {
  const { spec, value, onChange, labelEl, inputCls } = props;
  const [options, setOptions] = useState<{ value: string; label: string }[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    spec
      .loadOptions()
      .then((opts) => !cancelled && setOptions(opts))
      .catch((e) => !cancelled && setError(e instanceof Error ? e.message : "failed"));
    return () => {
      cancelled = true;
    };
  }, [spec]);

  return (
    <label className="block">
      {labelEl}
      <select
        required={spec.required}
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
        className={inputCls}
        disabled={!options}
      >
        <option value="">{options ? "— select —" : "Loading…"}</option>
        {options?.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      {error && <div className="mt-1 text-xs text-red-600">{error}</div>}
    </label>
  );
}
