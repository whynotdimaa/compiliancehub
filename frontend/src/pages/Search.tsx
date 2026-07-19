import { useState } from "react";

import { api, ApiError } from "../api";
import { Spinner } from "../components/ui";
import type { SearchResult } from "../types";

export function SearchPage() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (query.trim().length < 2) return;
    setBusy(true);
    setError(null);
    try {
      const response = await api.search(query.trim(), 8);
      setResults(response.results);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Search failed");
    } finally {
      setBusy(false);
    }
  }

  // Cross-encoder scores are unbounded logits: the bar shows rank strength
  // relative to the best hit, the number shows the raw score.
  const maxScore = results?.length ? Math.max(...results.map((r) => r.score)) : 1;
  const minScore = results?.length ? Math.min(...results.map((r) => r.score)) : 0;
  const span = maxScore - minScore || 1;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Search</h1>
          <p className="desc">
            Hybrid retrieval under the hood: vector similarity, full-text match and the knowledge
            graph — fused by reciprocal rank, reranked by a cross-encoder.
          </p>
        </div>
      </div>

      <form style={{ display: "flex", gap: 10 }} onSubmit={submit}>
        <input
          className="input"
          placeholder="retention period, ISO 27001, Article 30…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <button className="btn btn-primary" disabled={busy || query.trim().length < 2}>
          {busy ? <Spinner /> : "Search"}
        </button>
      </form>

      {error && <div className="error-note" style={{ marginTop: 16 }}>{error}</div>}

      {results && results.length === 0 && (
        <div className="empty">
          <div className="big">Nothing found</div>
          Try different terms, or check that documents finished ingesting.
        </div>
      )}

      <div style={{ marginTop: 20 }}>
        {results?.map((result) => (
          <div className="card result" key={result.chunk_id}>
            <div className="top">
              <div>
                <div className="breadcrumb">{result.heading_path || result.document_title}</div>
                <div className="doc">
                  {result.document_title} · {result.filename}
                  {result.page ? ` · p. ${result.page}` : ""}
                </div>
              </div>
              <div className="score">
                <span className="track">
                  <span
                    className="fill"
                    style={{ width: `${Math.round(((result.score - minScore) / span) * 100)}%` }}
                  />
                </span>
                <span className="val">{result.score.toFixed(2)}</span>
              </div>
            </div>
            <div className="text">{result.text.length > 420 ? result.text.slice(0, 420) + "…" : result.text}</div>
          </div>
        ))}
      </div>
    </>
  );
}
