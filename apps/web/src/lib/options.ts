/** Loaders for async select options on form fields. */

import { api } from "./api";

type Page<T> = { items: T[]; total: number };

export async function loadCompanyOptions(): Promise<{ value: string; label: string }[]> {
  const page = await api<Page<{ id: string; name: string }>>("/companies?limit=500");
  return page.items.map((c) => ({ value: c.id, label: c.name }));
}

export async function loadContactOptions(): Promise<{ value: string; label: string }[]> {
  const page = await api<
    Page<{ id: string; first_name: string | null; last_name: string | null; email: string | null }>
  >("/contacts?limit=500");
  return page.items.map((c) => {
    const name = [c.first_name, c.last_name].filter(Boolean).join(" ") || c.email || c.id;
    return { value: c.id, label: name };
  });
}

export async function loadDealOptions(): Promise<{ value: string; label: string }[]> {
  const page = await api<Page<{ id: string; name: string }>>("/deals?limit=500");
  return page.items.map((d) => ({ value: d.id, label: d.name }));
}
