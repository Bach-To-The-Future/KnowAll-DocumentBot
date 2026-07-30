"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ChevronDown, RotateCcw, SendHorizonal } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { listDocuments } from "@/lib/api";
import { streamQuery } from "@/lib/stream";
import { cn } from "@/lib/utils";
import { useChatStore, type ChatMessage } from "@/stores/chat";
import { NO_ANSWER_MESSAGE, type Citation } from "@/types/api";

function CitationBlock({ citations }: { citations: Citation[] }) {
  // Native <details>: accessible expand/collapse without extra state.
  return (
    <details data-testid="citation-block" className="group mt-2 rounded-md border border-zinc-200 bg-zinc-50">
      <summary className="flex cursor-pointer select-none items-center gap-1.5 px-3 py-2 text-xs font-medium text-zinc-600">
        <ChevronDown className="h-3.5 w-3.5 transition-transform group-open:rotate-180" aria-hidden />
        {citations.length} source{citations.length === 1 ? "" : "s"}
      </summary>
      <ul className="space-y-2 border-t border-zinc-200 p-3">
        {citations.map((citation) => (
          <li key={citation.index} className="text-xs">
            <div className="mb-1 flex items-center gap-2">
              <Badge variant="info">[{citation.index}]</Badge>
              <span className="font-medium">{citation.source}</span>
              <span className="text-zinc-400">
                p.{citation.page_number} · relevance {citation.score.toFixed(2)}
              </span>
            </div>
            <p className="line-clamp-3 whitespace-pre-wrap text-zinc-600">{citation.text}</p>
          </li>
        ))}
      </ul>
    </details>
  );
}

function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  const abstained = message.status === "done" && message.content.trim() === NO_ANSWER_MESSAGE;

  return (
    <div className={cn("flex", isUser ? "justify-end" : "justify-start")}>
      <div
        data-testid={`message-${message.role}`}
        className={cn(
          "max-w-[85%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed",
          isUser ? "bg-zinc-900 text-zinc-50" : "border border-zinc-200 bg-white shadow-sm"
        )}
      >
        {message.error ? (
          <p className="flex items-center gap-2 text-red-600">
            <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden />
            {message.error}
          </p>
        ) : abstained ? (
          <p className="flex items-center gap-2 text-amber-700">
            <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden />
            {message.content}
          </p>
        ) : (
          <p className="whitespace-pre-wrap">
            {message.content}
            {message.status === "streaming" && (
              <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse bg-zinc-400 align-text-bottom" />
            )}
          </p>
        )}
        {message.standaloneQuestion && message.standaloneQuestion !== message.content && (
          <p className="mt-1.5 text-xs text-zinc-400">
            searched as: “{message.standaloneQuestion}”
          </p>
        )}
        {!isUser && !abstained && message.citations.length > 0 && (
          <CitationBlock citations={message.citations} />
        )}
      </div>
    </div>
  );
}

function SourceFilter() {
  const { data: files } = useQuery({ queryKey: ["documents"], queryFn: listDocuments });
  const docFilter = useChatStore((s) => s.docFilter);
  const setDocFilter = useChatStore((s) => s.setDocFilter);

  if (!files?.length) return null;

  const toggle = (file: string) =>
    setDocFilter(
      docFilter.includes(file) ? docFilter.filter((f) => f !== file) : [...docFilter, file]
    );

  return (
    <details className="rounded-md border border-zinc-200 bg-white">
      <summary className="cursor-pointer select-none px-3 py-2 text-xs font-medium text-zinc-600">
        Filter sources{docFilter.length > 0 ? ` (${docFilter.length} selected)` : " (all)"}
      </summary>
      <div className="max-h-40 space-y-1 overflow-y-auto border-t border-zinc-200 p-3">
        {files.map((file) => (
          <label key={file} className="flex items-center gap-2 text-xs text-zinc-700">
            <input
              type="checkbox"
              checked={docFilter.includes(file)}
              onChange={() => toggle(file)}
              className="h-3.5 w-3.5 accent-zinc-900"
            />
            {file}
          </label>
        ))}
      </div>
    </details>
  );
}

export function ChatView() {
  const [question, setQuestion] = useState("");
  const store = useChatStore();
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [store.messages]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const trimmed = question.trim();
    if (!trimmed || store.isStreaming) return;

    setQuestion("");
    store.addUserMessage(trimmed);
    const assistantId = store.startAssistantMessage();

    try {
      await streamQuery(
        {
          question: trimmed,
          session_id: store.sessionId,
          documents: store.docFilter.length > 0 ? store.docFilter : null,
        },
        {
          onCitations: (citations, standalone) =>
            store.setCitations(assistantId, citations, standalone),
          onToken: (text) => store.appendToken(assistantId, text),
          onError: (detail) => store.failMessage(assistantId, detail),
          onDone: () => store.finishMessage(assistantId),
        }
      );
      // Defensive: if the stream ended without a done event, settle the UI.
      if (useChatStore.getState().isStreaming) store.finishMessage(assistantId);
    } catch (error) {
      store.failMessage(assistantId, error instanceof Error ? error.message : "Stream failed.");
    }
  }

  return (
    <div className="flex h-[calc(100vh-8.5rem)] flex-col gap-3">
      <SourceFilter />

      <div className="flex-1 space-y-4 overflow-y-auto rounded-lg border border-zinc-200 bg-zinc-50/60 p-4">
        {store.messages.length === 0 && (
          <p className="pt-16 text-center text-sm text-zinc-400">
            Ask a question about your documents. Answers cite their sources.
          </p>
        )}
        {store.messages.map((message) => (
          <MessageBubble key={message.id} message={message} />
        ))}
        <div ref={bottomRef} />
      </div>

      <form onSubmit={onSubmit} className="flex items-center gap-2">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => store.reset()}
          title="New conversation"
        >
          <RotateCcw className="h-4 w-4" aria-hidden />
        </Button>
        <Input
          data-testid="chat-input"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Ask about your documents…"
          disabled={store.isStreaming}
          autoFocus
        />
        <Button type="submit" disabled={store.isStreaming || !question.trim()}>
          <SendHorizonal className="h-4 w-4" aria-hidden />
          Send
        </Button>
      </form>
    </div>
  );
}
