// Fetch wrappers + global event stream helper. With VITE_MOCK=1 every call is served by src/mock instead of the backend.
// Sources:
// - https://developer.mozilla.org/en-US/docs/Web/API/EventSource
// - https://developer.mozilla.org/en-US/docs/Web/API/FormData (multipart upload; browser sets the boundary)
// - https://vite.dev/guide/env-and-mode (import.meta.env.VITE_*)
import { openStream } from "./stream";
import type { PipelineEvent } from "./types";
import { mockCrop, mockEventStream, mockIngest, mockRequest } from "../mock";

export const MOCK = import.meta.env.VITE_MOCK === "1";

async function send(method: string, path: string, body?: unknown): Promise<Response> {
  const res = await fetch(path, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${method} ${path}: ${res.status} ${await res.text()}`);
  return res;
}

export async function api<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  if (MOCK) return mockRequest(method, path, body) as T;
  return (await send(method, path, body)).json();
}

export async function apiText(path: string): Promise<string> {
  if (MOCK) return mockRequest("GET", path) as string;
  return (await send("GET", path)).text();
}

export async function ingest(files: File[]): Promise<{ run_id: string }> {
  if (MOCK) return mockIngest();
  const form = new FormData();
  files.forEach((f) => form.append("files", f));
  const res = await fetch("/api/ingest", { method: "POST", body: form });
  if (!res.ok) throw new Error(`POST /api/ingest: ${res.status} ${await res.text()}`);
  return res.json();
}

export const qs = (params: Record<string, string | number | undefined>) => {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
};

/** Image URL and the relative highlight rectangle ("x,y,w,h") of a PDF cell crop. Caller revokes nothing in mock mode. */
export async function fetchCrop(params: Record<string, string | number>): Promise<{ url: string; highlight: string | null }> {
  if (MOCK) return mockCrop();
  const res = await send("GET", `/api/evidence/crop${qs(params)}`);
  return { url: URL.createObjectURL(await res.blob()), highlight: res.headers.get("X-Highlight") };
}

/** Opens the app-wide SSE stream (every event of every run); reconnects with the last seq. Returns a closer. */
export function openEvents(onEvent: (e: PipelineEvent) => void): () => void {
  if (MOCK) return mockEventStream(onEvent);
  return openStream((since) => `/api/events?since=${since}`, onEvent);
}
