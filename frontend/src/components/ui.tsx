import type { DocumentStatus } from "../types";

export function StatusBadge({ status }: { status: DocumentStatus }) {
  const label: Record<DocumentStatus, string> = {
    pending: "Queued",
    processing: "Processing",
    ready: "Ready",
    failed: "Failed",
  };
  return (
    <span className={`badge badge-${status}`}>
      <span className="dot" />
      {label[status]}
    </span>
  );
}

export function Spinner() {
  return <span className="spinner" aria-label="loading" />;
}

export function MetricBar({ label, value }: { label: string; value: number | null }) {
  return (
    <div className="metric">
      <span className="mlabel">{label}</span>
      <span className="track" role="img" aria-label={`${label}: ${value === null ? "not computed" : value.toFixed(2)}`}>
        <span className="fill" style={{ width: value === null ? 0 : `${Math.round(value * 100)}%` }} />
      </span>
      <span className={value === null ? "mval na" : "mval"}>{value === null ? "—" : value.toFixed(2)}</span>
    </div>
  );
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function formatWhen(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

const stroke = { fill: "none", stroke: "currentColor", strokeWidth: 1.6, strokeLinecap: "round", strokeLinejoin: "round" } as const;

export const Icons = {
  docs: (
    <svg width="16" height="16" viewBox="0 0 24 24" {...stroke}>
      <path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z" />
      <path d="M14 3v5h5" />
    </svg>
  ),
  ask: (
    <svg width="16" height="16" viewBox="0 0 24 24" {...stroke}>
      <path d="M21 12a8 8 0 0 1-8 8H4l2.5-2.7A8 8 0 1 1 21 12z" />
    </svg>
  ),
  search: (
    <svg width="16" height="16" viewBox="0 0 24 24" {...stroke}>
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-3.8-3.8" />
    </svg>
  ),
  gauge: (
    <svg width="16" height="16" viewBox="0 0 24 24" {...stroke}>
      <path d="M4 14a8 8 0 1 1 16 0" />
      <path d="m12 14 4-5" />
      <path d="M2 20h20" />
    </svg>
  ),
  logout: (
    <svg width="15" height="15" viewBox="0 0 24 24" {...stroke}>
      <path d="M15 4h4a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-4" />
      <path d="m10 17 5-5-5-5" />
      <path d="M15 12H3" />
    </svg>
  ),
};
