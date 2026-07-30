/** Tracked ingestion jobs live in a store, not component state: navigating
 * away mid-ingest must not orphan the tracking UI, and a mutation resolving
 * after the dashboard unmounts updates the store safely. */
import { create } from "zustand";

export interface TrackedJob {
  jobId: string;
  fileName: string;
}

interface IngestState {
  jobs: TrackedJob[];
  addJob: (job: TrackedJob) => void;
}

export const useIngestStore = create<IngestState>((set) => ({
  jobs: [],
  addJob: (job) => set((state) => ({ jobs: [job, ...state.jobs] })),
}));
