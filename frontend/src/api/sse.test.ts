import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { API } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { ForbiddenError, NetworkError, NotFoundError } from "./errors";
import { SseParser, readSse, type SseMessage } from "./sse";

describe("SseParser", () => {
  it("parses id, event and JSON data", () => {
    const out = new SseParser().push('id: 7\nevent: step_started\ndata: {"name":"discovery_agent"}\n\n');
    expect(out).toEqual([{ id: 7, event: "step_started", data: { name: "discovery_agent" } }]);
  });

  it("handles events split across chunks, even mid-line", () => {
    const p = new SseParser();
    expect(p.push("id: 1\nevent: run_sta")).toEqual([]);
    expect(p.push('rted\ndata: {"a"')).toEqual([]);
    expect(p.push(":1}\n\nid: 2\nevent: x\ndata: y\n\n")).toEqual([
      { id: 1, event: "run_started", data: { a: 1 } },
      { id: 2, event: "x", data: "y" },
    ]);
  });

  it("accepts CRLF line endings", () => {
    expect(new SseParser().push("id: 3\r\nevent: e\r\ndata: 1\r\n\r\n")).toEqual([{ id: 3, event: "e", data: 1 }]);
  });

  it("ignores keep-alive comments and comment-only blocks", () => {
    const p = new SseParser();
    expect(p.push(": keepalive\n\n")).toEqual([]);
    expect(p.push(': hi\nid: 4\nevent: e\ndata: {"k":true}\n\n')).toEqual([{ id: 4, event: "e", data: { k: true } }]);
  });

  it("joins multi-line data and defaults the event name", () => {
    expect(new SseParser().push("data: line1\ndata: line2\n\n")).toEqual([{ id: null, event: "message", data: "line1\nline2" }]);
  });

  it("delivers non-JSON data as text and tolerates a bad id", () => {
    expect(new SseParser().push("id: abc\nevent: e\ndata: plain text\n\n")).toEqual([{ id: null, event: "e", data: "plain text" }]);
  });

  it("keeps an incomplete trailing event until it is finished", () => {
    const p = new SseParser();
    expect(p.push("id: 1\nevent: e\ndata: 1\n\nid: 2\nevent: e\ndata: 2")).toHaveLength(1);
    expect(p.push("\n\n")).toEqual([{ id: 2, event: "e", data: 2 }]);
  });
});

function streamBody(chunks: string[], delayMs = 0): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  return new ReadableStream({
    async start(controller) {
      for (const c of chunks) {
        if (delayMs) await new Promise((r) => setTimeout(r, delayMs));
        controller.enqueue(enc.encode(c));
      }
      controller.close();
    },
  });
}

describe("readSse", () => {
  const url = `${API}/engagements/wf_1/events`;

  it("streams messages in order and resolves when the server closes", async () => {
    server.use(
      http.get(url, () =>
        new HttpResponse(streamBody(["id: 1\nevent: run_started\ndata: {}\n\nid: 2\nev", 'ent: step_started\ndata: {"name":"x"}\n\n']), {
          headers: { "Content-Type": "text/event-stream" },
        }),
      ),
    );
    const got: SseMessage[] = [];
    await readSse(url, { onMessage: (m) => got.push(m) });
    expect(got.map((m) => [m.id, m.event])).toEqual([[1, "run_started"], [2, "step_started"]]);
  });

  it("sends the caller's headers (this is why we do not use EventSource)", async () => {
    let seen: Headers | undefined;
    server.use(
      http.get(url, ({ request }) => {
        seen = request.headers;
        return new HttpResponse(streamBody([]), { headers: { "Content-Type": "text/event-stream" } });
      }),
    );
    await readSse(url, { headers: { "X-Dev-User": "pat", "X-Dev-Roles": "Partner" }, onMessage: () => {} });
    expect(seen?.get("x-dev-user")).toBe("pat");
    expect(seen?.get("accept")).toBe("text/event-stream");
  });

  it("turns HTTP failures into typed errors, not network errors", async () => {
    server.use(http.get(url, () => HttpResponse.json({ detail: "engagement not found" }, { status: 404 })));
    await expect(readSse(url, { onMessage: () => {} })).rejects.toBeInstanceOf(NotFoundError);
    server.use(http.get(url, () => HttpResponse.json({ detail: "no" }, { status: 403 })));
    await expect(readSse(url, { onMessage: () => {} })).rejects.toBeInstanceOf(ForbiddenError);
  });

  it("raises NetworkError when the connection fails", async () => {
    server.use(http.get(url, () => HttpResponse.error()));
    await expect(readSse(url, { onMessage: () => {} })).rejects.toBeInstanceOf(NetworkError);
  });

  it("stops quietly when aborted", async () => {
    server.use(
      http.get(url, () => new HttpResponse(streamBody(["id: 1\nevent: a\ndata: 1\n\n", "id: 2\nevent: b\ndata: 2\n\n"], 50), {
        headers: { "Content-Type": "text/event-stream" },
      })),
    );
    const ctl = new AbortController();
    const got: SseMessage[] = [];
    await readSse(url, {
      signal: ctl.signal,
      onMessage: (m) => {
        got.push(m);
        ctl.abort();
      },
    });
    expect(got.length).toBeGreaterThanOrEqual(1);
  });
});
