/** Deals kanban: one column per stage, drag a deal between columns to
 *  change its stage. Status (open / won / lost) and closed_at are
 *  derived server-side from the destination stage's is_won / is_lost flags.
 */

import { useMemo } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  DndContext,
  PointerSensor,
  KeyboardSensor,
  useDroppable,
  useDraggable,
  useSensor,
  useSensors,
  type DragEndEvent,
  closestCorners,
} from "@dnd-kit/core";
import { api } from "@/lib/api";
import { fmtMoney, StatusBadge } from "@/lib/format";

type Deal = {
  id: string;
  name: string;
  amount: number | null;
  currency: string;
  status: "open" | "won" | "lost";
  pipeline_id: string;
  stage_id: string;
  company_id: string | null;
  primary_contact_id: string | null;
};
type Stage = { id: string; name: string; position: number; is_won: boolean; is_lost: boolean };
type Pipeline = { id: string; name: string; is_default: boolean };
type Page<T> = { items: T[]; total: number };

export function DealsKanban() {
  const qc = useQueryClient();

  const pipelinesQ = useQuery<Pipeline[]>({
    queryKey: ["pipelines"],
    queryFn: () => api<Pipeline[]>("/pipelines"),
  });
  const defaultPipeline =
    pipelinesQ.data?.find((p) => p.is_default) ?? pipelinesQ.data?.[0];

  const stagesQ = useQuery<Stage[]>({
    queryKey: ["stages", defaultPipeline?.id],
    queryFn: () => api<Stage[]>(`/pipelines/${defaultPipeline!.id}/stages`),
    enabled: !!defaultPipeline?.id,
  });

  const dealsQ = useQuery<Page<Deal>>({
    queryKey: ["/deals"],
    queryFn: () => api<Page<Deal>>("/deals?limit=500"),
  });

  // Stage-change mutation with optimistic update on the deals list.
  const moveMut = useMutation({
    mutationFn: ({ id, stage_id }: { id: string; stage_id: string }) =>
      api<Deal>(`/deals/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ stage_id }),
      }),
    onMutate: async ({ id, stage_id }) => {
      await qc.cancelQueries({ queryKey: ["/deals"] });
      const prev = qc.getQueryData<Page<Deal>>(["/deals"]);
      if (prev) {
        qc.setQueryData<Page<Deal>>(["/deals"], {
          ...prev,
          items: prev.items.map((d) =>
            d.id === id ? { ...d, stage_id } : d,
          ),
        });
      }
      return { prev };
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.prev) qc.setQueryData(["/deals"], ctx.prev);
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["/deals"] });
    },
  });

  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: { distance: 5 }, // ignore tiny accidental drags
    }),
    useSensor(KeyboardSensor),
  );

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over) return;
    const dealId = String(active.id);
    const newStageId = String(over.id);
    const deal = dealsQ.data?.items.find((d) => d.id === dealId);
    if (!deal || deal.stage_id === newStageId) return;
    moveMut.mutate({ id: dealId, stage_id: newStageId });
  }

  // Group deals by stage for fast render.
  const dealsByStage = useMemo(() => {
    const grouped: Record<string, Deal[]> = {};
    for (const d of dealsQ.data?.items ?? []) {
      (grouped[d.stage_id] ||= []).push(d);
    }
    return grouped;
  }, [dealsQ.data]);

  if (!defaultPipeline)
    return (
      <div className="text-slate-500">
        No pipeline configured for this organization yet.
      </div>
    );

  if (stagesQ.isLoading || dealsQ.isLoading)
    return <div className="text-slate-500">Loading…</div>;

  const stages = stagesQ.data ?? [];

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCorners}
      onDragEnd={handleDragEnd}
    >
      <div className="-mx-2 flex gap-2 overflow-x-auto pb-2">
        {stages.map((stage) => (
          <StageColumn
            key={stage.id}
            stage={stage}
            deals={dealsByStage[stage.id] ?? []}
          />
        ))}
      </div>
    </DndContext>
  );
}

function StageColumn({ stage, deals }: { stage: Stage; deals: Deal[] }) {
  const { setNodeRef, isOver } = useDroppable({ id: stage.id });
  const total = deals.reduce((sum, d) => sum + Number(d.amount ?? 0), 0);
  const currency = deals[0]?.currency ?? "EUR";

  const accent = stage.is_won
    ? "bg-green-50 border-green-200"
    : stage.is_lost
      ? "bg-red-50 border-red-200"
      : "bg-slate-50 border-slate-200";

  return (
    <div
      ref={setNodeRef}
      className={`min-w-[280px] flex-1 rounded-lg border ${accent} ${
        isOver ? "ring-2 ring-slate-900/30" : ""
      }`}
    >
      <div className="flex items-center justify-between px-3 py-2 border-b border-slate-200">
        <div className="text-sm font-semibold text-slate-700">{stage.name}</div>
        <div className="text-xs text-slate-500">
          {deals.length} · {fmtMoney(total, currency)}
        </div>
      </div>
      <div className="space-y-2 p-2 min-h-[60px]">
        {deals.map((deal) => (
          <DealCard key={deal.id} deal={deal} />
        ))}
        {deals.length === 0 && (
          <div className="text-center text-xs text-slate-400 py-4">
            Drop deals here
          </div>
        )}
      </div>
    </div>
  );
}

function DealCard({ deal }: { deal: Deal }) {
  const { attributes, listeners, setNodeRef, transform, isDragging } =
    useDraggable({ id: deal.id });

  // CSS transform during drag.
  const style: React.CSSProperties = transform
    ? {
        transform: `translate3d(${transform.x}px, ${transform.y}px, 0)`,
        zIndex: 50,
      }
    : {};

  return (
    <div
      ref={setNodeRef}
      style={style}
      {...attributes}
      {...listeners}
      className={`rounded-md bg-white p-3 shadow-sm ring-1 ring-slate-200 cursor-grab active:cursor-grabbing ${
        isDragging ? "opacity-50" : ""
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <Link
          to={`/deals/${deal.id}`}
          onClick={(e) => e.stopPropagation()}
          className="text-sm font-medium text-slate-900 hover:underline"
        >
          {deal.name}
        </Link>
        {deal.status !== "open" && <StatusBadge status={deal.status} />}
      </div>
      <div className="mt-1 text-xs tabular-nums text-slate-600">
        {fmtMoney(deal.amount, deal.currency)}
      </div>
    </div>
  );
}
