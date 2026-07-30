"use client";

import { useQuery } from "@tanstack/react-query";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getStats } from "@/lib/api";
import type { LatencyPercentiles, StatsResponse } from "@/types/api";

const STAGES: { key: keyof StatsResponse; label: string }[] = [
  { key: "rewrite_ms", label: "Query rewrite" },
  { key: "expansion_ms", label: "Multi-query expansion" },
  { key: "retrieval_ms", label: "Hybrid retrieval + rerank" },
  { key: "generation_ms", label: "LLM generation" },
];

function StatTile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-xs font-medium uppercase tracking-wide text-zinc-500">
          {label}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-2xl font-semibold tabular-nums">{value}</p>
        {hint && <p className="mt-1 text-xs text-zinc-400">{hint}</p>}
      </CardContent>
    </Card>
  );
}

export function StatsView() {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["stats"],
    queryFn: getStats,
    refetchInterval: 5000,
  });

  if (isLoading) return <p className="text-sm text-zinc-400">Loading telemetry…</p>;
  if (isError) return <p className="text-sm text-red-600">{(error as Error).message}</p>;
  if (!data || data.n === 0) {
    return (
      <p className="text-sm text-zinc-400">
        No queries recorded yet in this API process. Ask something in the chat first.
      </p>
    );
  }

  const percent = (v?: number) => (v === undefined ? "—" : `${(v * 100).toFixed(1)}%`);

  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-3">
        <StatTile label="Queries (rolling)" value={String(data.n)} hint="last ~500 requests" />
        <StatTile
          label="Abstention rate"
          value={percent(data.abstention_rate)}
          hint="drift here = recalibrate the rerank score floor"
        />
        <StatTile label="Cache hit rate" value={percent(data.cache_hit_rate)} />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Pipeline latency (ms)</CardTitle>
        </CardHeader>
        <CardContent>
          <table data-testid="stats-table" className="w-full text-sm">
            <thead>
              <tr className="border-b border-zinc-200 text-left text-xs uppercase tracking-wide text-zinc-500">
                <th className="pb-2 font-medium">Stage</th>
                <th className="pb-2 text-right font-medium">p50</th>
                <th className="pb-2 text-right font-medium">p95</th>
              </tr>
            </thead>
            <tbody>
              {STAGES.map(({ key, label }) => {
                const stage = data[key] as LatencyPercentiles | undefined;
                return (
                  <tr key={key} className="border-b border-zinc-100 last:border-0">
                    <td className="py-2">{label}</td>
                    <td className="py-2 text-right tabular-nums">
                      {stage ? stage.p50.toLocaleString() : "—"}
                    </td>
                    <td className="py-2 text-right tabular-nums">
                      {stage ? stage.p95.toLocaleString() : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </div>
  );
}
