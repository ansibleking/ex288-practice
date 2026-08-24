import { ApprovalsPanel } from "../components/ApprovalsPanel";

export function ApprovalsPage() {
  return (
    <div className="page">
      <header className="page-header">
        <h1>Approvals</h1>
        <p>Review AI-assisted summaries and approve or reject requests assigned to you.</p>
      </header>
      <ApprovalsPanel />
    </div>
  );
}
