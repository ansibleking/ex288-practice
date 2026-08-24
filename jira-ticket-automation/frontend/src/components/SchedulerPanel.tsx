import { Fragment, useEffect, useState } from "react";
import { cancelScheduledItem, createScheduledItem, getHealth, listIssueTypes, listSchedule } from "../api";
import { dayRangeIso, localDateAndTimeToIso, todayLocalDate } from "../lib/scheduleTime";
import type { ExtraSelectField, ScheduledItem } from "../types";
import { ExtraFieldsSelects, extraFieldsSatisfied } from "./ExtraFieldsSelects";
import { ReportingServiceSelect } from "./ReportingServiceSelect";
import { TicketDetailModal } from "./TicketDetailModal";

const DEFAULT_ISSUE_TYPES = ["Service Request", "Task", "Bug", "Incident"];

const STATUS_LABEL: Record<string, string> = {
  pending: "Pending",
  created: "Created",
  resolved: "Resolved",
  create_failed: "Create failed",
  resolve_failed: "Resolve failed",
  cancelled: "Cancelled",
};

function scheduleStatusMessage(item: ScheduledItem): string {
  if (item.error) return item.error;
  switch (item.status) {
    case "pending":
      return "Waiting for its start time — nothing has happened yet.";
    case "created":
      return item.jira_issue_key
        ? `Created ${item.jira_issue_key} at its start time.`
        : "Created at its start time.";
    case "resolved":
      return item.jira_issue_key
        ? `${item.jira_issue_key} resolved automatically at its end time.`
        : "Resolved automatically at its end time.";
    case "cancelled":
      return "Cancelled — no Jira action was taken.";
    default:
      return item.status;
  }
}

export function SchedulerPanel() {
  const [date, setDate] = useState(todayLocalDate());
  const [items, setItems] = useState<ScheduledItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [issueTypes, setIssueTypes] = useState<string[]>(DEFAULT_ISSUE_TYPES);
  const [startTime, setStartTime] = useState("09:00");
  const [endTime, setEndTime] = useState("");
  const [text, setText] = useState("");
  const [issueType, setIssueType] = useState(DEFAULT_ISSUE_TYPES[0]);
  const [reportingServiceConfigured, setReportingServiceConfigured] = useState(false);
  const [reportingServiceKey, setReportingServiceKey] = useState<string | null>(null);
  const [extraFields, setExtraFields] = useState<ExtraSelectField[]>([]);
  const [extraFieldValues, setExtraFieldValues] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const [openKey, setOpenKey] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<number | null>(null);

  useEffect(() => {
    listIssueTypes()
      .then((types) => {
        if (types.length > 0) {
          setIssueTypes(types);
          setIssueType(types[0]);
        }
      })
      .catch(() => {
        /* keep fallback list */
      });
    getHealth()
      .then((h) => setReportingServiceConfigured(h.reporting_service_configured))
      .catch(() => {
        /* leave the reporting-service picker hidden if health is unreachable */
      });
  }, []);

  async function refresh() {
    setError(null);
    try {
      const { start, end } = dayRangeIso(date);
      setItems(await listSchedule(start, end));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load schedule");
    }
  }

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [date]);

  const missingRequiredFields =
    (reportingServiceConfigured && !reportingServiceKey) || !extraFieldsSatisfied(extraFields, extraFieldValues);

  async function handleAdd() {
    if (!text.trim() || !startTime || missingRequiredFields) return;
    setSubmitting(true);
    setFormError(null);
    try {
      await createScheduledItem({
        start_at: localDateAndTimeToIso(date, startTime),
        end_at: endTime ? localDateAndTimeToIso(date, endTime) : undefined,
        text: text.trim(),
        issue_type: issueType,
        reporting_service_key: reportingServiceKey ?? undefined,
        extra_field_values: extraFieldValues,
      });
      setText("");
      setReportingServiceKey(null);
      setExtraFieldValues({});
      await refresh();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Failed to schedule item");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleCancel(id: number) {
    try {
      await cancelScheduledItem(id);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to cancel item");
    }
  }

  return (
    <div className="scheduler-layout">
      <div className="card">
        <div className="panel-header">
          <h2>Add to schedule</h2>
        </div>
        <p className="panel-subtitle">
          A ticket is created automatically at the start time, and — if you set an end time — resolved
          automatically when the window ends.
        </p>
        <div className="schedule-form">
          <label>
            Date
            <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          </label>
          <label>
            Start time
            <input type="time" value={startTime} onChange={(e) => setStartTime(e.target.value)} />
          </label>
          <label>
            End time (optional — auto-resolves at this time)
            <input type="time" value={endTime} onChange={(e) => setEndTime(e.target.value)} />
          </label>
          <label>
            Ticket type
            <select value={issueType} onChange={(e) => setIssueType(e.target.value)}>
              {issueTypes.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </label>
          {reportingServiceConfigured && (
            <label>
              Reporting service (required)
              <ReportingServiceSelect value={reportingServiceKey} onChange={setReportingServiceKey} />
            </label>
          )}
          <ExtraFieldsSelects
            values={extraFieldValues}
            onChange={(fieldId, optionId) => setExtraFieldValues((prev) => ({ ...prev, [fieldId]: optionId }))}
            onFieldsLoaded={setExtraFields}
          />
          <label className="schedule-form-description">
            Description
            <textarea
              rows={2}
              value={text}
              placeholder="e.g. DB maintenance window — replication paused"
              onChange={(e) => setText(e.target.value)}
            />
          </label>
        </div>
        {formError && <p className="error-text">{formError}</p>}
        <button
          className="primary-button"
          disabled={submitting || !text.trim() || !startTime || missingRequiredFields}
          onClick={() => void handleAdd()}
        >
          {submitting ? "Adding…" : "+ Add entry"}
        </button>
      </div>

      <div className="card">
        <div className="panel-header">
          <h2>Schedule for {date}</h2>
          <button onClick={() => void refresh()}>Refresh</button>
        </div>
        {error && <p className="error-text">{error}</p>}
        {items === null && !error && <p className="empty-state">Loading…</p>}
        {items && items.length === 0 && <p className="empty-state">Nothing scheduled for this day yet.</p>}
        {items && items.length > 0 && (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Start</th>
                  <th>End</th>
                  <th>Description</th>
                  <th>Type</th>
                  <th>Status</th>
                  <th>Ticket</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => {
                  const key = item.jira_issue_key;
                  const isOpen = expandedId === item.id;
                  return (
                    <Fragment key={item.id}>
                      <tr>
                        <td className="num">
                          {new Date(item.start_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                        </td>
                        <td className="num">
                          {item.end_at
                            ? new Date(item.end_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
                            : "—"}
                        </td>
                        <td className="input-cell" title={item.text}>
                          {item.text.length > 60 ? `${item.text.slice(0, 60)}…` : item.text}
                        </td>
                        <td>{item.issue_type}</td>
                        <td>
                          <button
                            type="button"
                            className={`status-pill status-schedule-${item.status} status-pill-toggle`}
                            onClick={() => setExpandedId(isOpen ? null : item.id)}
                            aria-expanded={isOpen}
                          >
                            {STATUS_LABEL[item.status] ?? item.status}
                          </button>
                        </td>
                        <td>
                          {key ? (
                            <button className="link-button" onClick={() => setOpenKey(key)}>
                              {key}
                            </button>
                          ) : (
                            "—"
                          )}
                        </td>
                        <td>
                          {item.status === "pending" && (
                            <button onClick={() => void handleCancel(item.id)}>Cancel</button>
                          )}
                        </td>
                      </tr>
                      {isOpen && (
                        <tr className="detail-row">
                          <td colSpan={7}>
                            <p className="detail-message">{scheduleStatusMessage(item)}</p>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {openKey && <TicketDetailModal ticketKey={openKey} onClose={() => setOpenKey(null)} />}
    </div>
  );
}
