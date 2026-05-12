import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { Navigate, useLocation } from "react-router-dom";

import { api, getAccessToken, setAccessToken } from "./api";

type Me = {
  user: { id: string; email: string; full_name: string | null; is_active: boolean };
  current_org: { id: string; name: string; slug: string } | null;
  memberships: Array<{ org: { id: string; name: string; slug: string }; role: string }>;
};

type AuthState = {
  me: Me | null;
  loading: boolean;
  loginWithPassword: (email: string, password: string) => Promise<void>;
  requestMagicLink: (email: string) => Promise<void>;
  verifyMagicLink: (token: string) => Promise<void>;
  logout: () => void;
};

const AuthCtx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState<boolean>(!!getAccessToken());

  const refreshMe = useCallback(async () => {
    if (!getAccessToken()) {
      setMe(null);
      setLoading(false);
      return;
    }
    try {
      const data = await api<Me>("/auth/me");
      setMe(data);
    } catch {
      setAccessToken(null);
      setMe(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshMe();
  }, [refreshMe]);

  const loginWithPassword = useCallback(
    async (email: string, password: string) => {
      const data = await api<{ access_token: string; refresh_token: string }>(
        "/auth/login",
        { method: "POST", body: JSON.stringify({ email, password }) },
      );
      setAccessToken(data.access_token);
      localStorage.setItem("refresh_token", data.refresh_token);
      await refreshMe();
    },
    [refreshMe],
  );

  const requestMagicLink = useCallback(async (email: string) => {
    await api("/auth/magic-link/request", {
      method: "POST",
      body: JSON.stringify({ email }),
    });
  }, []);

  const verifyMagicLink = useCallback(
    async (token: string) => {
      const data = await api<{ access_token: string; refresh_token: string }>(
        "/auth/magic-link/verify",
        { method: "POST", body: JSON.stringify({ token }) },
      );
      setAccessToken(data.access_token);
      localStorage.setItem("refresh_token", data.refresh_token);
      await refreshMe();
    },
    [refreshMe],
  );

  const logout = useCallback(() => {
    setAccessToken(null);
    localStorage.removeItem("refresh_token");
    setMe(null);
  }, []);

  const value = useMemo<AuthState>(
    () => ({ me, loading, loginWithPassword, requestMagicLink, verifyMagicLink, logout }),
    [me, loading, loginWithPassword, requestMagicLink, verifyMagicLink, logout],
  );

  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthCtx);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

export function RequireAuth({ children }: { children: ReactNode }) {
  const { me, loading } = useAuth();
  const location = useLocation();
  if (loading) return <div className="p-8 text-slate-500">Loading…</div>;
  if (!me) return <Navigate to="/login" state={{ from: location }} replace />;
  return <>{children}</>;
}
