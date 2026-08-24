import { SchedulerPanel } from "../components/SchedulerPanel";

export function SchedulerPage() {
  return (
    <div className="page">
      <header className="page-header">
        <h1>Scheduler</h1>
        <p>
          Plan a day's tickets in advance. Each entry creates automatically at its start time, and
          resolves automatically at its end time if you set one.
        </p>
      </header>
      <SchedulerPanel />
    </div>
  );
}
