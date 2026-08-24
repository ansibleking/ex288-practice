import { useEffect, useState } from "react";
import { getHealth, listIssueTypes, submitFeedFile, submitFeedText } from "../api";
import { explainRouting, outcomeText } from "../lib/explainRouting";
import type { ExtraSelectField, FeedResponse } from "../types";
import { ChatInput } from "./ChatInput";
import { ClassificationCard } from "./ClassificationCard";
import { ExtraFieldsSelects, extraFieldsSatisfied } from "./ExtraFieldsSelects";
import { PendingConfirm } from "./PendingConfirm";
import { ReportingServiceSelect } from "./ReportingServiceSelect";
import { StepIndicator } from "./StepIndicator";

const STEPS_SIMPLE = ["Describe", "AI classification", "Done"];
const STEPS_WITH_REVIEW = ["Describe", "AI classification", "Review & confirm", "Done"];
const DEFAULT_ISSUE_TYPES = ["Service Request", "Task", "Bug", "Incident"];

interface Example {
  label: string;
  text: string;
  issueType: string;
}

const EXAMPLES: Example[] = [
  {
    label: "🚨 Report an incident",
    text: "payments-svc is returning intermittent 503 errors since 10:14 UTC, affecting checkout for EU customers",
    issueType: "Task",
  },
  {
    label: "🧾 Request access (Service Request)",
    text: "Please provision VPN access for a new contractor joining the infra team on Monday.",
    issueType: "Service Request",
  },
  {
    label: "🔧 Routine change (Service Request)",
    text: "Please increase the disk quota for the reporting database from 500GB to 1TB ahead of next month's load.",
    issueType: "Service Request",
  },
];

interface Props {
  onSettled: (inputText: string, response: FeedResponse) => void;
}

export function FeedWizard({ onSettled }: Props) {
  const [draftText, setDraftText] = useState("");
  const [inputText, setInputText] = useState<string | null>(null);
  const [response, setResponse] = useState<FeedResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [issueTypes, setIssueTypes] = useState<string[]>(DEFAULT_ISSUE_TYPES);
  const [issueType, setIssueType] = useState<string>(DEFAULT_ISSUE_TYPES[0]);

  const [reportingServiceConfigured, setReportingServiceConfigured] = useState(false);
  const [reportingServiceKey, setReportingServiceKey] = useState<string | null>(null);

  const [extraFields, setExtraFields] = useState<ExtraSelectField[]>([]);
  const [extraFieldValues, setExtraFieldValues] = useState<Record<string, string>>({});

  useEffect(() => {
    listIssueTypes()
      .then((types) => {
        if (types.length > 0) {
          setIssueTypes(types);
          setIssueType((current) => (types.includes(current) ? current : types[0]));
        }
      })
      .catch(() => {
        // Keep the built-in fallback list — the wizard still works, it just
        // can't confirm which issue types this Jira project actually allows.
      });
    getHealth()
      .then((h) => setReportingServiceConfigured(h.reporting_service_configured))
      .catch(() => {
        /* leave the reporting-service picker hidden if health is unreachable */
      });
  }, []);

  const isPending = response?.action_status === "pending_confirmation";
  const steps = isPending ? STEPS_WITH_REVIEW : STEPS_SIMPLE;
  const currentIndex = response === null ? 0 : isPending ? steps.length - 2 : steps.length - 1;

  function reset() {
    setDraftText("");
    setInputText(null);
    setResponse(null);
    setError(null);
    setReportingServiceKey(null);
    setExtraFieldValues({});
  }

  function applyExample(example: Example) {
    setDraftText(example.text);
    if (issueTypes.includes(example.issueType)) setIssueType(example.issueType);
  }

  function missingRequiredFields(): boolean {
    if (reportingServiceConfigured && !reportingServiceKey) return true;
    return !extraFieldsSatisfied(extraFields, extraFieldValues);
  }

  async function handleSubmitText(text: string) {
    setError(null);
    if (missingRequiredFields()) {
      setError("Fill in every required field above before submitting.");
      return;
    }
    try {
      const result = await submitFeedText(
        text,
        "chat",
        issueType,
        reportingServiceKey ?? undefined,
        extraFieldValues,
      );
      setInputText(text);
      setResponse(result);
      if (result.action_status !== "pending_confirmation") onSettled(text, result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to submit feed");
    }
  }

  async function handleSubmitFile(file: File) {
    setError(null);
    if (missingRequiredFields()) {
      setError("Fill in every required field above before submitting.");
      return;
    }
    try {
      const result = await submitFeedFile(file, issueType, reportingServiceKey ?? undefined, extraFieldValues);
      const label = `[file: ${file.name}]`;
      setInputText(label);
      setResponse(result);
      if (result.action_status !== "pending_confirmation") onSettled(label, result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to submit file");
    }
  }

  function handleConfirmed(result: FeedResponse) {
    setResponse(result);
    if (inputText !== null) onSettled(inputText, result);
  }

  function handleCancelled() {
    if (response === null) return;
    const cancelled: FeedResponse = { ...response, action_status: "cancelled" };
    setResponse(cancelled);
    if (inputText !== null) onSettled(inputText, cancelled);
  }

  return (
    <div className="feed-wizard card">
      <StepIndicator steps={steps} currentIndex={currentIndex} />

      {response === null && (
        <div className="wizard-step">
          <p className="wizard-step-hint">
            Describe what you're seeing — a new problem, an access/change request, an update on something
            already tracked, or confirmation that something is resolved.
          </p>

          <div className="example-row">
            {EXAMPLES.map((ex) => (
              <button key={ex.label} className="example-chip" onClick={() => applyExample(ex)}>
                {ex.label}
              </button>
            ))}
          </div>

          <div className="describe-fields">
            <label className="issue-type-select">
              Ticket type (used if a new ticket is created)
              <select value={issueType} onChange={(e) => setIssueType(e.target.value)}>
                {issueTypes.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </label>

            {reportingServiceConfigured && (
              <label className="issue-type-select">
                Reporting service (required)
                <ReportingServiceSelect value={reportingServiceKey} onChange={setReportingServiceKey} />
              </label>
            )}

            <ExtraFieldsSelects
              values={extraFieldValues}
              onChange={(fieldId, optionId) =>
                setExtraFieldValues((prev) => ({ ...prev, [fieldId]: optionId }))
              }
              onFieldsLoaded={setExtraFields}
            />
          </div>

          <ChatInput
            text={draftText}
            onTextChange={setDraftText}
            onSubmitText={handleSubmitText}
            onSubmitFile={handleSubmitFile}
          />
          {error && <p className="error-text">{error}</p>}
        </div>
      )}

      {response !== null && (
        <div className="wizard-step">
          {inputText && <p className="feed-entry-input">{inputText}</p>}
          <ClassificationCard classification={response.classification} />
          <p className="wizard-guidance">{explainRouting(response)}</p>

          {isPending ? (
            <PendingConfirm
              auditId={response.audit_id}
              classification={response.classification}
              issueTypes={issueTypes}
              initialIssueType={issueType}
              reportingServiceConfigured={reportingServiceConfigured}
              initialReportingServiceKey={reportingServiceKey}
              initialExtraFieldValues={extraFieldValues}
              onConfirmed={handleConfirmed}
              onCancelled={handleCancelled}
            />
          ) : (
            <p className="feed-entry-outcome">{outcomeText(response)}</p>
          )}

          {!isPending && (
            <button className="wizard-restart primary-button" onClick={reset}>
              Submit another report
            </button>
          )}
        </div>
      )}
    </div>
  );
}
