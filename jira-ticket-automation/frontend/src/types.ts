export type Intent = "new_issue" | "service_request" | "update_existing" | "resolved" | "noise";
export type Severity = "low" | "medium" | "high" | "critical";

export interface FeedClassification {
  intent: Intent;
  confidence: number;
  severity: Severity;
  matched_ticket_key: string | null;
  title: string;
  summary: string;
  reasoning: string;
  resolution_comment: string | null;
}

export type ActionStatus =
  | "executed"
  | "pending_confirmation"
  | "confirmed"
  | "cancelled"
  | "skipped"
  | "failed";

export interface FeedResponse {
  audit_id: number;
  classification: FeedClassification;
  routing_decision: string;
  action_status: ActionStatus;
  jira_issue_key: string | null;
}

export interface AuditRow {
  id: number;
  created_at: string;
  input_text: string;
  input_source: string;
  llm_intent: Intent;
  llm_confidence: number;
  llm_severity: Severity;
  llm_matched_ticket_key: string | null;
  llm_title: string;
  llm_summary: string;
  llm_reasoning: string;
  llm_raw_response_json: string;
  routing_decision: string;
  threshold_confidence_min: number;
  threshold_severity_max: string;
  action_status: ActionStatus;
  jira_action_type: string | null;
  jira_issue_key: string | null;
  jira_error: string | null;
}

export interface CandidateTicket {
  key: string;
  summary: string;
  description_excerpt: string;
}

export interface JiraTicketSummary {
  key: string;
  summary: string;
  status: string;
  priority: string | null;
  issue_type: string;
  assignee: string | null;
  updated: string;
  url: string;
}

export interface PaginatedTickets {
  items: JiraTicketSummary[];
  total: number;
}

export interface ConfirmOverrides {
  title?: string;
  severity?: Severity;
  issue_type?: string;
  reporting_service_key?: string;
  extra_field_values?: Record<string, string>;
}

export interface ReportingServiceOption {
  key: string;
  label: string;
}

export interface SelectOption {
  id: string;
  value: string;
}

export interface ExtraSelectField {
  field_id: string;
  label: string;
  options: SelectOption[];
}

export interface JiraComment {
  author: string;
  body: string;
  created: string;
}

export interface JiraAttachment {
  id: string;
  filename: string;
  size: number;
  mime_type: string;
  author: string;
  created: string;
  url: string;
}

export interface JiraTicketDetail {
  key: string;
  summary: string;
  description: string;
  status: string;
  priority: string | null;
  issue_type: string;
  assignee: string | null;
  reporter: string | null;
  created: string;
  updated: string;
  url: string;
  comments: JiraComment[];
  attachments: JiraAttachment[];
}

export type ScheduledItemStatus =
  | "pending"
  | "created"
  | "resolved"
  | "create_failed"
  | "resolve_failed"
  | "cancelled";

export interface ScheduledItem {
  id: number;
  created_at: string;
  start_at: string;
  end_at: string | null;
  text: string;
  issue_type: string;
  reporting_service_key: string | null;
  extra_field_values_json: string | null;
  status: ScheduledItemStatus;
  jira_issue_key: string | null;
  classification_json: string | null;
  create_audit_id: number | null;
  resolve_audit_id: number | null;
  error: string | null;
}

export interface TransitionFieldSpec {
  field_id: string;
  label: string;
  type: "string" | "number";
}

export interface TransitionOption {
  id: string;
  name: string;
  to_status: string;
  extra_fields: TransitionFieldSpec[];
}

export interface ApprovalTicket {
  key: string;
  summary: string;
  status: string;
  issue_type: string;
  reporter: string | null;
  updated: string;
  url: string;
  transitions: TransitionOption[];
}

export interface FieldEntry {
  label: string;
  value: string;
}

export interface TicketApprovalDetail {
  key: string;
  summary: string;
  description: string;
  status: string;
  issue_type: string;
  assignee: string | null;
  reporter: string | null;
  created: string;
  updated: string;
  url: string;
  fields: FieldEntry[];
  transitions: TransitionOption[];
  attachments: JiraAttachment[];
}

export type ApprovalRecommendation = "approve" | "reject" | "needs_more_info";

export interface ApprovalSummary {
  overview: string;
  key_details: string[];
  concerns: string[];
  recommendation: ApprovalRecommendation;
  reasoning: string;
}

export interface SheetData {
  name: string;
  headers: string[];
  rows: string[][];
  truncated: boolean;
}

export interface ParsedWorkbook {
  filename: string;
  sheets: SheetData[];
}

export type DiagramNodeRole = "source" | "destination" | "both";
export type DiagramNodeZone = "internal" | "dmz" | "external" | "unknown";
export type DiagramEdgeStatus = "approved" | "rejected" | "pending" | "unknown";

export interface DiagramNode {
  id: string;
  label: string;
  role: DiagramNodeRole;
  zone: DiagramNodeZone;
}

export interface DiagramEdge {
  source_id: string;
  target_id: string;
  label: string;
  status: DiagramEdgeStatus;
  reason: string | null;
}

export interface NetworkDiagram {
  nodes: DiagramNode[];
  edges: DiagramEdge[];
  summary: string;
}

export interface ScheduleCreateRequest {
  start_at: string;
  end_at?: string;
  text: string;
  issue_type: string;
  reporting_service_key?: string;
  extra_field_values?: Record<string, string>;
}
