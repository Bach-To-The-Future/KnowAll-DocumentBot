"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileUp, Loader2, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { deleteDocuments, getJobStatus, listDocuments, uploadDocument } from "@/lib/api";
import { useIngestStore, type TrackedJob } from "@/stores/ingest";
import type { JobState } from "@/types/api";

const ACCEPTED = ".pdf,.docx,.pptx,.txt,.md,.csv,.xlsx";
const TERMINAL: JobState[] = ["completed", "failed"];

type BadgeState = JobState | "unreachable";

const STATE_BADGE: Record<BadgeState, "default" | "info" | "warning" | "success" | "destructive"> = {
  queued: "default",
  running: "info",
  retrying: "warning",
  completed: "success",
  failed: "destructive",
  unreachable: "destructive",
};

function JobRow({ job }: { job: TrackedJob }) {
  const queryClient = useQueryClient();
  const { data, isError } = useQuery({
    queryKey: ["job", job.jobId],
    queryFn: () => getJobStatus(job.jobId),
    // Poll every 2s while the ARQ worker runs. Stop on a terminal state AND
    // on persistent errors (e.g. an evicted job id 404s forever) — polling
    // must degrade, not hammer a dead endpoint indefinitely.
    refetchInterval: (query) => {
      if (query.state.status === "error") return false;
      const state = query.state.data?.status;
      return state && TERMINAL.includes(state) ? false : 2000;
    },
  });

  const status: BadgeState = isError ? "unreachable" : (data?.status ?? "queued");
  const settled = isError || TERMINAL.includes(status as JobState);

  useEffect(() => {
    // A finished ingest changes the corpus: refresh the document list.
    if (status === "completed") {
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
    }
  }, [status, queryClient]);

  return (
    <li
      data-testid="job-row"
      className="flex items-center justify-between gap-3 rounded-md border border-zinc-200 px-3 py-2 text-sm"
    >
      <span className="flex min-w-0 items-center gap-2">
        {!settled && <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-zinc-400" aria-hidden />}
        <span className="truncate">{job.fileName}</span>
      </span>
      <span className="flex shrink-0 items-center gap-2">
        {status === "completed" && data?.chunks_embedded !== undefined && (
          <span className="text-xs text-zinc-500">{data.chunks_embedded} chunks</span>
        )}
        {status === "failed" && data?.error && (
          <span className="max-w-64 truncate text-xs text-red-600" title={data.error}>
            {data.error}
          </span>
        )}
        <Badge data-testid="job-status" variant={STATE_BADGE[status]}>
          {status}
        </Badge>
      </span>
    </li>
  );
}

export function DocumentDashboard() {
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  // Store-backed (not component state): survives navigation mid-ingest, and
  // a mutation resolving after unmount updates the store race-free.
  const jobs = useIngestStore((s) => s.jobs);
  const addJob = useIngestStore((s) => s.addJob);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const documentsQuery = useQuery({ queryKey: ["documents"], queryFn: listDocuments });

  const uploadMutation = useMutation({
    mutationFn: uploadDocument,
    onSuccess: (accepted, file) => addJob({ jobId: accepted.job_id, fileName: file.name }),
  });

  const deleteMutation = useMutation({
    mutationFn: deleteDocuments,
    onSuccess: () => {
      setSelected(new Set());
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
    },
  });

  function onFilesChosen(files: FileList | null) {
    if (!files) return;
    for (const file of Array.from(files)) {
      uploadMutation.mutate(file);
    }
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  function toggleSelection(file: string) {
    setSelected((previous) => {
      const next = new Set(previous);
      if (next.has(file)) next.delete(file);
      else next.add(file);
      return next;
    });
  }

  function onDelete() {
    if (selected.size === 0) return;
    const names = Array.from(selected);
    if (!window.confirm(`Delete ${names.length} document(s) from storage AND the search index?`)) return;
    deleteMutation.mutate(names);
  }

  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle>Upload &amp; Ingest</CardTitle>
          <p className="text-xs text-zinc-500">
            Files land in MinIO, then the ingestion worker extracts, embeds and
            indexes them. Progress is polled live from the job tracker.
          </p>
        </CardHeader>
        <CardContent className="space-y-3">
          <input
            ref={fileInputRef}
            type="file"
            accept={ACCEPTED}
            multiple
            className="hidden"
            onChange={(e) => onFilesChosen(e.target.files)}
          />
          <Button onClick={() => fileInputRef.current?.click()} disabled={uploadMutation.isPending}>
            <FileUp className="h-4 w-4" aria-hidden />
            {uploadMutation.isPending ? "Uploading…" : "Choose files"}
          </Button>
          {uploadMutation.isError && (
            <p className="text-xs text-red-600">{(uploadMutation.error as Error).message}</p>
          )}
          {jobs.length > 0 && (
            <ul className="space-y-2">
              {jobs.map((job) => (
                <JobRow key={job.jobId} job={job} />
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>
            Knowledge Base{" "}
            {documentsQuery.data && (
              <span className="font-normal text-zinc-400">({documentsQuery.data.length})</span>
            )}
          </CardTitle>
          <p className="text-xs text-zinc-500">Documents currently synced in MinIO and searchable.</p>
        </CardHeader>
        <CardContent className="space-y-3">
          {documentsQuery.isLoading && <p className="text-sm text-zinc-400">Loading…</p>}
          {documentsQuery.isError && (
            <p className="text-sm text-red-600">{(documentsQuery.error as Error).message}</p>
          )}
          {documentsQuery.data?.length === 0 && (
            <p className="text-sm text-zinc-400">No documents yet — upload some.</p>
          )}
          {documentsQuery.data && documentsQuery.data.length > 0 && (
            <>
              <ul className="max-h-80 space-y-1 overflow-y-auto">
                {documentsQuery.data.map((file) => (
                  <li key={file}>
                    <label className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-zinc-50">
                      <input
                        type="checkbox"
                        checked={selected.has(file)}
                        onChange={() => toggleSelection(file)}
                        className="h-3.5 w-3.5 accent-zinc-900"
                      />
                      <span className="truncate">{file}</span>
                    </label>
                  </li>
                ))}
              </ul>
              <Button
                variant="destructive"
                size="sm"
                onClick={onDelete}
                disabled={selected.size === 0 || deleteMutation.isPending}
              >
                <Trash2 className="h-3.5 w-3.5" aria-hidden />
                Delete selected ({selected.size})
              </Button>
              {deleteMutation.isError && (
                <p className="text-xs text-red-600">{(deleteMutation.error as Error).message}</p>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
