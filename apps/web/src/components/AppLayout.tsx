import { Outlet, NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "@/lib/auth";

const navItem =
  "px-3 py-2 rounded-md text-sm font-medium hover:bg-slate-100 hover:text-slate-900";
const navItemActive = "bg-slate-900 text-white hover:bg-slate-900 hover:text-white";

export function AppLayout() {
  const { me, logout } = useAuth();
  const navigate = useNavigate();

  return (
    <div className="flex min-h-full">
      <aside className="w-60 border-r border-slate-200 bg-white">
        <div className="px-4 py-5">
          <div className="text-lg font-semibold">SalesPilot</div>
          <div className="text-xs text-slate-500 truncate">
            {me?.current_org?.name ?? "—"}
          </div>
        </div>
        <nav className="px-2 space-y-1">
          {[
            ["/contacts", "Contacts"],
            ["/companies", "Companies"],
            ["/deals", "Deals"],
            ["/activities", "Activities"],
          ].map(([to, label]) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `${navItem} block ${isActive ? navItemActive : "text-slate-700"}`
              }
            >
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="absolute bottom-0 w-60 border-t border-slate-200 p-4">
          <div className="text-xs text-slate-600 truncate">{me?.user.email}</div>
          <button
            onClick={() => {
              logout();
              navigate("/login");
            }}
            className="mt-2 text-xs text-slate-500 hover:text-slate-900 underline"
          >
            Sign out
          </button>
        </div>
      </aside>
      <main className="flex-1 px-8 py-6 overflow-auto">
        <Outlet />
      </main>
    </div>
  );
}
