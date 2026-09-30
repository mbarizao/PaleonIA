export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

let onUnauthorized = () => {};

export function setUnauthorizedHandler(handler: () => void) {
  onUnauthorized = handler;
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(path, { ...options, headers, credentials: "same-origin" });
  if (response.status === 401 && path !== "/api/login" && path !== "/api/auth") onUnauthorized();
  if (!response.ok) {
    let detail = await response.text();
    try {
      const parsed = JSON.parse(detail) as { detail?: unknown };
      if (typeof parsed.detail === "string") detail = parsed.detail;
      else if (Array.isArray(parsed.detail)) {
        detail = parsed.detail.map((item) => (item as { msg?: string }).msg || String(item)).join(" ");
      }
    } catch {
      /* texto puro */
    }
    throw new ApiError(response.status, detail || response.statusText);
  }
  const type = response.headers.get("content-type") || "";
  if (type.includes("application/json")) return response.json() as Promise<T>;
  return undefined as T;
}

export async function streamImport(body: FormData, onEvent: (event: ImportEvent) => Promise<void>) {
  const response = await fetch("/api/pages/stream", { method: "POST", body, credentials: "same-origin" });
  if (response.status === 401) onUnauthorized();
  if (!response.ok || !response.body) throw new Error(await response.text() || "Falha na importação");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result: { pages: import("./types").Page[]; errors: string[] } | null = null;
  async function consume(line: string) {
    if (!line.trim()) return;
    const event = JSON.parse(line) as ImportEvent;
    await onEvent(event);
    if (event.stage === "complete") result = { pages: event.pages || [], errors: event.errors || [] };
  }
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      let end: number;
      while ((end = buffer.indexOf("\n")) >= 0) {
        await consume(buffer.slice(0, end));
        buffer = buffer.slice(end + 1);
      }
      if (done) break;
    }
    await consume(buffer);
  } finally {
    await reader.cancel();
    reader.releaseLock();
  }
  if (!result) throw new Error("A conexão foi interrompida antes de concluir a importação.");
  return result as { pages: import("./types").Page[]; errors: string[] };
}

export type ImportEvent = {
  stage: string;
  filename?: string;
  image?: string;
  width: number;
  height: number;
  x: number;
  y: number;
  scale: number;
  done: number;
  total: number;
  pages?: import("./types").Page[];
  errors?: string[];
};
