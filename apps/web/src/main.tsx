import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import "./index.css";
import { AuthProvider, RequireAuth } from "./lib/auth";
import { Login } from "./pages/Login";
import { Dashboard } from "./pages/Dashboard";
import { Contacts } from "./pages/Contacts";
import { ContactDetail } from "./pages/ContactDetail";
import { Customers } from "./pages/Customers";
import { Prospects } from "./pages/Prospects";
import { Sequences } from "./pages/Sequences";
import { SequenceEditor } from "./pages/SequenceEditor";
import { LinkedInOutreach } from "./pages/LinkedInOutreach";
import { CompanyDetail } from "./pages/CompanyDetail";
import { Deals } from "./pages/Deals";
import { DealDetail } from "./pages/DealDetail";
import { Activities } from "./pages/Activities";
import { Settings, SettingsIndex } from "./pages/Settings";
import { IntegrationsSettings } from "./pages/IntegrationsSettings";
import { IntegrationConfigure } from "./pages/IntegrationConfigure";
import { AppLayout } from "./components/AppLayout";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: false, refetchOnWindowFocus: false },
  },
});

const root = document.getElementById("root");
if (!root) throw new Error("root not found");

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route
              element={
                <RequireAuth>
                  <AppLayout />
                </RequireAuth>
              }
            >
              <Route path="/dashboard" element={<Dashboard />} />
              <Route path="/prospects" element={<Prospects />} />
              <Route path="/customers" element={<Customers />} />
              <Route path="/sequences" element={<Sequences />} />
              <Route path="/sequences/:id" element={<SequenceEditor />} />
              <Route path="/linkedin" element={<LinkedInOutreach />} />
              <Route path="/contacts" element={<Contacts />} />
              <Route path="/contacts/:id" element={<ContactDetail />} />
              <Route path="/companies/:id" element={<CompanyDetail />} />
              <Route path="/deals" element={<Deals />} />
              <Route path="/deals/:id" element={<DealDetail />} />
              <Route path="/activities" element={<Activities />} />
              <Route path="/settings" element={<Settings />}>
                <Route index element={<SettingsIndex />} />
                <Route path="integrations" element={<IntegrationsSettings />} />
                <Route path="integrations/:kind" element={<IntegrationConfigure />} />
              </Route>
              <Route path="/" element={<Navigate to="/dashboard" replace />} />
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
