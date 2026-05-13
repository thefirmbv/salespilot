import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api } from "@/lib/api";

export function AcceptInvite() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const token = params.get("token") ?? "";
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    if (!token) {
      setError("Geen invite-token in de URL.");
    }
  }, [token]);

  const submit = async () => {
    if (password.length < 8) {
      setError("Wachtwoord moet minimaal 8 tekens zijn.");
      return;
    }
    setPending(true);
    setError(null);
    try {
      const result = await api<{ access_token: string; refresh_token: string }>(
        "/auth/accept-invite",
        {
          method: "POST",
          body: JSON.stringify({ token, password, full_name: fullName }),
        },
      );
      // Store tokens locally and go to dashboard
      localStorage.setItem("access_token", result.access_token);
      localStorage.setItem("refresh_token", result.refresh_token);
      navigate("/dashboard");
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Er ging iets mis";
      setError(msg);
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50">
      <div className="w-full max-w-md rounded-lg bg-white p-6 shadow ring-1 ring-slate-200">
        <h1 className="text-xl font-semibold">Welkom bij SalesPilot</h1>
        <p className="mt-1 text-sm text-slate-600">
          Kies een wachtwoord om je account te activeren.
        </p>

        {error && (
          <div className="mt-3 rounded-md bg-red-50 px-3 py-2 text-sm text-red-800">
            {error}
          </div>
        )}

        <div className="mt-4 space-y-3">
          <label className="block">
            <span className="block text-xs font-medium text-slate-700 mb-1">Volledige naam (optioneel)</span>
            <input value={fullName} onChange={(e) => setFullName(e.target.value)}
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm" />
          </label>
          <label className="block">
            <span className="block text-xs font-medium text-slate-700 mb-1">Wachtwoord (min. 8 tekens)</span>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm" />
          </label>
        </div>

        <button
          disabled={!password || pending || !token}
          onClick={submit}
          className="mt-4 w-full rounded-md bg-brand-500 px-4 py-2 text-sm font-medium text-white hover:bg-brand-600 disabled:opacity-50"
        >
          {pending ? "Bezig\u2026" : "Account activeren"}
        </button>
      </div>
    </div>
  );
}
