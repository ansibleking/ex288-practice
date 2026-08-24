import { Fragment, useEffect, useState } from "react";
import { getApprovalDetail, getApprovalSummary, transitionApproval } from "../api";
import { formatBytes } from "../lib/formatBytes";
import type { ApprovalSummary, TicketApprovalDetail, TransitionOption } from "../types";

interface Props {
  ticketKey: string;
  onClose: () => void;
  onTransitioned: () => void;
}

const APPROVE_PATTERN = /approve/i;
const REJECT_PATTERN = /reject|decline/i;

export function ApprovalDetailModal({ ticketKey, onClose, onTransitioned }: Props) {
  const [detail, setDetail] = useState<TicketApprovalDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [summary, setSummary] = useState<ApprovalSummary | null>(null);
  const [summarizing, setSummarizing] = useState(false);
  const [summaryError, setSummaryError] = useState<string | null>(null);

  const [actingTransitionId, setActingTransitionId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [comment, setComment] = useState("");
  const [extraValues, setExtraValues] = useState<Record<string, string>>({});

  useEffect(() => {
    let cancelled = false;
    setDetail(null);
    setError(null);
    setSummary(null);
    setSummaryError(null);
    getApprovalDetail(ticketKey)
      .then((d) => {
        if (!cancelled) setDetail(d);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load ticket");
      });
    return () => {
      cancelled = true;
    };
  }, [ticketKey]);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  async function handleSummarize() {
    setSummarizing(true);
    setSummaryError(null);
    try {
      setSummary(await getApprovalSummary(ticketKey));
    } catch (err) {
      setSummaryError(err instanceof Error ? err.message : "Failed to generate AI summary");
    } finally {
      setSummarizing(false);
    }
  }

  async function handleTransition(t: TransitionOption) {
    setActingTransitionId(t.id);
    setActionError(null);
    try {
      const extraFieldValues: Record<string, string | number> = {};
      for (const f of t.extra_fields) {
        const raw = extraValues[`${t.id}:${f.field_id}`] ?? "";
        if (raw === "") continue;
        extraFieldValues[f.field_id] = f.type === "number" ? Number(raw) : raw;
      }
      const refreshed = await transitionApproval(ticketKey, t.id, comment.trim(), extraFieldValues);
      setDetail(refreshed);
      setDone(true);
      onTransitioned();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Failed to apply this action");
    } finally {
      setActingTransitionId(null);
    }
  }

  function setExtraValue(transitionId: string, fieldId: string, value: string) {
    setExtraValues((prev) => ({ ...prev, [`${transitionId}:${fieldId}`]: value }));
  }

  const approveTransitions = detail?.transitions.filter((t) => APPROVE_PATTERN.test(t.name)) ?? [];
  const rejectTransitions = detail?.transitions.filter((t) => REJECT_PATTERN.test(t.name)) ?? [];
  const otherTransitions =
    detail?.transitions.filter((t) => !APPROVE_PATTERN.test(t.name) && !REJECT_PATTERN.test(t.name)) ?? [];

  function renderTransitionRow(t: TransitionOption, buttonClassName?: string) {
    return (
      <div key={t.id} className="transition-row">
        {t.extra_fields.length > 0 && (
          <div className="transition-extra-fields">
            {t.extra_fields.map((f) => (
              <label key={f.field_id}>
                {f.label}
                <input
                  type={f.type === "number" ? "number" : "text"}
                  value={extraValues[`${t.id}:${f.field_id}`] ?? ""}
                  onChange={(e) => setExtraValue(t.id, f.field_id, e.target.value)}
                />
              </label>
            ))}
          </div>
        )}
        <button
          className={buttonClassName}
          disabled={actingTransitionId !== null}
          onClick={() => void handleTransition(t)}
        >
          {actingTransitionId === t.id ? "Working…" : t.name}
        </button>
      </div>
    );
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>{ticketKey}</h2>
          <button className="icon-button" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>

        {error && <p className="error-text">{error}</p>}
        {!detail && !error && <p className="empty-state">Loading…</p>}

        {detail && (
          <div className="modal-body">
            <p className="ticket-detail-summary">{detail.summary}</p>
            <div className="badges">
              <span className="badge">{detail.status}</span>
              <span className="badge">{detail.issue_type}</span>
            </div>

            <dl className="ticket-detail-meta">
              <dt>Reporter</dt>
              <dd>{detail.reporter ?? "—"}</dd>
              <dt>Assignee</dt>
              <dd>{detail.assignee ?? "Unassigned"}</dd>
              <dt>Created</dt>
              <dd>{new Date(detail.created).toLocaleString()}</dd>
              <dt>Updated</dt>
              <dd>{new Date(detail.updated).toLocaleString()}</dd>
            </dl>

            {detail.description && (
              <div className="ticket-detail-section">
                <h3>Description</h3>
                <p className="ticket-detail-description">{detail.description}</p>
              </div>
            )}

            {detail.attachments.length > 0 && (
              <div className="ticket-detail-section">
                <h3>Attachments ({detail.attachments.length})</h3>
                <ul className="attachment-list">
                  {detail.attachments.map((a) => (
                    <li key={a.id}>
                      <a href={a.url} target="_blank" rel="noreferrer" className="link-button">
                        {a.filename}
                      </a>
                      <span className="attachment-meta">
                        {formatBytes(a.size)} · {a.author} · {new Date(a.created).toLocaleString()}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {detail.fields.length > 0 && (
              <div className="ticket-detail-section">
                <h3>Request details</h3>
                <dl className="ticket-detail-meta">
                  {detail.fields.map((f) => (
                    <Fragment key={f.label}>
                      <dt>{f.label}</dt>
                      <dd>{f.value}</dd>
                    </Fragment>
                  ))}
                </dl>
              </div>
            )}

            <div className="ticket-detail-section">
              <h3>AI summary</h3>
              {!summary && (
                <button disabled={summarizing} onClick={() => void handleSummarize()}>
                  {summarizing ? "Summarizing…" : "Summarize with AI"}
                </button>
              )}
              {summaryError && <p className="error-text">{summaryError}</p>}
              {summary && (
                <div className="approval-summary">
                  <p>{summary.overview}</p>
                  {summary.key_details.length > 0 && (
                    <ul className="approval-summary-list">
                      {summary.key_details.map((d, i) => (
                        <li key={i}>{d}</li>
                      ))}
                    </ul>
                  )}
                  {summary.concerns.length > 0 && (
                    <>
                      <p className="approval-summary-label">Worth checking</p>
                      <ul className="approval-summary-list approval-summary-concerns">
                        {summary.concerns.map((c, i) => (
                          <li key={i}>{c}</li>
                        ))}
                      </ul>
                    </>
                  )}
                  <div className="approval-recommendation">
                    <span className={`badge severity-${recommendationSeverity(summary.recommendation)}`}>
                      AI suggests: {recommendationLabel(summary.recommendation)}
                    </span>
                    <p className="approval-summary-reasoning">{summary.reasoning}</p>
                  </div>
                  <p className="panel-subtitle">
                    Advisory only — nothing is approved or rejected until you choose an action below.
                  </p>
                </div>
              )}
            </div>

            <div className="ticket-detail-section">
              <h3>Your decision</h3>
              {done && <p className="empty-state">Action recorded — status is now "{detail.status}".</p>}
              {!done && detail.transitions.length > 0 && (
                <label className="approval-comment-field">
                  Comment (some actions require one — e.g. rejecting or requesting clarification)
                  <textarea
                    rows={2}
                    value={comment}
                    onChange={(e) => setComment(e.target.value)}
                    placeholder="Optional reason to record on the ticket"
                  />
                </label>
              )}
              {actionError && <p className="error-text">{actionError}</p>}
              {detail.transitions.length === 0 && !done && (
                <p className="empty-state">No actions are currently available on this ticket.</p>
              )}
              <div className="transition-list">
                {approveTransitions.map((t) =>
                  renderTransitionRow(t, "confirm-button"),
                )}
                {rejectTransitions.map((t) => renderTransitionRow(t, "reject-button"))}
                {otherTransitions.map((t) => renderTransitionRow(t))}
              </div>
            </div>

            <a className="external-link" href={detail.url} target="_blank" rel="noreferrer">
              Open in Jira ↗
            </a>
          </div>
        )}
      </div>
    </div>
  );
}

function recommendationLabel(r: ApprovalSummary["recommendation"]): string {
  if (r === "approve") return "Approve";
  if (r === "reject") return "Reject";
  return "Needs more info";
}

function recommendationSeverity(r: ApprovalSummary["recommendation"]): string {
  if (r === "approve") return "low";
  if (r === "reject") return "high";
  return "medium";
}
