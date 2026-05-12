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
      </div>
    </div>
  );
}
