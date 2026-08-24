import { useEffect, useMemo, useRef, useState } from "react";
import { listReportingServices } from "../api";
import type { ReportingServiceOption } from "../types";

interface Props {
  value: string | null;
  onChange: (key: string | null) => void;
  disabled?: boolean;
}

const MAX_VISIBLE = 40;

export function ReportingServiceSelect({ value, onChange, disabled }: Props) {
  const [options, setOptions] = useState<ReportingServiceOption[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const wrapperRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    listReportingServices()
      .then(setOptions)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load reporting services"));
  }, []);

  useEffect(() => {
    if (!value || !options) return;
    const match = options.find((o) => o.key === value);
    if (match) setQuery(match.label);
  }, [value, options]);

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  const filtered = useMemo(() => {
    if (!options) return [];
    const q = query.trim().toLowerCase();
    const matches = q ? options.filter((o) => o.label.toLowerCase().includes(q)) : options;
    return matches.slice(0, MAX_VISIBLE);
  }, [options, query]);

  function select(option: ReportingServiceOption) {
    setQuery(option.label);
    onChange(option.key);
    setOpen(false);
  }

  return (
    <div className="reporting-service-select" ref={wrapperRef}>
      <input
        type="text"
        placeholder={options === null ? "Loading services…" : "Search reporting service…"}
        value={query}
        disabled={disabled || options === null}
        onChange={(e) => {
          setQuery(e.target.value);
          onChange(null);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
      />
      {error && <p className="error-text">{error}</p>}
      {open && options !== null && (
        <ul className="reporting-service-dropdown">
          {filtered.length === 0 && <li className="reporting-service-empty">No matches</li>}
          {filtered.map((o) => (
            <li key={o.key}>
              <button type="button" onClick={() => select(o)}>
                {o.label}
                <span className="reporting-service-key">{o.key}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
