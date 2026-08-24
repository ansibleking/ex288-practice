import { MyTicketsPanel } from "../components/MyTicketsPanel";

export function MyTicketsPage() {
  return (
    <div className="page">
      <header className="page-header">
        <h1>My Tickets</h1>
        <p>Tickets assigned to or reported by your Jira account.</p>
      </header>
      <MyTicketsPanel />
    </div>
  );
}
