import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import { fmtDateTime } from "@/lib/format";

type HaloPublic = {
  id: string;
  kind: string;
  is_enabled: boolean;
  config_public: {
    base_url: string | null;
    client_id: string | null;
    tenant: string | null;
    scopes: string | null;
    client_secret_set: boolean;
  };
  last_sync_at: string | null;
  last_sync_status: string | null;
  last_sync_message: string | null;
  updated_at: string;
} | null;

type TestResult = { ok: boolean; detail: string; token_present?: boolean };
type SyncResult = {
  ok: boolean;
  detail: string;
  fetched: number;
  created: number;
  updated: number;
};

export function IntegrationsSettings() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery<HaloPublic>({
    queryKey: ["/integrations/halopsa"],
    queryFn: () => api<HaloPublic>("/integrations/halopsa"),
  });

  const [baseUrl, setBaseUrl] = useState("");
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [tenant, setTenant] = useState("");
  const [scopes, setScopes] = useState("all");
  const [isEnabled, setIsEnabled] = useState(true);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [testMessage, setTestMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [syncMessage, setSyncMessage] = useState<{ ok: boolean; text: string } | null>(null);

  // Hydrate the form from existing config (secret is never echoed back).
  useEffect(() => {
    if (!data) return;
    setBaseUrl(data.config_public.base_url ?? "");
    setClientId(data.config_public.client_id ?? "");
    setTenant(data.config_public.tenant ?? "");
    setScopes(data.config_public.scopes ?? "all");
    setIsEnabled(data.is_enabled);
  }, [data]);

  const saveMut = useMutation({
    mutationFn: () =>
      api<HaloPublic>("/integrations/halopsa", {
        method: "PUT",
        body: JSON.stringify({
          is_enabled: isEnabled,
          config: {
            base_url: baseUrl,
            client_id: clientId,
            client_secret: clientSecret, // empty preserves existing
            tenant: tenant || null,
            scopes,
          },
        }),
      }),
    onSuccess: () => {
      setSaveMessage("Saved.");
      setClientSecret("");
      qc.invalidateQueries({ queryKey: ["/integrations/halopsa"] });
    },
    onError: (e) =>
      setSaveMessage(
        e instanceof ApiError ? `Save failed: ${e.detail}` : "Save failed",
      ),
  });

  const testMut = useMutation({
    mutationFn: () =>
      api<TestResult>("/integrations/halopsa/test", { method: "POST" }),
    onSuccess: (r) =>
      setTestMessage({ ok: r.ok, text: r.detail }),
    onError: (e) =>
      setTestMessage({
        ok: false,
        text: e instanceof ApiError ? e.detail : "test failed",
      }),
  });

  const syncMut = useMutation({
    mutationFn: () =>
      api<SyncResult>("/integrations/halopsa/sync", { method: "POST" }),
    onSuccess: (r) => {
      setSyncMessage({ ok: r.ok, text: r.detail });
      qc.invalidateQueries({ queryKey: ["/integrations/halopsa"] });
      qc.invalidateQueries({ queryKey: ["/companies"] });
    },
    onError: (e) =>
      setSyncMessage({
        ok: false,
        text: e instanceof ApiError ? e.detail : "sync failed",
      }),
  });

  if (isLoading) return <div className="text-slate-500">Loading…</div>;

  const inputCls =
    "mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-slate-900";

  return (
    <div className="space-y-6 max-w-2xl">
      <div className="rounded-lg ring-1 ring-slate-200 bg-white p-6">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold">HaloPSA</h2>
            <p className="text-sm text-slate-500">
              Connect SalesPilot to your HaloPSA tenant to sync clients in and
              push prospects out as new HaloPSA clients.
            </p>
          </div>
          {data && (
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={isEnabled}
                onChange={(e) => setIsEnabled(e.target.checked)}
              />
              Enabled
            </label>
          )}
        </div>

        <div className="mt-6 space-y-4">
          <label className="block">
            <span className="block text-sm font-medium text-slate-700">
              Base URL <span className="text-red-500">*</span>
            </span>
            <input
              type="text"
              required
              placeholder="halo.your-tenant.com"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              className={inputCls}
            />
            <span className="mt-1 block text-xs text-slate-500">
              Hostname only; https is added automatically.
            </span>
          </label>

          <label className="block">
            <span className="block text-sm font-medium text-slate-700">
              Client ID <span className="text-red-500">*</span>
            </span>
            <input
              type="text"
              required
              value={clientId}
              onChange={(e) => setClientId(e.target.value)}
              className={inputCls}
            />
          </label>

          <label className="block">
            <span className="block text-sm font-medium text-slate-700">
              Client Secret{" "}
              {!data?.config_public.client_secret_set && (
                <span className="text-red-500">*</span>
              )}
            </span>
            <input
              type="password"
              placeholder={
                data?.config_public.client_secret_set
                  ? "•••• (leave empty to keep existing)"
                  : ""
              }
              value={clientSecret}
              onChange={(e) => setClientSecret(e.target.value)}
              className={inputCls}
            />
          </label>

          <label className="block">
            <span className="block text-sm font-medium text-slate-700">
              Tenant (optional)
            </span>
            <input
              type="text"
              value={tenant}
              onChange={(e) => setTenant(e.target.value)}
              className={inputCls}
            />
          </label>

          <label className="block">
            <span className="block text-sm font-medium text-slate-700">
              Scopes
            </span>
            <input
              type="text"
              value={scopes}
              onChange={(e) => setScopes(e.target.value)}
              className={inputCls}
            />
            <span className="mt-1 block text-xs text-slate-500">
              Space-separated. Use <code>all</code> if unsure.
            </span>
          </label>
        </div>

        <div className="mt-6 flex flex-wrap items-center gap-2">
          <button
            onClick={() => {
              setSaveMessage(null);
              saveMut.mutate();
            }}
            disabled={saveMut.isPending || !baseUrl || !clientId || (!data?.config_public.client_secret_set && !clientSecret)}
            className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
          >
            {saveMut.isPending ? "Saving…" : data ? "Save changes" : "Connect"}
          </button>
          {data && (
            <>
              <button
                onClick={() => {
                  setTestMessage(null);
                  testMut.mutate();
                }}
                disabled={testMut.isPending}
                className="rounded-md bg-white px-3 py-1.5 text-sm font-medium text-slate-700 ring-1 ring-slate-300 hover:bg-slate-100 disabled:opacity-50"
              >
                {testMut.isPending ? "Testing…" : "Test connection"}
              </button>
              <button
                onClick={() => {
                  setSyncMessage(null);
                  syncMut.mutate();
                }}
                disabled={syncMut.isPending || !data.is_enabled}
                className="rounded-md bg-white px-3 py-1.5 text-sm font-medium text-slate-700 ring-1 ring-slate-300 hover:bg-slate-100 disabled:opacity-50"
              >
                {syncMut.isPending ? "Syncing…" : "Sync clients now"}
              </button>
            </>
          )}
        </div>

        {saveMessage && (
          <div className="mt-3 text-sm text-slate-600">{saveMessage}</div>
        )}
        {testMessage && (
          <div
            className={`mt-3 text-sm ${
              testMessage.ok ? "text-green-700" : "text-red-600"
            }`}
          >
            {testMessage.text}
          </div>
        )}
        {syncMessage && (
          <div
            className={`mt-3 text-sm ${
              syncMessage.ok ? "text-green-700" : "text-red-600"
            }`}
          >
            {syncMessage.text}
          </div>
        )}
      </div>

      {data && data.last_sync_at && (
        <div className="rounded-lg ring-1 ring-slate-200 bg-white p-6">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-600">
            Last sync
          </h3>
          <div className="mt-2 text-sm text-slate-700">
            <div>When: {fmtDateTime(data.last_sync_at)}</div>
            <div>Status: {data.last_sync_status ?? "—"}</div>
            {data.last_sync_message && (
              <div className="mt-1 text-slate-500">{data.last_sync_message}</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
