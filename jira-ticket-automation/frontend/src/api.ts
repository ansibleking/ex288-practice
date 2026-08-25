import type {
  ApprovalSummary,
  ApprovalTicket,
  AuditRow,
  CandidateTicket,
  ConfirmOverrides,
  ExtraSelectField,
  FeedResponse,
  JiraTicketDetail,
  LlmProvider,
  LlmProviderTestResult,
  LlmSettings,
  NetworkDiagram,
  PaginatedTickets,
  ParsedWorkbook,
  ReportingServiceOption,
  ScheduleCreateRequest,
  ScheduledItem,
  TicketApprovalDetail,
} from "./types";

export interface HealthStatus {
  llm_provider: string;
  llm_model: string;
  llm_configured: boolean;
  reporting_service_configured: boolean;
  jira_reachable: boolean;
  jira_user?: string;
  jira_error?: string;
}

class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, init);
  if (!response.ok) {
    const text = await response.text();
    // FastAPI error bodies are JSON ({"detail": "..."}) -- surface the plain
    // detail string instead of dumping the raw JSON (which itself often
    // wraps a nested Jira error blob) in front of the user.
    let message = text || response.statusText;
    try {
      const parsed = JSON.parse(text);
      if (typeof parsed?.detail === "string") message = parsed.detail;
    } catch {
      // Not JSON -- use the raw text as-is.
    }
    throw new ApiError(message, response.status);
  }
  return response.json() as Promise<T>;
}

export function submitFeedText(
  text: string,
  source: "chat" | "paste",
  issueType?: string,
  reportingServiceKey?: string,
  extraFieldValues?: Record<string, string>,
): Promise<FeedResponse> {
  return request<FeedResponse>("/feed", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      text,
      source,
      issue_type: issueType,
      reporting_service_key: reportingServiceKey,
      extra_field_values: extraFieldValues ?? {},
    }),
  });
}

export function submitFeedFile(
  file: File,
  issueType?: string,
  reportingServiceKey?: string,
  extraFieldValues?: Record<string, string>,
): Promise<FeedResponse> {
  const formData = new FormData();
  formData.append("file", file);
  if (issueType) formData.append("issue_type", issueType);
  if (reportingServiceKey) formData.append("reporting_service_key", reportingServiceKey);
  if (extraFieldValues && Object.keys(extraFieldValues).length > 0) {
    formData.append("extra_field_values", JSON.stringify(extraFieldValues));
  }
  return request<FeedResponse>("/feed/file", { method: "POST", body: formData });
}

export function confirmPending(auditId: number, overrides?: ConfirmOverrides): Promise<FeedResponse> {
  return request<FeedResponse>(`/pending/${auditId}/confirm`, {
    method: "POST",
    headers: overrides ? { "Content-Type": "application/json" } : undefined,
    body: overrides ? JSON.stringify(overrides) : undefined,
  });
}

export function cancelPending(auditId: number): Promise<AuditRow> {
  return request<AuditRow>(`/pending/${auditId}/cancel`, { method: "POST" });
}

export function listPending(): Promise<AuditRow[]> {
  return request<AuditRow[]>("/pending");
}

export function listAudit(limit = 50, offset = 0, status?: string): Promise<AuditRow[]> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (status) params.set("status", status);
  return request<AuditRow[]>(`/audit?${params.toString()}`);
}

export function listManagedTickets(): Promise<CandidateTicket[]> {
  return request<CandidateTicket[]>("/tickets/managed");
}

export interface MyTicketsFilters {
  startDate?: string;
  endDate?: string;
  limit?: number;
  offset?: number;
}

export function listMyTickets(filters: MyTicketsFilters = {}): Promise<PaginatedTickets> {
  const params = new URLSearchParams();
  if (filters.startDate) params.set("start_date", filters.startDate);
  if (filters.endDate) params.set("end_date", filters.endDate);
  params.set("limit", String(filters.limit ?? 20));
  params.set("offset", String(filters.offset ?? 0));
  return request<PaginatedTickets>(`/tickets/mine?${params.toString()}`);
}

export function getTicketDetail(key: string): Promise<JiraTicketDetail> {
  return request<JiraTicketDetail>(`/tickets/${encodeURIComponent(key)}`);
}

export function uploadAttachment(key: string, file: File): Promise<JiraTicketDetail> {
  const formData = new FormData();
  formData.append("file", file);
  return request<JiraTicketDetail>(`/tickets/${encodeURIComponent(key)}/attachments`, {
    method: "POST",
    body: formData,
  });
}

export function listIssueTypes(): Promise<string[]> {
  return request<string[]>("/tickets/issue-types");
}

export function parseSheet(file: File): Promise<ParsedWorkbook> {
  const formData = new FormData();
  formData.append("file", file);
  return request<ParsedWorkbook>("/sheets/parse", {
    method: "POST",
    body: formData,
  });
}

export function generateNetworkDiagram(headers: string[], rows: string[][]): Promise<NetworkDiagram> {
  return request<NetworkDiagram>("/sheets/diagram", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ headers, rows }),
  });
}

export function getLlmSettings(): Promise<LlmSettings> {
  return request<LlmSettings>("/settings/llm");
}

export function setLlmProvider(provider: LlmProvider | null): Promise<LlmSettings> {
  return request<LlmSettings>("/settings/llm", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ provider }),
  });
}

export function testLlmProvider(provider: LlmProvider): Promise<LlmProviderTestResult> {
  return request<LlmProviderTestResult>("/settings/llm/test", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ provider }),
  });
}

export function createScheduledItem(body: ScheduleCreateRequest): Promise<ScheduledItem> {
  return request<ScheduledItem>("/schedule", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function listSchedule(startIso: string, endIso: string): Promise<ScheduledItem[]> {
  const params = new URLSearchParams({ start: startIso, end: endIso });
  return request<ScheduledItem[]>(`/schedule?${params.toString()}`);
}

export function cancelScheduledItem(id: number): Promise<ScheduledItem> {
  return request<ScheduledItem>(`/schedule/${id}/cancel`, { method: "POST" });
}

export function listReportingServices(q?: string): Promise<ReportingServiceOption[]> {
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  const qs = params.toString();
  return request<ReportingServiceOption[]>(`/tickets/reporting-services${qs ? `?${qs}` : ""}`);
}

export function getHealth(): Promise<HealthStatus> {
  return request<HealthStatus>("/health");
}

export function listExtraSelectFields(): Promise<ExtraSelectField[]> {
  return request<ExtraSelectField[]>("/tickets/extra-select-fields");
}

export function listApprovals(): Promise<ApprovalTicket[]> {
  return request<ApprovalTicket[]>("/approvals");
}

export function getApprovalDetail(key: string): Promise<TicketApprovalDetail> {
  return request<TicketApprovalDetail>(`/approvals/${encodeURIComponent(key)}`);
}

export function getApprovalSummary(key: string): Promise<ApprovalSummary> {
  return request<ApprovalSummary>(`/approvals/${encodeURIComponent(key)}/summary`);
}

export function transitionApproval(
  key: string,
  transitionId: string,
  comment?: string,
  extraFieldValues?: Record<string, string | number>,
): Promise<TicketApprovalDetail> {
  return request<TicketApprovalDetail>(`/approvals/${encodeURIComponent(key)}/transition`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      transition_id: transitionId,
      comment: comment || undefined,
      extra_field_values: extraFieldValues && Object.keys(extraFieldValues).length > 0 ? extraFieldValues : undefined,
    }),
  });
}

export { ApiError };
