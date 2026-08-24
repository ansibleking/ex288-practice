import type { FeedResponse } from "../types";

export function explainRouting(response: FeedResponse): string {
  const key = response.jira_issue_key;
  switch (response.routing_decision) {
    case "auto_create":
      return "Created automatically — confidence and severity were both within the auto-execute thresholds.";
    case "propose_create":
      return "Needs your confirmation before creating a ticket — confidence was below the auto threshold, severity was too high, or this looked like an update with no matching ticket found.";
    case "auto_log_work":
      return `Work logged automatically to ${key ?? "the matched ticket"} — confidence met the (lower) bar for non-destructive updates.`;
    case "auto_resolve":
      return `${key ?? "The matched ticket"} was resolved automatically — a comment, worklog, and status transition were all attempted.`;
    case "propose_resolve":
      return `This looks resolved, but needs your confirmation before ${key ?? "the matched ticket"} is transitioned — severity or confidence didn't clear the auto-resolve bar.`;
    case "skip_as_noise":
      return "Classified as noise — not an actionable operational signal, so nothing was created or changed.";
    default:
      return "";
  }
}

export function outcomeText(response: FeedResponse): string {
  switch (response.action_status) {
    case "executed":
      return `Done — executed automatically${response.jira_issue_key ? ` (${response.jira_issue_key})` : ""}.`;
    case "confirmed":
      return `Done — confirmed and executed${response.jira_issue_key ? ` (${response.jira_issue_key})` : ""}.`;
    case "cancelled":
      return "Done — cancelled, no Jira action taken.";
    case "skipped":
      return "Done — skipped as noise.";
    case "failed":
      return "Done — the action failed partway through. Check the audit log for details.";
    default:
      return "";
  }
}
