export type DocumentStatus = "pending" | "processing" | "ready" | "failed";
export type DocumentType = "policy" | "contract" | "regulation" | "report" | "other";

export interface DocumentOut {
  id: string;
  title: string;
  filename: string;
  content_type: string;
  doc_type: DocumentType;
  status: DocumentStatus;
  size_bytes: number;
  chunk_count: number;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface UserOut {
  id: string;
  tenant_id: string;
  email: string;
  full_name: string;
  role: "admin" | "auditor" | "viewer";
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface SearchResult {
  chunk_id: string;
  document_id: string;
  document_title: string;
  filename: string;
  doc_type: DocumentType;
  heading_path: string;
  page: number | null;
  text: string;
  score: number;
}

export interface Citation {
  index: number;
  source_type: "document" | "web";
  snippet: string;
  chunk_id: string | null;
  document_id: string | null;
  document_title: string | null;
  heading_path: string | null;
  page: number | null;
  url: string | null;
  title: string | null;
}

export interface AskResponse {
  question: string;
  answer: string;
  citations: Citation[];
  rewritten_query: string | null;
  used_web_search: boolean;
  low_confidence: boolean;
}

export interface EvalRunSummary {
  run_id: string;
  dataset_name: string;
  started_at: string;
  items: number;
  avg_faithfulness: number | null;
  avg_answer_relevancy: number | null;
  avg_context_precision: number | null;
  avg_context_recall: number | null;
}

export interface EvalRecord {
  id: string;
  question: string;
  ground_truth: string | null;
  answer: string;
  contexts: string[] | null;
  faithfulness: number | null;
  answer_relevancy: number | null;
  context_precision: number | null;
  context_recall: number | null;
  low_confidence: boolean;
  created_at: string;
}
