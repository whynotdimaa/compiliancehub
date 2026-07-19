import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError } from "../api";
import { useAuth } from "../App";
import { formatBytes, formatWhen, Spinner, StatusBadge } from "../components/ui";
import type { DocumentOut } from "../types";

const DOC_TYPES = ["policy", "contract", "regulation", "report", "other"] as const;

export function Documents() {
  const { user } = useAuth();
  const canUpload = user?.role === "admin" || user?.role === "auditor";
  const [documents, setDocuments] = useState<DocumentOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [docType, setDocType] = useState<string>("policy");
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [importUrl, setImportUrl] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    try {
      setDocuments(await api.listDocuments());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load documents");
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const hasInFlight = documents?.some((d) => d.status === "pending" || d.status === "processing");
  useEffect(() => {
    if (!hasInFlight) return;
    const timer = setInterval(refresh, 4000);
    return () => clearInterval(timer);
  }, [hasInFlight, refresh]);

  async function handleFiles(files: FileList | null) {
    if (!files?.length) return;
    setBusy(true);
    setError(null);
    try {
      for (const file of Array.from(files)) {
        await api.uploadDocument(file, docType);
      }
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Upload failed");
    } finally {
      setBusy(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  async function handleImport(event: React.FormEvent) {
    event.preventDefault();
    if (!importUrl) return;
    setBusy(true);
    setError(null);
    try {
      await api.importUrl(importUrl, docType);
      setImportUrl("");
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Import failed");
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete(id: string) {
    setError(null);
    try {
      await api.deleteDocument(id);
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Delete failed");
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Documents</h1>
          <p className="desc">
            Everything uploaded here is parsed, chunked along its headings, embedded and indexed —
            ready for search and cited answers.
          </p>
        </div>
      </div>

      {canUpload && (
        <>
          <div
            className={dragging ? "dropzone dragging" : "dropzone"}
            onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => { e.preventDefault(); setDragging(false); handleFiles(e.dataTransfer.files); }}
          >
            <div>
              <b>Drop files here</b> or{" "}
              <button className="btn btn-ghost" type="button" onClick={() => fileInput.current?.click()} disabled={busy}>
                {busy ? <Spinner /> : "browse"}
              </button>
            </div>
            <span className="hint">PDF · DOCX · Markdown · TXT — up to 50 MB</span>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <span className="microlabel">Type</span>
              <select className="select" style={{ width: "auto" }} value={docType} onChange={(e) => setDocType(e.target.value)}>
                {DOC_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
            <input ref={fileInput} type="file" hidden multiple accept=".pdf,.docx,.md,.txt" onChange={(e) => handleFiles(e.target.files)} />
          </div>

          <form className="import-row" onSubmit={handleImport}>
            <input
              className="input"
              placeholder="…or paste a URL / Google Drive share link"
              value={importUrl}
              onChange={(e) => setImportUrl(e.target.value)}
              type="url"
            />
            <button className="btn btn-ghost" disabled={busy || !importUrl}>Import</button>
          </form>
        </>
      )}

      {error && <div className="error-note" style={{ marginTop: 16 }}>{error}</div>}

      {documents && documents.length === 0 && (
        <div className="empty">
          <div className="big">No documents yet</div>
          Upload your first policy — ingestion runs in the background.
        </div>
      )}

      {documents && documents.length > 0 && (
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Document</th>
                <th>Type</th>
                <th>Status</th>
                <th className="num">Chunks</th>
                <th className="num">Size</th>
                <th>Added</th>
                {user?.role === "admin" && <th />}
              </tr>
            </thead>
            <tbody>
              {documents.map((doc) => (
                <tr key={doc.id}>
                  <td>
                    <div className="doc-title">{doc.title}</div>
                    <div className="doc-file">{doc.filename}</div>
                  </td>
                  <td style={{ textTransform: "capitalize" }}>{doc.doc_type}</td>
                  <td>
                    <StatusBadge status={doc.status} />
                    {doc.status === "failed" && doc.error && (
                      <div className="doc-file" title={doc.error}>{doc.error.slice(0, 60)}…</div>
                    )}
                  </td>
                  <td className="num">{doc.chunk_count || "—"}</td>
                  <td className="num">{formatBytes(doc.size_bytes)}</td>
                  <td>{formatWhen(doc.created_at)}</td>
                  {user?.role === "admin" && (
                    <td>
                      <button className="btn btn-danger-ghost" onClick={() => handleDelete(doc.id)} title="Delete">
                        ✕
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
