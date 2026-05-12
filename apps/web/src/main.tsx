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
import { Companies } from "./pages/Companies";
import { CompanyDetail } from "./pages/CompanyDetail";
import { Deals } from "./pages/Deals";
import { DealDetail } from "./pages/DealDetail";
import { Activities } from "./pages/Activities";
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
              <Route path="/contacts" element={<Contacts />} />
              <Route path="/contacts/:id" element={<ContactDetail />} />
              <Route path="/companies" element={<Companies />} />
              <Route path="/companies/:id" element={<CompanyDetail />} />
              <Route path="/deals" element={<Deals />} />
              <Route path="/deals/:id" element={<DealDetail />} />
              <Route path="/activities" element={<Activities />} />
              <Route path="/" element={<Navigate to="/dashboard" replace />} />
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
