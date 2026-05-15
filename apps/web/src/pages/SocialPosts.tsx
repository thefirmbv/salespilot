import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

type Destination = {
  platform: "linkedin";
  target_type: "person" | "organization";
  target_urn: string;
  target_name: string;
};

type Media = {
  id: string;
  position: number;
  filename: string;
  mime_type: string;
  size_bytes: number;
  alt_text: string | null;
  caption: string | null;
  url: string;
};

type PublishResult = {
  platform: string;
  target_urn: string;
  target_name: string | null;
  platform_post_id: string | null;
  post_url: string | null;
  published_at: string | null;
  error: string | null;
};

type Post = {
  id: string;
  destinations: Destination[];
  body: string;
  title: string | null;
  status: "draft" | "scheduled" | "publishing" | "published" | "failed" | "cancelled";
  scheduled_at: string | null;
  published_at: string | null;
  publish_result: PublishResult[];
  last_error: string | null;
  retry_count: number;
  media: Media[];
  creator_name: string | null;
  created_at: string;
  updated_at: string;
};

type Summary = {
  total: number;
  drafts: number;
  scheduled: number;
  published_30d: number;
  failed: number;
  impressions_30d: number;
  engagements_30d: number;
};

function fmtDate(iso: string | null, withTime = false): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (withTime) {
    return d.toLocaleString("nl-NL", {
      day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
    });
  }
  return d.toLocaleDateString("nl-NL", { day: "numeric", month: "short", year: "numeric" });
}

function toLocalInput(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
function fromLocalInput(s: string): string | null {
  if (!s) return null;
  return new Date(s).toISOString();
}

const STATUS_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  draft:      { bg: "#F1F5F9", text: "#475569", label: "Concept"        },
  scheduled:  { bg: "#FAEEDA", text: "#633806", label: "Ingepland"      },
  publishing: { bg: "#E6F1FB", text: "#0C447C", label: "Wordt gepost"   },
  published:  { bg: "#E1F5EE", text: "#085041", label: "Gepubliceerd"   },
  failed:     { bg: "#FCEBEB", text: "#791F1F", label: "Mislukt"        },
  cancelled:  { bg: "#F1F5F9", text: "#475569", label: "Geannuleerd"    },
};

function StatusBadge({ status }: { status: string }) {
  const s = STATUS_STYLES[status] ?? STATUS_STYLES.draft;
  return (
    <span className="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium"
      style={{ backgroundColor: s.bg, color: s.text }}>
      {s.label}
    </span>
  );
}

const LI_CHAR_LIMIT = 3000;

export function SocialPosts() {
  const [searchParams, setSearchParams] = useSearchParams();
  const tab = searchParams.get("view") ?? "list";
  const setTab = (v: string) => {
    const next = new URLSearchParams(searchParams);
    next.set("view", v);
    setSearchParams(next, { replace: true });
  };
  return (
    <div>
      <div className="overflow-hidden rounded-lg bg-white ring-1 ring-slate-200">
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
          <div>
            <h1 className="text-lg font-medium">
              <span className="mr-1">💬</span> LinkedIn content
            </h1>
            <div className="mt-0.5 text-xs text-slate-500">
              Schrijf, plan en publiceer LinkedIn-posts vanuit één plek
            </div>
          </div>
          <Link to="/social/new"
            className="inline-flex items-center gap-1 rounded-md bg-brand-500 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-600">
            + Nieuwe post
          </Link>
        </div>
        <div className="flex gap-1 border-b border-slate-200 px-4">
          {[["list","Lijst"],["calendar","Kalender"]].map(([id, label]) => (
            <button key={id} onClick={() => setTab(id)}
              className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium ${
                tab === id ? "border-brand-500 text-slate-900" : "border-transparent text-slate-500 hover:text-slate-800"
              }`}>
              {label}
            </button>
          ))}
        </div>
        <div className="p-4">
          {tab === "list" ? <ListView /> : <CalendarView />}
        </div>
      </div>
    </div>
  );
}

function ListView() {
  const [status, setStatus] = useState<string>("");
  const summaryQ = useQuery<Summary>({
    queryKey: ["/social/posts/summary"],
    queryFn: () => api<Summary>("/social/posts/summary"),
  });
  const postsQ = useQuery<Post[]>({
    queryKey: ["/social/posts", status],
    queryFn: () => api<Post[]>(status ? `/social/posts?status=${status}` : "/social/posts"),
  });
  const s = summaryQ.data;
  const posts = postsQ.data ?? [];
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <KPI label="Concept" value={String(s?.drafts ?? 0)} />
        <KPI label="Ingepland" value={String(s?.scheduled ?? 0)} tone="amber" />
        <KPI label="Gepubliceerd 30d" value={String(s?.published_30d ?? 0)} tone="emerald" />
        <KPI label="Engagement 30d" value={String(s?.engagements_30d ?? 0)} sub={`${s?.impressions_30d ?? 0} impressions`} />
      </div>
      <div className="flex flex-wrap items-center gap-1 border-b border-slate-200 pb-2">
        {[["","Alle"],["draft","Concept"],["scheduled","Ingepland"],["published","Gepubliceerd"],["failed","Mislukt"]].map(([id, label]) => (
          <button key={id} onClick={() => setStatus(id)}
            className={`rounded-md px-3 py-1.5 text-sm font-medium border ${
              status === id ? "border-brand-500 bg-brand-500 text-white" : "border-slate-200 bg-white text-slate-700 hover:bg-slate-50"
            }`}>
            {label}
          </button>
        ))}
      </div>
      {postsQ.isLoading && <div className="text-sm text-slate-500">Bezig met laden…</div>}
      {!postsQ.isLoading && posts.length === 0 && <EmptyState />}
      <div className="space-y-2">
        {posts.map((p) => <PostRow key={p.id} post={p} />)}
      </div>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="rounded-md border border-dashed border-slate-300 bg-slate-50 p-10 text-center text-sm text-slate-500">
      <div className="text-3xl mb-2">✏️</div>
      <div className="font-medium text-slate-700">Nog geen posts</div>
      <div className="mt-1">Klik op <b>+ Nieuwe post</b> om je eerste LinkedIn-bericht te maken.</div>
    </div>
  );
}

function PostRow({ post }: { post: Post }) {
  const qc = useQueryClient();
  const duplicateMut = useMutation({
    mutationFn: () => api<Post>(`/social/posts/${post.id}/duplicate`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["/social/posts"] }),
  });
  const deleteMut = useMutation({
    mutationFn: () => api(`/social/posts/${post.id}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["/social/posts"] });
      qc.invalidateQueries({ queryKey: ["/social/posts/summary"] });
    },
  });
  const displayTime = post.status === "published" ? post.published_at :
    post.status === "scheduled" ? post.scheduled_at : post.updated_at;
  return (
    <div className="rounded-md border border-slate-200 bg-white p-3">
      <div className="grid grid-cols-[minmax(0,2fr)_140px_140px_auto] gap-3 items-start">
        <Link to={`/social/${post.id}`} className="min-w-0 hover:opacity-80">
          <div className="flex items-baseline gap-2 flex-wrap">
            <div className="truncate font-medium">
              {post.title || (post.body.split("\n")[0]?.slice(0, 60) || "(zonder titel)")}
            </div>
            <StatusBadge status={post.status} />
          </div>
          <div className="text-[11px] text-slate-500 line-clamp-1 mt-1">{post.body}</div>
          <div className="text-[10px] text-slate-500 mt-1 flex items-center gap-2 flex-wrap">
            {post.media.length > 0 && <span>📎 {post.media.length}</span>}
            {post.destinations.map((d) => (
              <span key={d.target_urn} className="rounded bg-slate-100 px-1.5 py-0.5">
                {d.target_type === "person" ? "👤" : "🏢"} {d.target_name}
              </span>
            ))}
          </div>
        </Link>
        <div className="text-xs text-slate-600">
          <div className="text-[10px] uppercase tracking-wider text-slate-500">
            {post.status === "published" ? "Gepubliceerd" : post.status === "scheduled" ? "Ingepland" : "Bijgewerkt"}
          </div>
          <div>{fmtDate(displayTime, true)}</div>
        </div>
        <div className="text-xs text-slate-600">
          {post.status === "published" && (
            <>
              <div className="text-[10px] uppercase tracking-wider text-slate-500">Auteur</div>
              <div className="truncate">{post.creator_name ?? "—"}</div>
            </>
          )}
          {post.status === "failed" && post.last_error && (
            <div className="text-[10px] text-red-700 line-clamp-2">{post.last_error}</div>
          )}
        </div>
        <div className="flex gap-1">
          <Link to={`/social/${post.id}`} className="rounded-md border border-slate-300 px-2 py-1 text-xs hover:bg-slate-50">Open</Link>
          <button onClick={() => duplicateMut.mutate()} disabled={duplicateMut.isPending}
            className="rounded-md border border-slate-300 px-2 py-1 text-xs hover:bg-slate-50" title="Dupliceer">Dupliceer</button>
          {post.status !== "published" && post.status !== "publishing" && (
            <button onClick={() => { if (confirm("Deze post verwijderen?")) deleteMut.mutate(); }}
              className="rounded-md border border-slate-300 px-2 py-1 text-xs text-red-700 hover:bg-red-50">Verwijder</button>
          )}
        </div>
      </div>
    </div>
  );
}

function CalendarView() {
  const today = new Date();
  const [monthStart, setMonthStart] = useState(new Date(today.getFullYear(), today.getMonth(), 1));
  const monthEnd = new Date(monthStart.getFullYear(), monthStart.getMonth() + 1, 0, 23, 59, 59);
  const postsQ = useQuery<Post[]>({
    queryKey: ["/social/posts/calendar", monthStart.toISOString()],
    queryFn: () => api<Post[]>(`/social/posts?from_dt=${monthStart.toISOString()}&to_dt=${monthEnd.toISOString()}&limit=500`),
  });
  const byDay = useMemo(() => {
    const m = new Map<string, Post[]>();
    for (const p of postsQ.data ?? []) {
      const t = p.scheduled_at || p.published_at || p.created_at;
      const d = new Date(t);
      const key = `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
      if (!m.has(key)) m.set(key, []);
      m.get(key)!.push(p);
    }
    return m;
  }, [postsQ.data]);
  const monthLabel = monthStart.toLocaleDateString("nl-NL", { month: "long", year: "numeric" });
  const firstDay = monthStart.getDay() === 0 ? 6 : monthStart.getDay() - 1;
  const lastDate = monthEnd.getDate();
  const cells: (Date | null)[] = [];
  for (let i = 0; i < firstDay; i++) cells.push(null);
  for (let d = 1; d <= lastDate; d++) cells.push(new Date(monthStart.getFullYear(), monthStart.getMonth(), d));
  while (cells.length % 7 !== 0) cells.push(null);
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <button onClick={() => setMonthStart(new Date(monthStart.getFullYear(), monthStart.getMonth() - 1, 1))}
          className="rounded-md border border-slate-300 px-2 py-1 text-sm hover:bg-slate-50">← Vorige</button>
        <div className="text-sm font-medium capitalize">{monthLabel}</div>
        <button onClick={() => setMonthStart(new Date(monthStart.getFullYear(), monthStart.getMonth() + 1, 1))}
          className="rounded-md border border-slate-300 px-2 py-1 text-sm hover:bg-slate-50">Volgende →</button>
      </div>
      <div className="grid grid-cols-7 gap-1 text-[10px] uppercase tracking-wider text-slate-500">
        {["ma","di","wo","do","vr","za","zo"].map((d) => <div key={d} className="px-2 py-1">{d}</div>)}
      </div>
      <div className="grid grid-cols-7 gap-1">
        {cells.map((d, i) => {
          if (!d) return <div key={i} className="h-24 rounded-md bg-slate-50" />;
          const key = `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
          const posts = byDay.get(key) ?? [];
          const isToday = d.getDate() === today.getDate() && d.getMonth() === today.getMonth() && d.getFullYear() === today.getFullYear();
          return (
            <div key={i} className={`h-24 rounded-md border p-1 overflow-hidden text-xs ${
              isToday ? "border-brand-500 bg-brand-50" : "border-slate-200 bg-white"
            }`}>
              <div className="text-[10px] font-medium text-slate-500">{d.getDate()}</div>
              <div className="space-y-0.5 mt-0.5">
                {posts.slice(0, 3).map((p) => (
                  <Link key={p.id} to={`/social/${p.id}`}
                    className="block truncate rounded px-1 py-0.5 text-[10px] hover:opacity-80"
                    style={{
                      backgroundColor: STATUS_STYLES[p.status]?.bg ?? "#F1F5F9",
                      color: STATUS_STYLES[p.status]?.text ?? "#475569",
                    }}
                    title={p.title ?? p.body}>
                    {p.title || p.body.slice(0, 30)}
                  </Link>
                ))}
                {posts.length > 3 && <div className="text-[10px] text-slate-500">+{posts.length - 3} meer</div>}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function KPI({ label, value, sub, tone = "default" }: { label: string; value: string; sub?: string; tone?: "default" | "amber" | "emerald" | "red" }) {
  const toneCls = { default: "text-slate-900", amber: "text-amber-700", emerald: "text-emerald-700", red: "text-red-700" }[tone];
  return (
    <div className="rounded-md border border-slate-200 bg-white p-3">
      <div className="text-[10px] uppercase tracking-wider text-slate-500">{label}</div>
      <div className={`mt-1 text-xl font-medium tabular-nums ${toneCls}`}>{value}</div>
      {sub && <div className="text-[11px] text-slate-500">{sub}</div>}
    </div>
  );
}

export function SocialPostEditor() {
  const { id: routeId } = useParams<{ id?: string }>();
  const isNew = !routeId || routeId === "new";
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [actionError, setActionError] = useState<string | null>(null);

  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [selectedDest, setSelectedDest] = useState<Destination[]>([]);
  const [scheduledLocal, setScheduledLocal] = useState("");
  const [media, setMedia] = useState<Media[]>([]);
  const [post, setPost] = useState<Post | null>(null);

  const fileRef = useRef<HTMLInputElement>(null);

  const destsQ = useQuery<Destination[]>({
    queryKey: ["/social/destinations"],
    queryFn: () => api<Destination[]>("/social/destinations"),
    retry: false,
  });

  const existingQ = useQuery<Post>({
    queryKey: ["/social/posts", routeId],
    queryFn: () => api<Post>(`/social/posts/${routeId}`),
    enabled: !isNew,
  });

  useEffect(() => {
    if (existingQ.data && !isNew) {
      const p = existingQ.data;
      setPost(p);
      setTitle(p.title ?? "");
      setBody(p.body ?? "");
      setSelectedDest(p.destinations ?? []);
      setScheduledLocal(toLocalInput(p.scheduled_at));
      setMedia(p.media ?? []);
    }
  }, [existingQ.data, isNew]);

  const upsertMut = useMutation({
    mutationFn: async (payload: { status: "draft" | "scheduled" }) => {
      const body_payload = {
        title: title || undefined,
        body,
        destinations: selectedDest,
        scheduled_at: scheduledLocal ? fromLocalInput(scheduledLocal) : null,
        status: payload.status,
      };
      if (isNew) {
        return api<Post>("/social/posts", { method: "POST", body: JSON.stringify(body_payload) });
      }
      return api<Post>(`/social/posts/${routeId}`, { method: "PATCH", body: JSON.stringify(body_payload) });
    },
    onSuccess: (p) => {
      qc.invalidateQueries({ queryKey: ["/social/posts"] });
      qc.invalidateQueries({ queryKey: ["/social/posts/summary"] });
      if (isNew) navigate(`/social/${p.id}`, { replace: true });
    },
    onError: (e) => setActionError(e instanceof ApiError ? e.detail : "Opslaan mislukt"),
  });

  const publishMut = useMutation({
    mutationFn: async () => {
      let id = routeId;
      if (isNew || !post) {
        const saved = await upsertMut.mutateAsync({ status: "draft" });
        id = saved.id;
      } else {
        await upsertMut.mutateAsync({ status: "draft" });
      }
      return api<{ ok: boolean; detail: string; results: PublishResult[] }>(
        `/social/posts/${id}/publish-now`, { method: "POST" }
      );
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["/social/posts"] });
      qc.invalidateQueries({ queryKey: ["/social/posts/summary"] });
      navigate("/social", { replace: true });
    },
    onError: (e) => setActionError(e instanceof ApiError ? e.detail : "Publiceren mislukt"),
  });

  const uploadFiles = async (files: FileList) => {
    if (!files.length) return;
    let id = routeId;
    if (isNew || !post) {
      const saved = await upsertMut.mutateAsync({ status: "draft" });
      id = saved.id;
    }
    for (const f of Array.from(files)) {
      const fd = new FormData();
      fd.append("file", f);
      const r = await fetch(`/api/v1/social/media?post_id=${id}`, {
        method: "POST",
        headers: { Authorization: `Bearer ${localStorage.getItem("access_token")}` },
        body: fd,
      });
      if (!r.ok) {
        setActionError("Upload mislukt: " + (await r.text()).slice(0, 200));
        continue;
      }
    }
    if (id && !isNew) {
      const reloaded = await api<Post>(`/social/posts/${id}`);
      setMedia(reloaded.media);
      setPost(reloaded);
    } else if (id) {
      navigate(`/social/${id}`, { replace: true });
    }
  };

  const removeMedia = async (mid: string) => {
    await api(`/social/media/${mid}`, { method: "DELETE" });
    setMedia(media.filter((m) => m.id !== mid));
  };

  const isReadOnly = post?.status === "published" || post?.status === "publishing";

  return (
    <div>
      <div className="overflow-hidden rounded-lg bg-white ring-1 ring-slate-200">
        <div className="border-b border-slate-200 px-4 py-3">
          <Link to="/social" className="text-xs text-slate-500 hover:text-slate-900">← Alle posts</Link>
          <h1 className="mt-1 text-lg font-medium">
            {isNew ? "Nieuwe LinkedIn post" : post?.title || "Post bewerken"}
          </h1>
          {post && (
            <div className="mt-1 flex items-center gap-2 text-xs text-slate-500">
              <StatusBadge status={post.status} />
              {post.published_at && <span>Gepubliceerd: {fmtDate(post.published_at, true)}</span>}
              {post.scheduled_at && post.status === "scheduled" && <span>Wordt gepost op {fmtDate(post.scheduled_at, true)}</span>}
            </div>
          )}
        </div>
        {actionError && <div className="px-4 py-2 bg-red-50 text-sm text-red-800">{actionError}</div>}
        {post?.status === "failed" && post.last_error && (
          <div className="px-4 py-2 bg-amber-50 text-sm text-amber-900">
            <strong>Vorige poging mislukt:</strong> {post.last_error}
          </div>
        )}
        <div className="grid gap-4 p-4 md:grid-cols-[1fr_400px]">
          <div className="space-y-3">
            <label className="block">
              <span className="block text-[11px] uppercase tracking-wider text-slate-500 mb-1">
                Interne titel (niet zichtbaar op LinkedIn)
              </span>
              <input value={title} disabled={isReadOnly} onChange={(e) => setTitle(e.target.value)}
                placeholder="bv. Productlancering Q2"
                className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm" />
            </label>
            <label className="block">
              <div className="flex justify-between text-[11px] uppercase tracking-wider text-slate-500 mb-1">
                <span>Post tekst</span>
                <span className={body.length > LI_CHAR_LIMIT ? "text-red-700" : ""}>
                  {body.length} / {LI_CHAR_LIMIT}
                </span>
              </div>
              <textarea value={body} disabled={isReadOnly} onChange={(e) => setBody(e.target.value)} rows={14}
                placeholder="Schrijf je post hier… Tip: laat de eerste 2 regels pakkend zijn — daarna komt 'lees meer'."
                className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm leading-relaxed" />
            </label>
            <div>
              <div className="flex justify-between items-center text-[11px] uppercase tracking-wider text-slate-500 mb-1">
                <span>Media ({media.length})</span>
                {!isReadOnly && (
                  <button onClick={() => fileRef.current?.click()}
                    className="rounded-md border border-slate-300 px-2 py-1 text-xs hover:bg-slate-50">+ Upload</button>
                )}
              </div>
              <input ref={fileRef} type="file" accept="image/*,video/*" multiple className="hidden"
                onChange={(e) => { if (e.target.files) uploadFiles(e.target.files); e.target.value = ""; }} />
              <div className="grid grid-cols-3 gap-2">
                {media.map((m) => (
                  <div key={m.id} className="relative group rounded-md border border-slate-200 overflow-hidden bg-slate-50">
                    {m.mime_type.startsWith("image/") ? (
                      <img src={m.url} alt={m.alt_text ?? ""} className="w-full h-24 object-cover" />
                    ) : (
                      <video src={m.url} className="w-full h-24 object-cover" />
                    )}
                    {!isReadOnly && (
                      <button onClick={() => removeMedia(m.id)}
                        className="absolute top-1 right-1 rounded-full bg-white/90 px-1.5 text-xs opacity-0 group-hover:opacity-100"
                        title="Verwijder">×</button>
                    )}
                    <div className="px-1 py-0.5 text-[10px] text-slate-500 truncate">{m.filename}</div>
                  </div>
                ))}
                {media.length === 0 && (
                  <div className="col-span-3 rounded-md border border-dashed border-slate-300 bg-slate-50 p-6 text-center text-xs text-slate-500">
                    Klik op + Upload om afbeeldingen toe te voegen
                  </div>
                )}
              </div>
            </div>
            <div>
              <div className="text-[11px] uppercase tracking-wider text-slate-500 mb-1">Posten naar</div>
              {destsQ.isError && (
                <div className="rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-900">
                  Kan LinkedIn-bestemmingen niet ophalen. Controleer Settings → Integrations → LinkedIn (access token).
                </div>
              )}
              {!destsQ.isError && (destsQ.data?.length ?? 0) === 0 && !destsQ.isLoading && (
                <div className="rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-900">
                  Geen LinkedIn-bestemmingen gevonden. Zorg dat er een geldige access_token in de LinkedIn-integratie staat.
                </div>
              )}
              <div className="space-y-1">
                {(destsQ.data ?? []).map((d) => {
                  const checked = selectedDest.some((s) => s.target_urn === d.target_urn);
                  return (
                    <label key={d.target_urn} className="flex items-center gap-2 rounded-md border border-slate-200 px-3 py-2 text-sm hover:bg-slate-50">
                      <input type="checkbox" checked={checked} disabled={isReadOnly}
                        onChange={(e) => {
                          if (e.target.checked) setSelectedDest([...selectedDest, d]);
                          else setSelectedDest(selectedDest.filter((x) => x.target_urn !== d.target_urn));
                        }} />
                      <span className="text-base">{d.target_type === "person" ? "👤" : "🏢"}</span>
                      <span className="flex-1">{d.target_name}</span>
                      <span className="text-[10px] text-slate-500">{d.target_type}</span>
                    </label>
                  );
                })}
              </div>
            </div>
            <label className="block">
              <span className="block text-[11px] uppercase tracking-wider text-slate-500 mb-1">Inplannen voor (optioneel)</span>
              <input type="datetime-local" value={scheduledLocal} disabled={isReadOnly}
                onChange={(e) => setScheduledLocal(e.target.value)}
                className="rounded-md border border-slate-300 px-3 py-2 text-sm" />
              <p className="mt-1 text-[11px] text-slate-500">
                Laat leeg om als concept op te slaan. Met datum + tijd wordt het automatisch gepost.
              </p>
            </label>
          </div>
          <div className="space-y-3">
            <div className="text-[11px] uppercase tracking-wider text-slate-500">LinkedIn preview</div>
            <LinkedInPreview body={body} media={media}
              authorName={selectedDest[0]?.target_name ?? "Jouw naam"}
              authorType={selectedDest[0]?.target_type ?? "person"} />
            {!isReadOnly && (
              <div className="rounded-md border border-slate-200 bg-slate-50 p-3 space-y-2">
                <button disabled={upsertMut.isPending || !body.trim()}
                  onClick={() => upsertMut.mutate({ status: "draft" })}
                  className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-medium hover:bg-slate-100 disabled:opacity-50">
                  {upsertMut.isPending ? "Bezig…" : "Concept opslaan"}
                </button>
                <button
                  disabled={upsertMut.isPending || !body.trim() || !scheduledLocal || selectedDest.length === 0}
                  onClick={() => upsertMut.mutate({ status: "scheduled" })}
                  className="w-full rounded-md bg-amber-500 px-3 py-2 text-sm font-medium text-white hover:bg-amber-600 disabled:opacity-50"
                  title={!scheduledLocal ? "Kies eerst datum + tijd" : selectedDest.length === 0 ? "Kies eerst een bestemming" : ""}>
                  {scheduledLocal ? `Inplannen voor ${fmtDate(fromLocalInput(scheduledLocal), true)}` : "Inplannen"}
                </button>
                <button
                  disabled={publishMut.isPending || !body.trim() || selectedDest.length === 0}
                  onClick={() => publishMut.mutate()}
                  className="w-full rounded-md bg-brand-500 px-3 py-2 text-sm font-medium text-white hover:bg-brand-600 disabled:opacity-50"
                  title={selectedDest.length === 0 ? "Kies eerst een bestemming" : ""}>
                  {publishMut.isPending ? "Bezig met posten…" : "Nu publiceren"}
                </button>
              </div>
            )}
            {post?.status === "published" && <PostAnalyticsPanel postId={post.id} />}

            {post?.publish_result && post.publish_result.length > 0 && (
              <div className="rounded-md border border-slate-200 bg-white p-3 space-y-2">
                <div className="text-[11px] uppercase tracking-wider text-slate-500">Publicatie resultaat</div>
                {post.publish_result.map((r, i) => (
                  <div key={i} className="text-xs">
                    <div className="flex items-center gap-1">
                      <span>{r.error ? "❌" : "✅"}</span>
                      <span className="truncate">{r.target_name}</span>
                    </div>
                    {r.error && <div className="text-red-700 ml-4">{r.error}</div>}
                    {r.post_url && (
                      <a href={r.post_url} target="_blank" rel="noreferrer" className="text-brand-600 hover:underline ml-4">
                        Bekijk op LinkedIn ↗
                      </a>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function LinkedInPreview({
  body, media, authorName, authorType,
}: { body: string; media: Media[]; authorName: string; authorType: string }) {
  const initials = authorName.split(/\s+/).map((s) => s[0]).slice(0, 2).join("").toUpperCase();
  return (
    <div className="rounded-md border border-slate-300 bg-white overflow-hidden shadow-sm">
      <div className="flex items-center gap-2 p-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-full bg-sky-100 text-sky-800 text-xs font-bold">
          {initials || "?"}
        </div>
        <div className="min-w-0">
          <div className="text-sm font-semibold truncate">{authorName}</div>
          <div className="text-[10px] text-slate-500">
            {authorType === "organization" ? "Bedrijfspagina" : "Persoonlijk profiel"} · zojuist · 🌐
          </div>
        </div>
      </div>
      <div className="px-3 pb-3 text-sm whitespace-pre-wrap break-words">
        {body || <span className="text-slate-400">(geen tekst)</span>}
      </div>
      {media.length > 0 && (
        <div className={`grid gap-0.5 ${media.length === 1 ? "grid-cols-1" : "grid-cols-2"} bg-slate-100`}>
          {media.slice(0, 4).map((m) => (
            m.mime_type.startsWith("image/") ? (
              <img key={m.id} src={m.url} alt={m.alt_text ?? ""} className="w-full max-h-72 object-cover" />
            ) : (
              <video key={m.id} src={m.url} className="w-full max-h-72 object-cover" />
            )
          ))}
        </div>
      )}
      <div className="flex justify-between items-center px-3 py-2 border-t border-slate-200 text-[11px] text-slate-500">
        <span>👍 ❤️ 👏 32</span>
        <span>4 reacties</span>
      </div>
      <div className="grid grid-cols-4 border-t border-slate-200 text-xs text-slate-600">
        <button className="py-2 hover:bg-slate-50">👍 Like</button>
        <button className="py-2 hover:bg-slate-50">💬 Reageer</button>
        <button className="py-2 hover:bg-slate-50">🔁 Repost</button>
        <button className="py-2 hover:bg-slate-50">📤 Verstuur</button>
      </div>
    </div>
  );
}

// ===== Per-post analytics panel =====

type MetricSnapshot = {
  snapshot_at: string;
  platform_post_id: string;
  impressions: number;
  likes: number;
  comments: number;
  shares: number;
  clicks: number;
  engagement_rate: number | null;
};

function PostAnalyticsPanel({ postId }: { postId: string }) {
  const qc = useQueryClient();
  const snapshotsQ = useQuery<MetricSnapshot[]>({
    queryKey: ["/social/posts/metrics", postId],
    queryFn: () => api<MetricSnapshot[]>(`/social/posts/${postId}/metrics`),
  });

  const refreshMut = useMutation({
    mutationFn: () => api<{ ok: boolean; snapshots_added: number }>(
      `/social/posts/${postId}/metrics/refresh`,
      { method: "POST" }
    ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["/social/posts/metrics", postId] });
    },
  });

  const snapshots = snapshotsQ.data ?? [];

  // Aggregate across all destinations for the same snapshot_at
  type AggPoint = {
    snapshot_at: string;
    impressions: number;
    likes: number;
    comments: number;
    shares: number;
    clicks: number;
  };
  const byTime = new Map<string, AggPoint>();
  for (const s of snapshots) {
    const key = s.snapshot_at;
    const existing = byTime.get(key);
    if (existing) {
      existing.impressions += s.impressions;
      existing.likes += s.likes;
      existing.comments += s.comments;
      existing.shares += s.shares;
      existing.clicks += s.clicks;
    } else {
      byTime.set(key, {
        snapshot_at: key,
        impressions: s.impressions,
        likes: s.likes,
        comments: s.comments,
        shares: s.shares,
        clicks: s.clicks,
      });
    }
  }
  const chartData = Array.from(byTime.values()).map((p) => ({
    ...p,
    label: new Date(p.snapshot_at).toLocaleDateString("nl-NL", { day: "numeric", month: "short" }),
    engagements: p.likes + p.comments + p.shares + p.clicks,
  }));

  // Latest totals across destinations
  const totals = chartData.length > 0 ? chartData[chartData.length - 1] : {
    impressions: 0, likes: 0, comments: 0, shares: 0, clicks: 0, engagements: 0,
  };

  return (
    <div className="rounded-md border border-slate-200 bg-white p-3 space-y-3">
      <div className="flex items-center justify-between">
        <div className="text-[11px] uppercase tracking-wider text-slate-500">Analytics</div>
        <button
          type="button"
          onClick={() => refreshMut.mutate()}
          disabled={refreshMut.isPending}
          className="rounded-md border border-slate-300 bg-white px-2 py-1 text-xs hover:bg-slate-50 disabled:opacity-50"
        >
          {refreshMut.isPending ? "Bezig…" : "↻ Ververs"}
        </button>
      </div>

      {snapshotsQ.isLoading && <div className="text-xs text-slate-500">Bezig met laden…</div>}

      {snapshots.length === 0 && !snapshotsQ.isLoading && (
        <div className="rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-900">
          Nog geen metrics-snapshot. Klik op <strong>↻ Ververs</strong> om de eerste op te halen.
          LinkedIn levert impressions alleen aan apps met Marketing Developer Platform-toegang;
          likes + comments werken altijd.
        </div>
      )}

      {snapshots.length > 0 && (
        <>
          <div className="grid grid-cols-3 gap-2 md:grid-cols-5 text-xs">
            <MetricCard label="Likes" value={totals.likes} />
            <MetricCard label="Comments" value={totals.comments} />
            <MetricCard label="Shares" value={totals.shares} />
            <MetricCard label="Clicks" value={totals.clicks} />
            <MetricCard label="Impressions" value={totals.impressions} />
          </div>

          {chartData.length >= 2 && (
            <div className="h-48 -mx-1">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartData} margin={{ top: 4, right: 8, bottom: 0, left: -20 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                  <XAxis dataKey="label" tick={{ fontSize: 10 }} />
                  <YAxis tick={{ fontSize: 10 }} />
                  <Tooltip />
                  <Line type="monotone" dataKey="engagements" stroke="#10b981" strokeWidth={2} dot={false} name="Engagement" />
                  {totals.impressions > 0 && (
                    <Line type="monotone" dataKey="impressions" stroke="#3b82f6" strokeWidth={1.5} dot={false} name="Impressions" />
                  )}
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}

          <details className="text-xs">
            <summary className="cursor-pointer text-slate-500 hover:text-slate-800">
              {snapshots.length} snapshot{snapshots.length === 1 ? "" : "s"} — bekijk lijst
            </summary>
            <ul className="mt-1 max-h-32 overflow-y-auto divide-y divide-slate-100">
              {snapshots.slice().reverse().map((s, i) => (
                <li key={i} className="py-1 tabular-nums text-[11px] text-slate-600 flex justify-between">
                  <span>{new Date(s.snapshot_at).toLocaleString("nl-NL")}</span>
                  <span>{s.likes}L · {s.comments}C · {s.shares}S{s.impressions > 0 && ` · ${s.impressions}I`}</span>
                </li>
              ))}
            </ul>
          </details>
        </>
      )}
    </div>
  );
}

function MetricCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded border border-slate-200 bg-slate-50 px-2 py-1.5">
      <div className="text-[9px] uppercase tracking-wider text-slate-500">{label}</div>
      <div className="text-base font-medium tabular-nums">{value.toLocaleString("nl-NL")}</div>
    </div>
  );
}
