/** Client-side chat state (Zustand). Server truth stays on the backend —
 * this store only mirrors what the current browser session displays. */
import { create } from "zustand";

import type { Citation } from "@/types/api";

function randomId(): string {
  // crypto.randomUUID requires a secure context — plain http:// over a LAN
  // hostname/IP is not one, and it crashed the whole page there (caught by
  // the E2E suite running against the container hostname).
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `id-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

export type MessageStatus = "streaming" | "done" | "error";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: Citation[];
  standaloneQuestion?: string;
  status: MessageStatus;
  error?: string;
}

interface ChatState {
  /** Sent with every query: enables backend conversation memory. */
  sessionId: string;
  messages: ChatMessage[];
  isStreaming: boolean;
  docFilter: string[];
  setDocFilter: (docs: string[]) => void;
  addUserMessage: (content: string) => void;
  startAssistantMessage: () => string;
  appendToken: (id: string, text: string) => void;
  setCitations: (id: string, citations: Citation[], standaloneQuestion: string) => void;
  finishMessage: (id: string) => void;
  failMessage: (id: string, error: string) => void;
  reset: () => void;
}

export const useChatStore = create<ChatState>((set) => ({
  sessionId: randomId(),
  messages: [],
  isStreaming: false,
  docFilter: [],
  setDocFilter: (docs) => set({ docFilter: docs }),
  addUserMessage: (content) =>
    set((state) => ({
      messages: [
        ...state.messages,
        { id: randomId(), role: "user", content, citations: [], status: "done" },
      ],
    })),
  startAssistantMessage: () => {
    const id = randomId();
    set((state) => ({
      isStreaming: true,
      messages: [
        ...state.messages,
        { id, role: "assistant", content: "", citations: [], status: "streaming" },
      ],
    }));
    return id;
  },
  appendToken: (id, text) =>
    set((state) => ({
      messages: state.messages.map((m) =>
        m.id === id ? { ...m, content: m.content + text } : m
      ),
    })),
  setCitations: (id, citations, standaloneQuestion) =>
    set((state) => ({
      messages: state.messages.map((m) =>
        m.id === id ? { ...m, citations, standaloneQuestion } : m
      ),
    })),
  finishMessage: (id) =>
    set((state) => ({
      isStreaming: false,
      messages: state.messages.map((m) =>
        m.id === id ? { ...m, status: "done" as const } : m
      ),
    })),
  failMessage: (id, error) =>
    set((state) => ({
      isStreaming: false,
      messages: state.messages.map((m) =>
        m.id === id ? { ...m, status: "error" as const, error } : m
      ),
    })),
  reset: () => set({ messages: [], sessionId: randomId(), isStreaming: false }),
}));
