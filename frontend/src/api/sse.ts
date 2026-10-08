import { ApiError, NetworkError, apiErrorFrom } from "./errors";

/**
 * Server-Sent Events over fetch. The browser's EventSource cannot send custom headers, and this app
 * authenticates with headers (X-Dev-User in development, a bearer token with Entra), so we read the
 * stream ourselves.
 */

export interface SseMessage {
  id: number | null;
  event: string;
  data: unknown;
}

/** Incremental parser: feed it text chunks as they arrive, even split mid-line or mid-event. */
export class SseParser {
  private buffer = "";

  push(chunk: string): SseMessage[] {
    this.buffer += chunk.replace(/\r\n?/g, "\n");
    const messages: SseMessage[] = [];
    let end: number;
    while ((end = this.buffer.indexOf("\n\n")) !== -1) {
      const block = this.buffer.slice(0, end);
      this.buffer = this.buffer.slice(end + 2);
      const msg = parseBlock(block);
      if (msg) messages.push(msg);
    }
    return messages;
  }
}

function parseBlock(block: string): SseMessage | null {
  let event = "message";
  let id: number | null = null;
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line === "" || line.startsWith(":")) continue; // comment / keep-alive
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") event = value;
    else if (field === "id") {
      const n = Number(value);
      id = Number.isInteger(n) ? n : null;
    } else if (field === "data") data.push(value);
  }
  if (data.length === 0) return null; // nothing to deliver (for example a bare keep-alive)
  const raw = data.join("\n");
  let parsed: unknown = raw;
  try {
    parsed = JSON.parse(raw);
  } catch {
    /* not JSON: deliver the text */
  }
  return { id, event, data: parsed };
}

export interface ReadSseOptions {
  headers?: Record<string, string>;
  signal?: AbortSignal;
  onMessage: (message: SseMessage) => void;
  fetch?: typeof fetch;
}

/**
 * Read a stream until the server closes it. Resolves on a clean close, throws a typed error on an
 * HTTP failure (so a 404 or 401 is not mistaken for a dropped connection) or NetworkError otherwise.
 * An abort via `signal` resolves quietly.
 */
export async function readSse(url: string, { headers, signal, onMessage, fetch: fetchImpl }: ReadSseOptions): Promise<void> {
  const doFetch = fetchImpl ?? ((input: string, init?: RequestInit) => globalThis.fetch(input, init));
  let response: Response;
  try {
    response = await doFetch(url, {
      headers: { Accept: "text/event-stream", ...headers },
      ...(signal ? { signal } : {}),
    });
  } catch (e) {
    if (signal?.aborted) return;
    throw new NetworkError(e instanceof Error ? e.message : undefined);
  }
  if (!response.ok) {
    const body = await response.json().catch(() => undefined);
    throw apiErrorFrom(response.status, body);
  }
  if (!response.body) throw new NetworkError("The server sent no stream");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const parser = new SseParser();
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      for (const message of parser.push(decoder.decode(value, { stream: true }))) onMessage(message);
    }
  } catch (e) {
    if (signal?.aborted) return;
    if (e instanceof ApiError) throw e;
    throw new NetworkError(e instanceof Error ? e.message : "The stream was interrupted");
  }
}
