import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { useApi } from "@/api/ApiProvider";
import { liveConfig } from "@/api/liveConfig";
import { ForbiddenError, NotFoundError, UnauthorizedError } from "@/api/errors";
import { readSse, type SseMessage } from "@/api/sse";
import { isTerminalEvent, type EngagementEvent } from "@/api/types";

/**
 * connecting: opening the stream · live: events are arriving · closed: the server ended the stream
 * (the run paused or finished) · polling: the stream kept failing, so the page polls instead.
 */
export type Connection = "connecting" | "live" | "closed" | "polling";


function toEvent(m: SseMessage): EngagementEvent {
  const data = typeof m.data === "object" && m.data !== null ? (m.data as Record<string, unknown>) : {};
  return { ...(data as object), id: m.id ?? 0, type: m.event } as EngagementEvent;
}

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const t = setTimeout(resolve, ms);
    signal.addEventListener("abort", () => { clearTimeout(t); resolve(); }, { once: true });
  });
}

/**
 * Follow one engagement's run over Server-Sent Events. Reconnects with the last event id after a
 * dropped connection (so nothing is missed or repeated), refreshes the engagement's data as steps
 * finish, and gives up after a few tries so the caller can fall back to polling.
 */
export function useEngagementLive(id: string, options: { retryDelaysMs?: number[] } = {}) {
  const api = useApi();
  const qc = useQueryClient();
  const [events, setEvents] = useState<EngagementEvent[]>([]);
  const [connection, setConnection] = useState<Connection>("connecting");
  const [error, setError] = useState<unknown>(null);
  const [generation, setGeneration] = useState(0);
  const delays = options.retryDelaysMs ?? liveConfig.retryDelaysMs;
  const delaysRef = useRef(delays);
  delaysRef.current = delays;
  const configRef = useRef(api.config);
  configRef.current = api.config;

  useEffect(() => {
    const ctl = new AbortController();
    const { signal } = ctl;
    let lastId = 0;
    let failures = 0;
    setEvents([]);
    setConnection("connecting");
    setError(null);

    const refresh = () => void qc.invalidateQueries({ queryKey: ["engagement", id] });

    async function run() {
      while (!signal.aborted) {
        try {
          const { baseUrl, getHeaders } = configRef.current;
          await readSse(`${baseUrl}/engagements/${encodeURIComponent(id)}/events?after=${lastId}`, {
            headers: getHeaders(),
            signal,
            onMessage: (m) => {
              if (m.id !== null) lastId = Math.max(lastId, m.id);
              const e = toEvent(m);
              failures = 0;
              setConnection("live");
              setEvents((prev) => (prev.some((p) => p.id === e.id && e.id !== 0) ? prev : [...prev, e]));
              if (e.type === "step_finished" || e.type === "run_started" || isTerminalEvent(e.type)) refresh();
            },
          });
          if (signal.aborted) return;
          // A clean close means the run paused or ended (or was already settled when we connected).
          setConnection("closed");
          refresh();
          return;
        } catch (e) {
          if (signal.aborted) return;
          if (e instanceof NotFoundError || e instanceof UnauthorizedError || e instanceof ForbiddenError) {
            setError(e); // retrying will not help; the page shows the typed error
            setConnection("closed");
            return;
          }
          failures += 1;
          if (failures > delaysRef.current.length) {
            setConnection("polling");
            return;
          }
          setConnection("connecting");
          await sleep(delaysRef.current[failures - 1] ?? 1000, signal);
        }
      }
    }
    void run();
    return () => ctl.abort();
  }, [id, generation, qc]);

  /** Re-open the stream from the start; used after a decision so the next events arrive. */
  const reconnect = useCallback(() => setGeneration((g) => g + 1), []);
  return { events, connection, error, reconnect };
}
