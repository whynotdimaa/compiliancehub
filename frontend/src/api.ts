import type {
  AskResponse,
  DocumentOut,
  EvalRecord,
  EvalRunSummary,
  SearchResult,
  TokenPair,
  UserOut,
} from "./types";

const BASE = "/api/v1";
const TOKEN_KEY = "ch_token";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

export const tokenStore = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (token: string) => localStorage.setItem(TOKEN_KEY, token),
  clear: () => localStorage.removeItem(TOKEN_KEY),
};

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { ...(init.headers as Record<string, string>) };
  if (!(init.body instanceof FormData) && init.body !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  const token = tokenStore.get();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const response = await fetch(BASE + path, { ...init, headers });

  if (response.status === 401 && !path.startsWith("/auth/")) {
    tokenStore.clear();
    window.dispatchEvent(new Event("ch-unauthorized"));
  }
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(response.status, detail);
  }
  if (response.status === 204) return undefined as T;
  return response.json();
}

export const api = {
  register: (payload: {
    tenant_name: string;
    tenant_slug: string;
    admin_email: string;
    admin_password: string;
    admin_full_name: string;
  }) => request<{ id: string; slug: string }>("/auth/register", { method: "POST", body: JSON.stringify(payload) }),

  login: (payload: { tenant_slug: string; email: string; password: string }) =>
    request<TokenPair>("/auth/login", { method: "POST", body: JSON.stringify(payload) }),

  me: () => request<UserOut>("/auth/me"),

  listDocuments: () => request<DocumentOut[]>("/documents"),

  uploadDocument: (file: File, docType: string) => {
    const form = new FormData();
    form.append("file", file);
    form.append("doc_type", docType);
    return request<DocumentOut>("/documents", { method: "POST", body: form });
  },

  importUrl: (url: string, docType: string) =>
    request<DocumentOut>("/documents/import", {
      method: "POST",
      body: JSON.stringify({ url, doc_type: docType }),
    }),

  documentStatus: (id: string) =>
    request<{ id: string; status: string; chunk_count: number; error: string | null }>(
      `/documents/${id}/status`,
    ),

  deleteDocument: (id: string) => request<void>(`/documents/${id}`, { method: "DELETE" }),

  search: (query: string, topK: number) =>
    request<{ query: string; results: SearchResult[] }>("/search", {
      method: "POST",
      body: JSON.stringify({ query, top_k: topK }),
    }),

  ask: (question: string) =>
    request<AskResponse>("/ask", { method: "POST", body: JSON.stringify({ question }) }),

  evalRuns: () => request<EvalRunSummary[]>("/evaluation/runs"),

  startEvalRun: () =>
    request<{ run_id: string; items: number }>("/evaluation/runs", {
      method: "POST",
      body: JSON.stringify({}),
    }),

  evalRunDetails: (runId: string) => request<EvalRecord[]>(`/evaluation/runs/${runId}`),
};
