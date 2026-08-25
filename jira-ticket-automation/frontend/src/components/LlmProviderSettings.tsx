import { useEffect, useState } from "react";
import { getLlmSettings, setLlmProvider, testLlmProvider } from "../api";
import type { LlmProvider, LlmProviderTestResult, LlmSettings } from "../types";

const PROVIDER_LABEL: Record<LlmProvider, string> = {
  onprem: "On-prem",
  anthropic: "Anthropic",
};

const PROVIDER_DESCRIPTION: Record<LlmProvider, string> = {
  onprem: "Self-hosted model. Data never leaves your network.",
  anthropic: "Anthropic's API. Faster to recover from an on-prem outage, but sheet/ticket content leaves your network.",
};

type TestState = { status: "idle" } | { status: "testing" } | { status: "done"; result: LlmProviderTestResult };

export function LlmProviderSettings() {
  const [settings, setSettings] = useState<LlmSettings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [switching, setSwitching] = useState<LlmProvider | null>(null);
  const [tests, setTests] = useState<Record<LlmProvider, TestState>>({
    onprem: { status: "idle" },
    anthropic: { status: "idle" },
  });

  function load() {
    getLlmSettings()
      .then(setSettings)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load LLM settings"));
  }

  useEffect(load, []);

  async function handleSwitch(provider: LlmProvider) {
    setSwitching(provider);
    setError(null);
    try {
      setSettings(await setLlmProvider(provider));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to switch provider");
    } finally {
      setSwitching(null);
    }
  }

  async function handleResetToDefault() {
    setSwitching(null);
    setError(null);
    try {
      setSettings(await setLlmProvider(null));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to reset provider");
    }
  }

  async function handleTest(provider: LlmProvider) {
    setTests((prev) => ({ ...prev, [provider]: { status: "testing" } }));
    try {
      const result = await testLlmProvider(provider);
      setTests((prev) => ({ ...prev, [provider]: { status: "done", result } }));
    } catch (err) {
      setTests((prev) => ({
        ...prev,
        [provider]: {
          status: "done",
          result: { ok: false, latency_ms: null, error: err instanceof Error ? err.message : "Test failed" },
        },
      }));
    }
  }

  if (error && !settings) return <p className="error-text">{error}</p>;
  if (!settings) return <p className="empty-state">Loading…</p>;

  return (
    <div className="llm-settings">
      {error && <p className="error-text">{error}</p>}

      <div className="llm-provider-grid">
        {(Object.keys(PROVIDER_LABEL) as LlmProvider[]).map((provider) => {
          const isActive = settings.provider === provider;
          const status = settings[provider];
          const test = tests[provider];
          return (
            <div key={provider} className={isActive ? "llm-provider-card active" : "llm-provider-card"}>
              <div className="llm-provider-card-header">
                <h3>{PROVIDER_LABEL[provider]}</h3>
                {isActive && <span className="badge severity-low">Active</span>}
              </div>
              <p className="panel-subtitle">{PROVIDER_DESCRIPTION[provider]}</p>
              <span className={`badge ${status.configured ? "severity-low" : ""}`.trim()}>
                {status.configured ? "Configured" : "Not configured"}
              </span>

              <div className="llm-provider-card-actions">
                <button
                  disabled={isActive || switching === provider || !status.configured}
                  onClick={() => void handleSwitch(provider)}
                >
                  {switching === provider ? "Switching…" : isActive ? "In use" : "Use this provider"}
                </button>
                <button
                  className="sheet-tab"
                  disabled={test.status === "testing" || !status.configured}
                  onClick={() => void handleTest(provider)}
                >
                  {test.status === "testing" ? "Testing…" : "Test connection"}
                </button>
              </div>

              {!status.configured && (
                <p className="empty-state">
                  {provider === "onprem" ? "ONPREM_LLM_BASE_URL" : "ANTHROPIC_API_KEY"} isn't set in .env.
                </p>
              )}

              {test.status === "done" && test.result.ok && (
                <p className="llm-test-result llm-test-ok">✓ Reachable ({test.result.latency_ms} ms)</p>
              )}
              {test.status === "done" && !test.result.ok && (
                <p className="llm-test-result llm-test-fail">✗ {test.result.error}</p>
              )}
            </div>
          );
        })}
      </div>

      <p className="panel-subtitle">
        Default from .env: <strong>{PROVIDER_LABEL[settings.default_provider]}</strong>
        {settings.override_active && " (overridden below)"}
      </p>
      {settings.override_active && (
        <button className="sheet-tab" onClick={() => void handleResetToDefault()}>
          Reset to .env default
        </button>
      )}
    </div>
  );
}
