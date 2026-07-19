import { Fragment, useState } from "react";

import { api, ApiError } from "../api";
import { Spinner } from "../components/ui";
import type { AskResponse } from "../types";

interface Turn {
  question: string;
  response?: AskResponse;
  error?: string;
}

/** Render [n] markers in the answer as citation chips. */
function AnswerText({ text }: { text: string }) {
  const parts = text.split(/(\[\d+\])/g);
  return (
    <p className="turn-a">
      {parts.map((part, i) => {
        const match = part.match(/^\[(\d+)\]$/);
        return match ? (
          <span key={i} className="cite-chip">{match[1]}</span>
        ) : (
          <Fragment key={i}>{part}</Fragment>
        );
      })}
    </p>
  );
}

export function Ask() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit() {
    const q = question.trim();
    if (q.length < 5 || busy) return;
    setQuestion("");
    setBusy(true);
    setTurns((prev) => [...prev, { question: q }]);
    try {
      const response = await api.ask(q);
      setTurns((prev) => prev.map((t, i) => (i === prev.length - 1 ? { ...t, response } : t)));
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Request failed";
      setTurns((prev) => prev.map((t, i) => (i === prev.length - 1 ? { ...t, error: message } : t)));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="ask-column">
      <div className="page-head">
        <div>
          <h1>Ask</h1>
          <p className="desc">
            Answers are drafted only from your documents, graded for relevance first, and cite the
            exact section they come from.
          </p>
        </div>
      </div>

      {turns.length === 0 && (
        <div className="empty">
          <div className="big">Ask your first question</div>
          Try “How long is personal data retained?” after seeding the demo documents.
        </div>
      )}

      {turns.map((turn, i) => (
        <article className="turn" key={i}>
          <div className="turn-q">{turn.question}</div>

          {!turn.response && !turn.error && (
            <div className="thinking"><Spinner /> Retrieving, grading, writing…</div>
          )}
          {turn.error && <div className="error-note">{turn.error}</div>}

          {turn.response && (
            <>
              <AnswerText text={turn.response.answer} />
              <div className="turn-meta">
                {turn.response.rewritten_query && (
                  <span className="meta-tag">query rewritten → “{turn.response.rewritten_query}”</span>
                )}
                {turn.response.used_web_search && <span className="meta-tag">web fallback used</span>}
                {turn.response.low_confidence && (
                  <span className="meta-tag warn">low confidence — nothing relevant found</span>
                )}
              </div>
              {turn.response.citations.length > 0 && (
                <div className="citations">
                  {turn.response.citations.map((c) => (
                    <div className="card citation" key={c.index}>
                      <div className="src">
                        <span className="idx">[{c.index}]</span>
                        <span className="where">
                          {c.source_type === "document" ? c.document_title : (c.title || c.url)}
                        </span>
                      </div>
                      <span className="loc">
                        {c.source_type === "document"
                          ? [c.heading_path, c.page ? `p. ${c.page}` : null].filter(Boolean).join(" · ")
                          : c.url}
                      </span>
                      <span className="snippet">{c.snippet}</span>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </article>
      ))}

      <div className="ask-bar">
        <textarea
          className="textarea"
          rows={1}
          placeholder="Ask about your policies…"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
        />
        <button className="btn btn-accent" onClick={submit} disabled={busy || question.trim().length < 5}>
          {busy ? <Spinner /> : "Ask"}
        </button>
      </div>
    </div>
  );
}
