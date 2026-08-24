import { useMemo, useRef, useState } from "react";
import { parseSheet } from "../api";
import { NetworkDiagramView } from "./NetworkDiagramView";
import type { ParsedWorkbook } from "../types";

// Common values on access/approval-style sheets -- rendered as colored
// badges (table view) and matched to the same severity colors (chart view)
// instead of plain text, so approved/blocked/pending rows are scannable at a
// glance rather than requiring the reader to parse every cell.
const POSITIVE_VALUES = new Set([
  "yes", "true", "approved", "approve", "active", "allowed", "permitted",
  "granted", "open", "enabled", "ok", "pass", "passed", "completed", "done",
  "success", "authorized",
]);
const NEGATIVE_VALUES = new Set([
  "no", "false", "rejected", "reject", "denied", "deny", "blocked", "closed",
  "disabled", "revoked", "fail", "failed", "expired", "terminated",
]);
const WARNING_VALUES = new Set([
  "pending", "review", "in progress", "requested", "in review", "awaiting",
  "hold", "on hold", "pending approval", "expiring",
]);

function cellTone(raw: string): "low" | "critical" | "medium" | null {
  const v = raw.trim().toLowerCase();
  if (!v) return null;
  if (POSITIVE_VALUES.has(v)) return "low";
  if (NEGATIVE_VALUES.has(v)) return "critical";
  if (WARNING_VALUES.has(v)) return "medium";
  return null;
}

const CATEGORICAL_PALETTE = [
  "var(--accent)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
  "var(--chart-6)",
];

function colorForSlice(label: string, index: number): string {
  const tone = cellTone(label);
  if (tone) return `var(--severity-${tone})`;
  if (label === "Other") return "var(--muted)";
  return CATEGORICAL_PALETTE[index % CATEGORICAL_PALETTE.length];
}

function distinctCount(rows: string[][], col: number): number {
  const seen = new Set<string>();
  for (const row of rows) seen.add((row[col] ?? "").trim() || "(blank)");
  return seen.size;
}

// Defaults the chart to whichever column looks most like a category (a
// handful of repeated values, e.g. a status or type column) rather than a
// column of mostly-unique values (e.g. a hostname or ticket key), which
// would render as a wall of same-size slices with no useful signal.
function pickDefaultChartColumn(headers: string[], rows: string[][]): number {
  let best = 0;
  let bestScore = Infinity;
  headers.forEach((_, i) => {
    const d = distinctCount(rows, i);
    if (d >= 2 && d <= 12 && d < bestScore) {
      bestScore = d;
      best = i;
    }
  });
  return best;
}

const MAX_SLICES = 8;
const DONUT_RADIUS = 60;
const DONUT_STROKE = 26;

function SheetDonut({ entries, total }: { entries: [string, number][]; total: number }) {
  const circumference = 2 * Math.PI * DONUT_RADIUS;
  let cumulative = 0;
  return (
    <svg viewBox="0 0 160 160" width="180" height="180" className="donut-chart" role="img" aria-label="Column breakdown chart">
      <circle cx="80" cy="80" r={DONUT_RADIUS} fill="none" stroke="var(--border)" strokeWidth={DONUT_STROKE} />
      {entries.map(([label, count], i) => {
        const dash = (count / total) * circumference;
        const el = (
          <circle
            key={label}
            cx="80"
            cy="80"
            r={DONUT_RADIUS}
            fill="none"
            stroke={colorForSlice(label, i)}
            strokeWidth={DONUT_STROKE}
            strokeDasharray={`${dash} ${circumference - dash}`}
            strokeDashoffset={-cumulative}
            transform="rotate(-90 80 80)"
          />
        );
        cumulative += dash;
        return el;
      })}
      <text x="80" y="76" textAnchor="middle" className="donut-center-value">
        {total}
      </text>
      <text x="80" y="94" textAnchor="middle" className="donut-center-label">
        rows
      </text>
    </svg>
  );
}

type SortState = { col: number; dir: "asc" | "desc" };
type View = "table" | "chart" | "diagram";

export function SheetViewer() {
  const [workbook, setWorkbook] = useState<ParsedWorkbook | null>(null);
  const [activeSheet, setActiveSheet] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [sort, setSort] = useState<SortState | null>(null);
  const [view, setView] = useState<View>("table");
  const [chartColumn, setChartColumn] = useState(0);
  const fileInputRef = useRef<HTMLInputElement>(null);

  async function handleFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setLoading(true);
    setError(null);
    try {
      const parsed = await parseSheet(file);
      setWorkbook(parsed);
      setActiveSheet(0);
      setFilter("");
      setSort(null);
      setView("table");
      const first = parsed.sheets[0];
      setChartColumn(first ? pickDefaultChartColumn(first.headers, first.rows) : 0);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to read this file");
    } finally {
      setLoading(false);
    }
  }

  function selectSheet(i: number) {
    setActiveSheet(i);
    setFilter("");
    setSort(null);
    const s = workbook?.sheets[i];
    setChartColumn(s ? pickDefaultChartColumn(s.headers, s.rows) : 0);
  }

  function toggleSort(col: number) {
    setSort((prev) => {
      if (!prev || prev.col !== col) return { col, dir: "asc" };
      if (prev.dir === "asc") return { col, dir: "desc" };
      return null;
    });
  }

  const sheet = workbook?.sheets[activeSheet];

  const visibleRows = useMemo(() => {
    if (!sheet) return [];
    let rows = sheet.rows;
    const needle = filter.trim().toLowerCase();
    if (needle) {
      rows = rows.filter((row) => row.some((cell) => cell.toLowerCase().includes(needle)));
    }
    if (sort) {
      const { col, dir } = sort;
      rows = [...rows].sort((a, b) => {
        const av = a[col] ?? "";
        const bv = b[col] ?? "";
        const an = Number(av);
        const bn = Number(bv);
        const cmp =
          av !== "" && bv !== "" && !Number.isNaN(an) && !Number.isNaN(bn)
            ? an - bn
            : av.localeCompare(bv);
        return dir === "asc" ? cmp : -cmp;
      });
    }
    return rows;
  }, [sheet, filter, sort]);

  const chartData = useMemo(() => {
    if (!sheet || sheet.headers.length === 0) return null;
    const counts = new Map<string, number>();
    for (const row of visibleRows) {
      const raw = (row[chartColumn] ?? "").trim();
      counts.set(raw || "(blank)", (counts.get(raw || "(blank)") ?? 0) + 1);
    }
    let entries = [...counts.entries()].sort((a, b) => b[1] - a[1]);
    if (entries.length > MAX_SLICES) {
      const top = entries.slice(0, MAX_SLICES - 1);
      const otherCount = entries.slice(MAX_SLICES - 1).reduce((sum, [, c]) => sum + c, 0);
      entries = [...top, ["Other", otherCount]];
    }
    return { entries, total: visibleRows.length };
  }, [sheet, visibleRows, chartColumn]);

  return (
    <div className="sheet-viewer">
      <div className="sheet-viewer-toolbar">
        <button className="attachment-upload-button" disabled={loading} onClick={() => fileInputRef.current?.click()}>
          {loading ? "Reading…" : workbook ? "+ Open a different sheet" : "+ Upload a spreadsheet"}
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept=".xlsx,.csv"
          style={{ display: "none" }}
          onChange={(e) => void handleFileChange(e)}
        />
        {workbook && <span className="panel-subtitle">{workbook.filename}</span>}
      </div>

      {error && <p className="error-text">{error}</p>}

      {!workbook && !error && (
        <p className="empty-state">
          Download the attachment from Jira, then upload it here (.xlsx or .csv) to view it as a table or chart —
          no Jira session or download-folder round trip required to read it.
        </p>
      )}

      {workbook && workbook.sheets.length > 1 && (
        <div className="sheet-tabs">
          {workbook.sheets.map((s, i) => (
            <button
              key={s.name}
              className={i === activeSheet ? "sheet-tab active" : "sheet-tab"}
              onClick={() => selectSheet(i)}
            >
              {s.name}
            </button>
          ))}
        </div>
      )}

      {sheet && sheet.truncated && (
        <p className="empty-state">
          This sheet is large — showing the first {sheet.rows.length} rows
          {sheet.headers.length > 0 ? ` and ${sheet.headers.length} columns` : ""}.
        </p>
      )}

      {sheet && (
        <>
          <div className="sheet-controls">
            <input
              type="search"
              placeholder="Filter rows — e.g. a host, user, or status…"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            />
            <span className="panel-subtitle sheet-row-count">
              {filter ? `${visibleRows.length} of ${sheet.rows.length} rows` : `${sheet.rows.length} rows`}
            </span>
            <div className="sheet-view-toggle">
              <button className={view === "table" ? "sheet-tab active" : "sheet-tab"} onClick={() => setView("table")}>
                Table
              </button>
              <button className={view === "chart" ? "sheet-tab active" : "sheet-tab"} onClick={() => setView("chart")}>
                Chart
              </button>
              <button className={view === "diagram" ? "sheet-tab active" : "sheet-tab"} onClick={() => setView("diagram")}>
                Diagram
              </button>
            </div>
          </div>

          {view === "table" && (
            <div className="table-scroll sheet-table-scroll">
              <table className="data-table sheet-table">
                <thead>
                  <tr>
                    {sheet.headers.map((h, i) => (
                      <th key={i}>
                        <button
                          type="button"
                          className="sheet-th-sort"
                          onClick={() => toggleSort(i)}
                          aria-label={`Sort by ${h}`}
                        >
                          {h}
                          <span className="sort-indicator">
                            {sort?.col === i ? (sort.dir === "asc" ? "▲" : "▼") : ""}
                          </span>
                        </button>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {visibleRows.map((row, i) => (
                    <tr key={i}>
                      {row.map((cell, j) => {
                        const tone = cellTone(cell);
                        return (
                          <td key={j} title={cell}>
                            {tone ? <span className={`badge severity-${tone}`}>{cell}</span> : cell}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                  {visibleRows.length === 0 && (
                    <tr>
                      <td colSpan={Math.max(sheet.headers.length, 1)} className="empty-state">
                        {filter ? "No rows match your filter." : "This sheet has no data rows."}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}

          {view === "chart" && (
            <div className="sheet-chart">
              <label className="sheet-chart-column-picker">
                Chart by
                <select value={chartColumn} onChange={(e) => setChartColumn(Number(e.target.value))}>
                  {sheet.headers.map((h, i) => (
                    <option key={i} value={i}>
                      {h}
                    </option>
                  ))}
                </select>
              </label>

              {chartData && chartData.total > 0 ? (
                <div className="donut-wrap">
                  <SheetDonut entries={chartData.entries} total={chartData.total} />
                  <ul className="donut-legend">
                    {chartData.entries.map(([label, count], i) => (
                      <li key={label}>
                        <span className="donut-swatch" style={{ background: colorForSlice(label, i) }} />
                        <span className="donut-label">{label}</span>
                        <span className="donut-count">
                          {count} ({Math.round((count / chartData.total) * 100)}%)
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : (
                <p className="empty-state">No data to chart{filter ? " for the current filter" : ""}.</p>
              )}
            </div>
          )}

          {view === "diagram" && (
            <NetworkDiagramView key={`${activeSheet}-${filter}`} headers={sheet.headers} rows={visibleRows} />
          )}
        </>
      )}
    </div>
  );
}
