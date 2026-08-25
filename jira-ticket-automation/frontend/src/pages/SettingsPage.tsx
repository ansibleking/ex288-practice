import { LlmProviderSettings } from "../components/LlmProviderSettings";

export function SettingsPage() {
  return (
    <div className="page">
      <header className="page-header">
        <h1>Settings</h1>
        <p>Switch which LLM powers classification, approvals, and the sheet visualizer — takes effect immediately, no restart.</p>
      </header>
      <div className="card">
        <LlmProviderSettings />
      </div>
    </div>
  );
}
