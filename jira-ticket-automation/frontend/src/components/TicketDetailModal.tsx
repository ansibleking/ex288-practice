import { useEffect, useRef, useState } from "react";
import { getTicketDetail, uploadAttachment } from "../api";
import { formatBytes } from "../lib/formatBytes";
import type { JiraTicketDetail } from "../types";

interface Props {
  ticketKey: string;
  onClose: () => void;
}

export function TicketDetailModal({ ticketKey, onClose }: Props) {
  const [detail, setDetail] = useState<JiraTicketDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let cancelled = false;
    setDetail(null);
    setError(null);
    getTicketDetail(ticketKey)
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

  async function handleFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setUploading(true);
    setUploadError(null);
    try {
      setDetail(await uploadAttachment(ticketKey, file));
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "Failed to upload attachment");
    } finally {
      setUploading(false);
    }
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
              {detail.priority && <span className="badge">{detail.priority}</span>}
            </div>

            <dl className="ticket-detail-meta">
              <dt>Assignee</dt>
              <dd>{detail.assignee ?? "Unassigned"}</dd>
              <dt>Reporter</dt>
              <dd>{detail.reporter ?? "—"}</dd>
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

            <div className="ticket-detail-section">
              <h3>Attachments ({detail.attachments.length})</h3>
              {detail.attachments.length === 0 && <p className="empty-state">No attachments yet.</p>}
              {detail.attachments.length > 0 && (
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
              )}
              {uploadError && <p className="error-text">{uploadError}</p>}
              <button
                className="attachment-upload-button"
                disabled={uploading}
                onClick={() => fileInputRef.current?.click()}
              >
                {uploading ? "Uploading…" : "+ Attach file / screenshot"}
              </button>
              <input
                ref={fileInputRef}
                type="file"
                style={{ display: "none" }}
                onChange={(e) => void handleFileChange(e)}
              />
            </div>

            <div className="ticket-detail-section">
              <h3>Comments ({detail.comments.length})</h3>
              {detail.comments.length === 0 && <p className="empty-state">No comments yet.</p>}
              {detail.comments.map((c, i) => (
                <div key={i} className="comment-item">
                  <div className="comment-meta">
                    <strong>{c.author}</strong>
                    <span>{new Date(c.created).toLocaleString()}</span>
                  </div>
                  <p>{c.body}</p>
                </div>
              ))}
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
