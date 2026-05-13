import { useEffect, useState, type FormEvent } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";

type Mode = "password" | "magic";

export function Login() {
  const { loginWithPassword, requestMagicLink, verifyMagicLink, me } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [params] = useSearchParams();

  const [mode, setMode] = useState<Mode>("password");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [info, setInfo] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Handle return from a magic-link email: ?token=...
  useEffect(() => {
    const token = params.get("token");
    if (token) {
      setBusy(true);
      verifyMagicLink(token)
        .then(() => navigate("/", { replace: true }))
        .catch((e: unknown) => {
          setError(e instanceof Error ? e.message : "magic link invalid");
        })
        .finally(() => setBusy(false));
    }
  }, [params, verifyMagicLink, navigate]);

  // Handle return from Microsoft 365 SSO callback. Backend redirects to
  // /login#access_token=...&refresh_token=... — we pick those up here.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const hash = window.location.hash;
    if (!hash || !hash.includes("access_token")) return;
    const frag = new URLSearchParams(hash.slice(1));
    const at = frag.get("access_token");
    const rt = frag.get("refresh_token");
    if (at && rt) {
      localStorage.setItem("access_token", at);
      localStorage.setItem("refresh_token", rt);
      // Clean the URL and reload so AuthProvider picks up the new token
      window.history.replaceState(null, "", "/login");
      window.location.href = "/";
    }
  }, []);

  // Render an error when SSO bounced back with ?sso_error=...
  useEffect(() => {
    const ssoErr = params.get("sso_error");
    if (!ssoErr) return;
    const messages: Record<string, string> = {
      sso_not_configured: "Microsoft 365 SSO is nog niet geconfigureerd door je beheerder.",
      domain_not_allowed: "Je email-domein is niet toegestaan voor deze SalesPilot-organisatie.",
      user_not_provisioned: "Je M365-account is niet bekend. Vraag je beheerder om een uitnodiging.",
      token_exchange_failed: "Microsoft weigerde de inlog-code. Probeer opnieuw.",
      no_email: "Microsoft heeft geen e-mailadres meegegeven.",
    };
    setError(messages[ssoErr] || `SSO-fout: ${ssoErr}`);
  }, [params]);

  // If already signed in, bounce.
  useEffect(() => {
    if (me) {
      const target =
        (location.state as { from?: { pathname?: string } } | null)?.from?.pathname ?? "/";
      navigate(target, { replace: true });
    }
  }, [me, navigate, location]);

  async function onPasswordSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await loginWithPassword(email, password);
      navigate("/", { replace: true });
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "login failed");
    } finally {
      setBusy(false);
    }
  }

  async function onMagicSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setInfo(null);
    setBusy(true);
    try {
      await requestMagicLink(email);
      setInfo("Check your inbox for a sign-in link.");
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "could not send link");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-full items-center justify-center p-6">
      <div className="w-full max-w-sm rounded-xl bg-white p-8 shadow-sm ring-1 ring-slate-200">
        <h1 className="text-xl font-semibold">Sign in to SalesPilot</h1>

        <div className="mt-6 flex gap-2 text-sm">
          {(["password", "magic"] as Mode[]).map((m) => (
            <button
              key={m}
              type="button"
              className={`rounded-md px-3 py-1.5 ${
                mode === m
                  ? "bg-slate-900 text-white"
                  : "bg-slate-100 text-slate-700 hover:bg-slate-200"
              }`}
              onClick={() => {
                setMode(m);
                setError(null);
                setInfo(null);
              }}
            >
              {m === "password" ? "Password" : "Magic link"}
            </button>
          ))}
        </div>

        <form
          onSubmit={mode === "password" ? onPasswordSubmit : onMagicSubmit}
          className="mt-6 space-y-4"
        >
          <label className="block">
            <span className="block text-sm font-medium text-slate-700">Email</span>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-slate-900"
            />
          </label>

          {mode === "password" && (
            <label className="block">
              <span className="block text-sm font-medium text-slate-700">Password</span>
              <input
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-slate-900"
              />
            </label>
          )}

          {error && <div className="text-sm text-red-600">{error}</div>}
          {info && <div className="text-sm text-green-700">{info}</div>}

          <button
            type="submit"
            disabled={busy}
            className="w-full rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
          >
            {busy
              ? "Working…"
              : mode === "password"
                ? "Sign in"
                : "Send magic link"}
          </button>
        </form>

        {/* SSO options */}
        <div className="mt-3 border-t border-slate-200 pt-3">
          <a
            href="/api/v1/auth/m365/login"
            className="flex w-full items-center justify-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            <svg width="16" height="16" viewBox="0 0 23 23" xmlns="http://www.w3.org/2000/svg">
              <rect x="1" y="1" width="10" height="10" fill="#F25022" />
              <rect x="12" y="1" width="10" height="10" fill="#7FBA00" />
              <rect x="1" y="12" width="10" height="10" fill="#00A4EF" />
              <rect x="12" y="12" width="10" height="10" fill="#FFB900" />
            </svg>
            Inloggen met Microsoft 365
          </a>
        </div>
      </div>
    </div>
  );
}
