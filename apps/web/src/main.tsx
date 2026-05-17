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
import { Quotations } from "./pages/Quotations";
import { MailCampaigns } from "./pages/MailCampaigns";
import { MailCampaignDetail } from "./pages/MailCampaignDetail";
import { Wespennest } from "./pages/Wespennest";
import { Management } from "./pages/Management";
import { Mandates } from "./pages/Mandates";
import { FinancieelDashboard } from "./pages/FinancieelDashboard";
import { SepaFix } from "./pages/SepaFix";
import { Unifi } from "./pages/Unifi";
import { UnifiHostDetail } from "./pages/UnifiHostDetail";
import { QuotationDetail } from "./pages/QuotationDetail";
import { AccessSettings } from "./pages/AccessSettings";
import { Tech } from "./pages/Tech";
import { Calendar } from "./pages/Calendar";
import { AcceptInvite } from "./pages/AcceptInvite";
import { SocialPosts, SocialPostEditor } from "./pages/SocialPosts";
import { CompanyDetail } from "./pages/CompanyDetail";
import { Deals } from "./pages/Deals";
import { DealDetail } from "./pages/DealDetail";
import { Activities } from "./pages/Activities";
import { Settings, SettingsIndex } from "./pages/Settings";
import { IntegrationsSettings } from "./pages/IntegrationsSettings";
import { IntegrationConfigure } from "./pages/IntegrationConfigure";
import { BrandingSettings } from "./pages/BrandingSettings";
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
          <Route path="/accept-invite" element={<AcceptInvite />} />
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
              <Route path="/quotations" element={<Quotations />} />
              <Route path="/mail-campaigns" element={<MailCampaigns />} />
              <Route path="/mail-campaigns/:id" element={<MailCampaignDetail />} />
              <Route path="/wespennest" element={<Wespennest />} />
              <Route path="/toegekend" element={<Wespennest />} />
              <Route path="/management" element={<Management />} />
              <Route path="/mandates" element={<Mandates />} />
              <Route path="/financieel/dashboard" element={<FinancieelDashboard />} />
              <Route path="/financieel/sepa-fix" element={<SepaFix />} />
              <Route path="/unifi" element={<Unifi />} />
              <Route path="/unifi/hosts/:hostId" element={<UnifiHostDetail />} />
              <Route path="/quotations/:quotationId" element={<QuotationDetail />} />
              <Route path="/settings/access" element={<AccessSettings />} />
              <Route path="/tech" element={<Tech />} />
              <Route path="/calendar" element={<Calendar />} />
              <Route path="/social" element={<SocialPosts />} />
              <Route path="/social/new" element={<SocialPostEditor />} />
              <Route path="/social/:id" element={<SocialPostEditor />} />
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
                <Route path="branding" element={<BrandingSettings />} />
                <Route path="management" element={<Management />} />
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
