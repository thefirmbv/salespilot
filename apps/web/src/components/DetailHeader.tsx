/** Header used at the top of every detail page.
 *
 *  Renders a back link, a title, optional subtitle, an Edit and Delete
 *  button. Edit triggers the consumer's edit-state; Delete confirms and
 *  navigates back to the list afterwards.
 */

import { Link, useNavigate } from "react-router-dom";

type Props = {
  backTo: string;
  backLabel: string;
  title: string;
  subtitle?: string;
  onEdit: () => void;
  onDelete: () => Promise<void> | void;
  deleteConfirmLabel?: string;
};

export function DetailHeader({
  backTo,
  backLabel,
  title,
  subtitle,
  onEdit,
  onDelete,
  deleteConfirmLabel,
}: Props) {
  const navigate = useNavigate();
  return (
    <div>
      <Link
        to={backTo}
        className="text-sm text-slate-500 hover:text-slate-800"
      >
        ← {backLabel}
      </Link>
      <div className="mt-2 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold">{title}</h1>
          {subtitle && <p className="text-sm text-slate-500">{subtitle}</p>}
        </div>
        <div className="flex gap-2">
          <button
            onClick={onEdit}
            className="rounded-md bg-white px-3 py-1.5 text-sm font-medium text-slate-700 ring-1 ring-slate-300 hover:bg-slate-100"
          >
            Edit
          </button>
          <button
            onClick={async () => {
              if (
                confirm(
                  `Delete ${deleteConfirmLabel ?? title}? This cannot be undone.`,
                )
              ) {
                await onDelete();
                navigate(backTo);
              }
            }}
            className="rounded-md bg-white px-3 py-1.5 text-sm font-medium text-red-600 ring-1 ring-red-300 hover:bg-red-50"
          >
            Delete
          </button>
        </div>
      </div>
    </div>
  );
}

/** Two-column key/value list used in detail headers and side panels. */
export function FieldList({
  fields,
}: {
  fields: Array<[label: string, value: React.ReactNode]>;
}) {
  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
      {fields.map(([label, value]) => (
        <div key={label}>
          <dt className="text-xs uppercase tracking-wider text-slate-500">
            {label}
          </dt>
          <dd className="mt-0.5 text-slate-900">{value}</dd>
        </div>
      ))}
    </dl>
  );
}
