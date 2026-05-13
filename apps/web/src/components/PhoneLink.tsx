/**
 * PhoneLink — render a phone number as a click-to-call action.
 *
 * Behaviour is driven by the active 3CX integration config_public:
 *   click_mode "tel"    -> standard tel: URI (works everywhere, opens the
 *                          OS default phone app)
 *   click_mode "3cx"    -> 3CX-specific deep link
 *                          (https://{pbx_fqdn}/callto/{e164}) which the
 *                          3CX desktop/web/mobile app intercepts and
 *                          initiates the call on the configured extension.
 *
 * Numbers are normalised to E.164: '030 1234567' or '030-123 4567'
 * becomes '+31301234567' using the country_code from the integration.
 * A leading default_outbound_prefix (e.g. '9') is stripped before
 * normalisation in case it was already prepended by someone.
 *
 * If no 3CX integration is configured we still render a tel: link.
 */

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

type Pbx3cxConfig = {
  pbx_fqdn?: string | null;
  extension?: string | null;
  country_code?: string | null;
  click_mode?: "tel" | "3cx" | null;
  default_outbound_prefix?: string | null;
};

type IntegrationPublic = {
  id: string;
  kind: string;
  is_enabled: boolean;
  config_public: Record<string, unknown> | null;
};

/**
 * Hook that reads the 3CX integration config — cached app-wide via
 * the same query key so calling it on 30 rows doesn't trigger 30
 * requests.
 */
export function use3CXConfig(): Pbx3cxConfig | null {
  const q = useQuery<IntegrationPublic | null>({
    queryKey: ["/integrations/pbx_3cx"],
    queryFn: () => api<IntegrationPublic | null>("/integrations/pbx_3cx"),
    staleTime: 5 * 60 * 1000,
    retry: false,
  });
  if (!q.data || !q.data.is_enabled) return null;
  return (q.data.config_public as Pbx3cxConfig | null) ?? null;
}

/**
 * Normalise a free-form phone number to E.164.
 * '030 1234567' + country_code '31' -> '+31301234567'.
 * '+31301234567' -> '+31301234567'.
 * Anything that can't be normalised is returned with non-digits stripped
 * but no leading '+'.
 */
export function normalisePhone(raw: string, countryCode: string = "31", outboundPrefix: string = ""): string {
  if (!raw) return "";
  let s = raw.trim();
  const wasPlus = s.startsWith("+");
  s = s.replace(/[^\d]/g, "");
  if (!s) return "";
  // Strip outbound prefix if user typed it (e.g. "9" or "0" to dial out)
  if (outboundPrefix && s.startsWith(outboundPrefix) && s.length > outboundPrefix.length + 8) {
    s = s.slice(outboundPrefix.length);
  }
  if (wasPlus) return "+" + s;
  // Dutch leading zero -> country code swap
  if (s.startsWith("00")) return "+" + s.slice(2);
  if (s.startsWith("0")) return "+" + countryCode + s.slice(1);
  // Already starts with country code without +
  if (countryCode && s.startsWith(countryCode)) return "+" + s;
  // Fallback: assume the user typed a partial number, just return what we have
  return "+" + countryCode + s;
}

export function buildCallHref(rawPhone: string, cfg: Pbx3cxConfig | null): string {
  const cc = (cfg?.country_code as string) || "31";
  const prefix = (cfg?.default_outbound_prefix as string) || "";
  const e164 = normalisePhone(rawPhone, cc, prefix);
  if (!e164) return "";

  const mode = cfg?.click_mode || "tel";
  if (mode === "3cx" && cfg?.pbx_fqdn) {
    // The 3CX click-to-call URL — handled by the installed 3CX app
    return `https://${cfg.pbx_fqdn}/callto/${e164.replace(/^\+/, "")}`;
  }
  return `tel:${e164}`;
}

/**
 * Render a phone number as a clickable link with a small phone icon.
 * Falls back gracefully when no number is set.
 */
export function PhoneLink({
  phone,
  className = "",
  showIcon = true,
}: {
  phone: string | null | undefined;
  className?: string;
  showIcon?: boolean;
}) {
  const cfg = use3CXConfig();
  if (!phone || !phone.trim()) {
    return <span className={`text-slate-400 ${className}`}>—</span>;
  }
  const href = buildCallHref(phone, cfg);
  return (
    <a
      href={href}
      onClick={(e) => e.stopPropagation()}
      className={`inline-flex items-center gap-1 text-brand-600 hover:underline ${className}`}
      title={cfg?.click_mode === "3cx" ? "Bel via 3CX" : "Bellen"}
    >
      {showIcon && (
        <svg className="h-3.5 w-3.5 shrink-0" fill="currentColor" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M6.62 10.79a15.05 15.05 0 006.59 6.59l2.2-2.2a1 1 0 011.05-.24c1.16.39 2.42.6 3.7.6a1 1 0 011 1V20a1 1 0 01-1 1A18 18 0 013 4a1 1 0 011-1h3.5a1 1 0 011 1c0 1.28.21 2.54.6 3.7a1 1 0 01-.24 1.05l-2.24 2.04z"/>
        </svg>
      )}
      <span className="tabular-nums">{phone}</span>
    </a>
  );
}

/**
 * Just a button-styled call action. Use this when phone is shown
 * elsewhere on the page and you only need the action.
 */
export function CallButton({
  phone,
  size = "md",
}: {
  phone: string | null | undefined;
  size?: "sm" | "md";
}) {
  const cfg = use3CXConfig();
  if (!phone || !phone.trim()) return null;
  const href = buildCallHref(phone, cfg);
  const isSmall = size === "sm";
  return (
    <a
      href={href}
      onClick={(e) => e.stopPropagation()}
      className={`inline-flex items-center gap-1.5 rounded-md bg-emerald-600 text-white hover:bg-emerald-700 ${
        isSmall ? "px-2 py-1 text-xs" : "px-3 py-1.5 text-sm"
      }`}
      title={cfg?.click_mode === "3cx" ? "Bel via 3CX" : "Bellen"}
    >
      <svg className={isSmall ? "h-3.5 w-3.5" : "h-4 w-4"} fill="currentColor" viewBox="0 0 24 24" aria-hidden="true">
        <path d="M6.62 10.79a15.05 15.05 0 006.59 6.59l2.2-2.2a1 1 0 011.05-.24c1.16.39 2.42.6 3.7.6a1 1 0 011 1V20a1 1 0 01-1 1A18 18 0 013 4a1 1 0 011-1h3.5a1 1 0 011 1c0 1.28.21 2.54.6 3.7a1 1 0 01-.24 1.05l-2.24 2.04z"/>
      </svg>
      Bel
    </a>
  );
}
