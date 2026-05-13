import { useEffect, useState } from "react";
import { Outlet, NavLink, useNavigate, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

type NavEntry = {
  to: string;
  label: string;
  icon: string;
  badge?: number;
  badgeTone?: "default" | "brand" | "danger";
};

type NavSection = {
  title: string | null;
  items: NavEntry[];
};

function useCounts() {
  // Tiny per-section counts: prospects, customers, open activities.
  const prospects = useQuery<{ total: number }>({
    queryKey: ["sidebar-prospects"],
    queryFn: () => api("/companies?source=salespilot&limit=1"),
    refetchInterval: 60_000,
  });
  const customers = useQuery<{ total: number }>({
    queryKey: ["sidebar-customers"],
    queryFn: () => api("/companies?source__in=halopsa,halopsa_pushed&limit=1"),
    refetchInterval: 60_000,
  });
  const activities = useQuery<{ total: number }>({
    queryKey: ["sidebar-activities-open"],
    queryFn: () => api("/activities?limit=1"),
    refetchInterval: 60_000,
  });
  const quotations = useQuery<{ open_count: number; expiring_soon_count: number; expired_count: number }>({
    queryKey: ["sidebar-quotations-summary"],
    queryFn: () => api("/quotations/summary"),
    refetchInterval: 60_000,
  });
  return {
    prospects: prospects.data?.total ?? 0,
    customers: customers.data?.total ?? 0,
    activities: activities.data?.total ?? 0,
    // Show open + expiring as a single "needs attention" badge.
    quotations_open: (quotations.data?.open_count ?? 0) + (quotations.data?.expiring_soon_count ?? 0),
  };
}

const ICONS = {
  dashboard: (
    <path
      strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.6}
      d="M3 12l9-8 9 8M5 10v10h4v-6h6v6h4V10"
    />
  ),
  target: (
    <>
      <circle cx="12" cy="12" r="9" strokeWidth={1.6} />
      <circle cx="12" cy="12" r="5" strokeWidth={1.6} />
      <circle cx="12" cy="12" r="1.6" fill="currentColor" />
    </>
  ),
  building: (
    <path
      strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.6}
      d="M4 21V5a1 1 0 011-1h8a1 1 0 011 1v16M14 21V9a1 1 0 011-1h4a1 1 0 011 1v12M3 21h18M8 8h2M8 12h2M8 16h2M16 12h2M16 16h2"
    />
  ),
  coin: (
    <>
      <circle cx="12" cy="12" r="9" strokeWidth={1.6} />
      <path strokeLinecap="round" strokeWidth={1.6} d="M15 9.5c-.5-1-1.5-1.5-3-1.5-2 0-3 1-3 2.2 0 1 .6 1.5 2 1.8l2 .4c1.4.3 2 .8 2 1.8 0 1.2-1 2.2-3 2.2-1.5 0-2.5-.5-3-1.5M12 7v10" />
    </>
  ),
  users: (
    <path
      strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.6}
      d="M16 11a4 4 0 10-8 0 4 4 0 008 0zM3 21v-1a5 5 0 015-5h2M14 15h2a5 5 0 015 5v1M19 8a3 3 0 100-6 3 3 0 000 6z"
    />
  ),
  checklist: (
    <path
      strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.6}
      d="M9 5h11M9 12h11M9 19h11M3.5 5l1.2 1.2L7 4M3.5 12l1.2 1.2L7 11M3.5 19l1.2 1.2L7 18"
    />
  ),
  globe: (
    <>
      <circle cx="12" cy="12" r="9" strokeWidth={1.6} />
      <path strokeWidth={1.6} d="M3 12h18M12 3a13 13 0 010 18M12 3a13 13 0 000 18" />
    </>
  ),
  send: (
    <path
      strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.6}
      d="M22 2L11 13M22 2l-7 20-4-9-9-4z"
    />
  ),
  linkedin: (
    <>
      <rect x="3" y="3" width="18" height="18" rx="2" strokeWidth={1.6} />
      <path strokeWidth={1.6} strokeLinecap="round" d="M8 10v8M8 6.5v.5M12 18v-4a2 2 0 014 0v4M12 14v4" />
    </>
  ),
  megaphone: (
    <path
      strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.6}
      d="M3 11l18-5v12L3 13v-2zm0 0v3a2 2 0 002 2h2v-7H5a2 2 0 00-2 2zm5 2v4a2 2 0 002 2h1l1-3"
    />
  ),
  wasp: (
    <>
      <ellipse cx="12" cy="13" rx="3.5" ry="5.5" strokeWidth={1.6} />
      <path strokeWidth={1.6} strokeLinecap="round" d="M8.5 11h7M8.5 13.5h7M8.5 16h7" />
      <path strokeWidth={1.6} strokeLinecap="round" d="M12 3v3.5M10 5l2 2 2-2" />
      <path strokeWidth={1.2} strokeLinecap="round" d="M6.5 8c0 1.5 1 2.5 2.5 3M17.5 8c0 1.5-1 2.5-2.5 3" />
    </>
  ),
  settings: (
    <path
      strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.6}
      d="M10.3 3.5l-.4 1.6a7.5 7.5 0 00-2 1.2L6.4 5.6 4.6 7.4l.7 1.5a7.5 7.5 0 00-1.2 2L2.5 11.3v2.4l1.6.4c.3.7.7 1.4 1.2 2l-.7 1.5 1.8 1.8 1.5-.7c.6.5 1.3.9 2 1.2l.4 1.6h2.4l.4-1.6a7.5 7.5 0 002-1.2l1.5.7 1.8-1.8-.7-1.5c.5-.6.9-1.3 1.2-2l1.6-.4v-2.4l-1.6-.4a7.5 7.5 0 00-1.2-2l.7-1.5-1.8-1.8-1.5.7a7.5 7.5 0 00-2-1.2l-.4-1.6z M12 9.5a2.5 2.5 0 100 5 2.5 2.5 0 000-5z"
    />
  ),
} as const;

function NavIcon({ name }: { name: keyof typeof ICONS }) {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      className="shrink-0"
      aria-hidden="true"
    >
      {ICONS[name]}
    </svg>
  );
}

function Badge({
  count,
  tone = "default",
  inverted = false,
}: {
  count: number;
  tone?: "default" | "brand" | "danger";
  inverted?: boolean;
}) {
  if (count <= 0) return null;
  if (inverted) {
    return (
      <span className="ml-auto rounded-full bg-white/20 px-2 py-0.5 text-[10px] font-medium tabular-nums">
        {count}
      </span>
    );
  }
  const cls =
    tone === "danger"
      ? "bg-red-100 text-red-700"
      : tone === "brand"
        ? "bg-brand-100 text-brand-700"
        : "bg-slate-100 text-slate-600";
  return (
    <span
      className={`ml-auto rounded-full px-2 py-0.5 text-[10px] font-medium tabular-nums ${cls}`}
    >
      {count}
    </span>
  );
}

export function AppLayout() {
  const { me, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const counts = useCounts();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  // Sluit het mobiele menu bij elke route-wisseling
  useEffect(() => {
    setMobileMenuOpen(false);
  }, [location.pathname]);

  // Body lock when mobile menu is open (geen page-scroll achter de overlay)
  useEffect(() => {
    if (mobileMenuOpen) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => { document.body.style.overflow = ""; };
  }, [mobileMenuOpen]);

  const sections: NavSection[] = [
    {
      title: "Overview",
      items: [{ to: "/dashboard", label: "Dashboard", icon: "dashboard" }],
    },
    {
      title: "Pipeline",
      items: [
        { to: "/prospects", label: "Prospects", icon: "target", badge: counts.prospects, badgeTone: "brand" },
        { to: "/customers", label: "Customers", icon: "building", badge: counts.customers },
        { to: "/deals", label: "Deals", icon: "coin" },
        { to: "/contacts", label: "Contacts", icon: "users" },
        { to: "/activities", label: "Activities", icon: "checklist", badge: counts.activities, badgeTone: "danger" },
      ],
    },
    {
      title: "Acquisitie",
      items: [
        { to: "/wespennest", label: "Wespennest", icon: "wasp" },
      ],
    },
    {
      title: "Outreach",
      items: [
        { to: "/sequences", label: "Sequences", icon: "send" },
        { to: "/linkedin", label: "LinkedIn (legacy)", icon: "linkedin" },
        { to: "/social", label: "LinkedIn posts", icon: "edit" },
        { to: "/mail-campaigns", label: "Mail Campaigns", icon: "megaphone" },
      ],
    },
    {
      title: "Persoonlijk",
      items: [
        { to: "/calendar", label: "Mijn agenda", icon: "edit" },
      ],
    },
    {
      title: "External",
      items: [
        { to: "/quotations", label: "Quotations", icon: "globe", badge: counts.quotations_open },
        { to: "/mandates", label: "SEPA-mandaten", icon: "shield" },
      ],
    },
  ];

  return (
    <>
      {/* Mobile top-bar (alleen <md). Bevat hamburger + logo. Volle breedte. */}
      <div className="md:hidden sticky top-0 z-30 flex items-center justify-between border-b border-slate-200 bg-white px-3 py-2 shadow-sm">
        <button
          type="button"
          onClick={() => setMobileMenuOpen(true)}
          aria-label="Open menu"
          className="inline-flex h-11 w-11 items-center justify-center rounded-md text-slate-700 hover:bg-slate-100 active:bg-slate-200"
        >
          <svg className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5M3.75 17.25h16.5" />
          </svg>
        </button>
        {me?.current_org?.logo_url ? (
          <img src={me.current_org.logo_url} alt={me.current_org.name} className="h-7 max-w-[140px] object-contain" />
        ) : (
          <div className="text-base font-semibold text-brand-600">SalesPilot</div>
        )}
        <div className="w-11"></div>
      </div>

      <div className="flex min-h-screen bg-slate-50">
      {/* Backdrop (alleen op mobile, alleen als menu open). Klik = sluiten. */}
      {mobileMenuOpen && (
        <div
          className="md:hidden fixed inset-0 z-40 bg-slate-900/50"
          onClick={() => setMobileMenuOpen(false)}
          aria-hidden="true"
        />
      )}

      <aside
        className={
          // Mobile: fixed off-canvas slide-in.
          // Desktop (md+): static in normal flow, sticky to top.
          `bg-white border-r border-slate-200 flex flex-col ` +
          `fixed top-0 left-0 z-50 h-screen w-64 transition-transform duration-200 ease-out ` +
          (mobileMenuOpen ? "translate-x-0 " : "-translate-x-full ") +
          `md:sticky md:translate-x-0 md:w-60 md:top-0 md:z-auto md:h-screen md:self-start md:shrink-0`
        }
      >
        <div className="flex items-center justify-between px-4 py-5">
          {me?.current_org?.logo_url ? (
            <img
              src={me.current_org.logo_url}
              alt={me.current_org.name}
              className="h-9 max-w-[180px] object-contain"
            />
          ) : (
            <div className="text-base font-semibold text-brand-600 leading-tight">
              SalesPilot
            </div>
          )}
          {/* Sluit-knop alleen op mobile */}
          <button
            type="button"
            onClick={() => setMobileMenuOpen(false)}
            aria-label="Sluit menu"
            className="md:hidden inline-flex h-9 w-9 items-center justify-center rounded-md text-slate-500 hover:bg-slate-100"
          >
            <svg className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 6l12 12M6 18L18 6" />
            </svg>
          </button>
        </div>

        <nav className="px-2 flex-1 overflow-auto">
          {sections.map((section) => (
            <div key={section.title ?? "_"} className="mb-3">
              {section.title && (
                <div className="px-3 py-1 text-[10px] font-medium uppercase tracking-wider text-slate-400">
                  {section.title}
                </div>
              )}
              <div className="space-y-0.5">
                {section.items.map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    className={({ isActive }) =>
                      `flex items-center gap-2.5 rounded-md px-3 py-1.5 text-sm transition-colors ${
                        isActive
                          ? "bg-brand-500 text-white font-medium"
                          : "text-slate-700 hover:bg-slate-100"
                      }`
                    }
                  >
                    {({ isActive }) => (
                      <>
                        <NavIcon name={item.icon as keyof typeof ICONS} />
                        <span className="flex-1 truncate">{item.label}</span>
                        {item.badge !== undefined && (
                          <Badge
                            count={item.badge}
                            tone={item.badgeTone}
                            inverted={isActive}
                          />
                        )}
                      </>
                    )}
                  </NavLink>
                ))}
              </div>
            </div>
          ))}
        </nav>

        <div className="border-t border-slate-200 px-2 pt-2 pb-3">
          <NavLink
            to="/settings"
            className={({ isActive }) =>
              `flex items-center gap-2.5 rounded-md px-3 py-1.5 text-sm transition-colors ${
                isActive
                  ? "bg-brand-500 text-white font-medium"
                  : "text-slate-700 hover:bg-slate-100"
              }`
            }
          >
            <NavIcon name="settings" />
            <span>Settings</span>
          </NavLink>
          <div className="mt-3 px-3">
            <div className="text-xs text-slate-700 truncate">{me?.user.email}</div>
            <button
              onClick={() => {
                logout();
                navigate("/login");
              }}
              className="mt-1 text-xs text-slate-500 hover:text-slate-900 underline"
            >
              Sign out
            </button>
          </div>
        </div>
      </aside>

      <main className="flex-1 px-4 py-4 md:px-8 md:py-6 overflow-auto bg-slate-50 min-w-0">
        <Outlet />
      </main>
    </div>
    </>
  );
}
