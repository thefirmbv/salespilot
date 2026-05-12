import { NavLink, Outlet, Navigate } from "react-router-dom";

const tab =
  "px-3 py-2 text-sm font-medium border-b-2 -mb-px transition-colors";
const tabActive = "border-slate-900 text-slate-900";
const tabIdle = "border-transparent text-slate-500 hover:text-slate-800";

export function Settings() {
  return (
    <div>
      <h1 className="text-2xl font-semibold">Settings</h1>
      <div className="mt-4 border-b border-slate-200">
        <div className="-mb-px flex gap-1">
          <NavLink
            to="integrations"
            className={({ isActive }) =>
              `${tab} ${isActive ? tabActive : tabIdle}`
            }
          >
            Integrations
          </NavLink>
          {/* Future tabs: Users, Pipelines, Custom fields, Branding, etc. */}
        </div>
      </div>
      <div className="mt-6">
        <Outlet />
      </div>
    </div>
  );
}

export function SettingsIndex() {
  return <Navigate to="integrations" replace />;
}
