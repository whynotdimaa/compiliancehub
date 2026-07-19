import { useCallback, useEffect, useState } from "react";

import { api, ApiError } from "../api";
import { useAuth } from "../App";
import { formatWhen, MetricBar, Spinner } from "../components/ui";
import type { EvalRecord, EvalRunSummary } from "../types";

export function Evaluation() {
  const { user } = useAuth();
  const canRun = user?.role === "admin" || user?.role === "auditor";
  const [runs, setRuns] = useState<EvalRunSummary[] | null>(null);
  const [openRun, setOpenRun] = useState<string | null>(null);
  const [records, setRecords] = useState<Record<string, EvalRecord[]>>({});
  const [busy, setBusy] = useState(false);
  const [queued, setQueued] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setRuns(await api.evalRuns());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load runs");
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // freshly queued run appears once the worker writes its rows — poll briefly
  useEffect(() => {
    if (!queued) return;
    const timer = setInterval(refresh, 6000);
    const stop = setTimeout(() => setQueued(false), 10 * 60_000);
    return () => { clearInterval(timer); clearTimeout(stop); };
  }, [queued, refresh]);

  async function startRun() {
    setBusy(true);
    setError(null);
    try {
      await api.startEvalRun();
      setQueued(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to queue the run");
    } finally {
      setBusy(false);
    }
  }

  async function toggle(runId: string) {
    if (openRun === runId) {
      setOpenRun(null);
      return;
    }
    setOpenRun(runId);
    if (!records[runId]) {
      try {
        const details = await api.evalRunDetails(runId);
        setRecords((prev) => ({ ...prev, [runId]: details }));
      } catch {
        /* keep the card usable even if details fail */
      }
    }
  }

  const latest = runs?.[0];

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Evaluation</h1>
          <p className="desc">
            The golden dataset runs through the same pipeline users hit, and an LLM judge scores
            every answer. Metrics follow the RAGAS definitions; “—” means not computable, not zero.
          </p>
        </div>
        {canRun && (
          <button className="btn btn-accent" onClick={startRun} disabled={busy}>
            {busy ? <Spinner /> : "Run evaluation"}
          </button>
        )}
      </div>

      {queued && (
        <div className="card" style={{ padding: "12px 16px", marginBottom: 18, display: "flex", gap: 10, alignItems: "center" }}>
          <Spinner /> Run queued — scoring takes a couple of minutes; results appear below.
        </div>
      )}
      {error && <div className="error-note" style={{ marginBottom: 18 }}>{error}</div>}

      {latest && (
        <div className="hero-row">
          <Stat label="Faithfulness" value={latest.avg_faithfulness} />
          <Stat label="Answer relevancy" value={latest.avg_answer_relevancy} />
          <Stat label="Context precision" value={latest.avg_context_precision} />
          <Stat label="Context recall" value={latest.avg_context_recall} />
        </div>
      )}

      {runs && runs.length === 0 && !queued && (
        <div className="empty">
          <div className="big">No evaluation runs yet</div>
          Seed the demo documents, then run the golden dataset to get your first scores.
        </div>
      )}

      <div className="runs">
        {runs?.map((run) => (
          <div className="card run-card" key={run.run_id}>
            <div className="run-head">
              <div className="run-title">
                <span className="name">{run.dataset_name}</span>
                <span className="when">
                  {formatWhen(run.started_at)} · {run.items} questions
                </span>
              </div>
              <button className="run-open" onClick={() => toggle(run.run_id)}>
                {openRun === run.run_id ? "Hide questions" : "Per-question detail"}
              </button>
            </div>
            <div className="metrics">
              <MetricBar label="Faithfulness" value={run.avg_faithfulness} />
              <MetricBar label="Answer relevancy" value={run.avg_answer_relevancy} />
              <MetricBar label="Context precision" value={run.avg_context_precision} />
              <MetricBar label="Context recall" value={run.avg_context_recall} />
            </div>

            {openRun === run.run_id && (
              <div className="records">
                {!records[run.run_id] && <div className="thinking"><Spinner /> Loading…</div>}
                {records[run.run_id]?.map((record) => (
                  <div className="record" key={record.id}>
                    <div className="rq">{record.question}</div>
                    <div className="ra">{record.answer}</div>
                    <div className="rmetrics">
                      <Mini label="faith" value={record.faithfulness} />
                      <Mini label="relevancy" value={record.answer_relevancy} />
                      <Mini label="precision" value={record.context_precision} />
                      <Mini label="recall" value={record.context_recall} />
                      {record.low_confidence && <span className="rmetric" style={{ color: "var(--danger)" }}>low confidence</span>}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </>
  );
}

function Stat({ label, value }: { label: string; value: number | null }) {
  return (
    <div className="card stat-tile">
      <div className="microlabel">{label}</div>
      <div className="value">
        {value === null ? <small>n/a</small> : value.toFixed(2)}
        {value !== null && <small> / 1</small>}
      </div>
    </div>
  );
}

function Mini({ label, value }: { label: string; value: number | null }) {
  return (
    <span className="rmetric">
      {label} <b>{value === null ? "—" : value.toFixed(2)}</b>
    </span>
  );
}
