import { NavLink, Outlet, Navigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

const tab =
  "px-3 py-2 text-sm font-medium border-b-2 -mb-px transition-colors";
const tabActive = "border-brand-500 text-slate-900";
const tabIdle = "border-transparent text-slate-500 hover:text-slate-800";

type AdminMe = {
  is_platform_admin: boolean;
  org_role: string;
};

export function Settings() {
  const adminMeQ = useQuery<AdminMe>({
    queryKey: ["/admin/me"],
    queryFn: () => api<AdminMe>("/admin/me"),
    retry: false,
  });
  const canManage =
    adminMeQ.data?.is_platform_admin ||
    adminMeQ.data?.org_role === "owner" ||
    adminMeQ.data?.org_role === "admin";

  return (
    <div>
      <h1 className="text-2xl font-semibold">Settings</h1>
      <div className="mt-4 border-b border-slate-200 overflow-x-auto">
        <div className="-mb-px flex gap-1 overflow-x-auto">
          <NavLink
            to="integrations"
            className={({ isActive }) =>
              `${tab} ${isActive ? tabActive : tabIdle}`
            }
          >
            Integrations
          </NavLink>
          <NavLink
            to="branding"
            className={({ isActive }) =>
              `${tab} ${isActive ? tabActive : tabIdle}`
            }
          >
            Branding
          </NavLink>
          <NavLink
            to="access"
            className={({ isActive }) =>
              `${tab} ${isActive ? tabActive : tabIdle}`
            }
          >
            Rechten
          </NavLink>
          {canManage && (
            <NavLink
              to="management"
              className={({ isActive }) =>
                `${tab} ${isActive ? tabActive : tabIdle}`
              }
            >
              Management
            </NavLink>
          )}
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
