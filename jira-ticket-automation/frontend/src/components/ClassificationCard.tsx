import type { FeedClassification } from "../types";

const INTENT_LABEL: Record<string, string> = {
  new_issue: "New issue",
  service_request: "Service request",
  update_existing: "Update to existing",
  resolved: "Resolved",
  noise: "Noise (not actionable)",
};

export function ClassificationCard({ classification }: { classification: FeedClassification }) {
  return (
    <div className="classification-card">
      <div className="badges">
        <span className={`badge intent-${classification.intent}`}>
          {INTENT_LABEL[classification.intent] ?? classification.intent}
        </span>
        <span className={`badge severity-${classification.severity}`}>{classification.severity}</span>
        <span className="badge confidence">{Math.round(classification.confidence * 100)}% confidence</span>
        {classification.matched_ticket_key && (
          <span className="badge matched">matches {classification.matched_ticket_key}</span>
        )}
      </div>
      <p className="classification-title">{classification.title}</p>
      <p className="classification-summary">{classification.summary}</p>
      <p className="classification-reasoning">{classification.reasoning}</p>
      {classification.resolution_comment && (
        <p className="classification-resolution">
          <strong>Resolution:</strong> {classification.resolution_comment}
        </p>
      )}
    </div>
  );
}
