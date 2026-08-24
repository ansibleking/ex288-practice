import { useState } from "react";
import { cancelPending, confirmPending } from "../api";
import type { ExtraSelectField, FeedClassification, FeedResponse, Severity } from "../types";
import { ExtraFieldsSelects, extraFieldsSatisfied } from "./ExtraFieldsSelects";
import { ReportingServiceSelect } from "./ReportingServiceSelect";

interface Props {
  auditId: number;
  classification: FeedClassification;
  issueTypes: string[];
  initialIssueType: string;
  reportingServiceConfigured: boolean;
  initialReportingServiceKey: string | null;
  initialExtraFieldValues: Record<string, string>;
  onConfirmed: (result: FeedResponse) => void;
  onCancelled: () => void;
}

const SEVERITIES: Severity[] = ["low", "medium", "high", "critical"];

export function PendingConfirm({
  auditId,
  classification,
  issueTypes,
  initialIssueType,
  reportingServiceConfigured,
  initialReportingServiceKey,
  initialExtraFieldValues,
  onConfirmed,
  onCancelled,
}: Props) {
  const [title, setTitle] = useState(classification.title);
  const [severity, setSeverity] = useState<Severity>(classification.severity);
  const [issueType, setIssueType] = useState(initialIssueType);
  const [reportingServiceKey, setReportingServiceKey] = useState(initialReportingServiceKey);
  const [extraFields, setExtraFields] = useState<ExtraSelectField[]>([]);
  const [extraFieldValues, setExtraFieldValues] = useState(initialExtraFieldValues);
  const [busy, setBusy] = useState<"confirm" | "cancel" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const isCreate = !classification.matched_ticket_key;
  const missingRequiredFields =
    isCreate &&
    ((reportingServiceConfigured && !reportingServiceKey) || !extraFieldsSatisfied(extraFields, extraFieldValues));

  async function handleConfirm() {
    setBusy("confirm");
    setError(null);
    try {
      onConfirmed(
        await confirmPending(auditId, {
          title,
          severity,
          issue_type: issueType,
          reporting_service_key: reportingServiceKey ?? undefined,
          extra_field_values: extraFieldValues,
        }),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to confirm");
    } finally {
      setBusy(null);
    }
  }

  async function handleCancel() {
    setBusy("cancel");
    setError(null);
    try {
      await cancelPending(auditId);
      onCancelled();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to cancel");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="pending-confirm">
      <p className="pending-note">
        Review and edit the AI's proposal if needed, then confirm — nothing touches Jira until you do.
      </p>
      <div className="review-form">
        <label>
          Title
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            disabled={busy !== null}
          />
        </label>
        <label>
          Severity
          <select
            value={severity}
            onChange={(e) => setSeverity(e.target.value as Severity)}
            disabled={busy !== null}
          >
            {SEVERITIES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        {isCreate && (
          <label>
            Ticket type
            <select value={issueType} onChange={(e) => setIssueType(e.target.value)} disabled={busy !== null}>
              {issueTypes.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </label>
        )}
        {isCreate && reportingServiceConfigured && (
          <label>
            Reporting service (required)
            <ReportingServiceSelect
              value={reportingServiceKey}
              onChange={setReportingServiceKey}
              disabled={busy !== null}
            />
          </label>
        )}
        {isCreate && (
          <ExtraFieldsSelects
            values={extraFieldValues}
            onChange={(fieldId, optionId) =>
              setExtraFieldValues((prev) => ({ ...prev, [fieldId]: optionId }))
            }
            onFieldsLoaded={setExtraFields}
            disabled={busy !== null}
          />
        )}
        {classification.matched_ticket_key && (
          <p className="review-readonly">
            Matched ticket: <strong>{classification.matched_ticket_key}</strong> (not editable here)
          </p>
        )}
      </div>
      {error && <p className="error-text">{error}</p>}
      <div className="actions">
        <button
          className="confirm-button"
          disabled={busy !== null || !title.trim() || missingRequiredFields}
          onClick={handleConfirm}
        >
          {busy === "confirm" ? "Working…" : "Confirm & Create/Update"}
        </button>
        <button disabled={busy !== null} onClick={handleCancel}>
          {busy === "cancel" ? "Working…" : "Cancel"}
        </button>
      </div>
    </div>
  );
}
