import { useEffect, useRef, useState } from "react";
import { generateNetworkDiagram } from "../api";
import type { DiagramEdge, DiagramEdgeStatus, DiagramNodeZone, NetworkDiagram } from "../types";

const STATUS_COLOR: Record<DiagramEdgeStatus, string> = {
  approved: "var(--severity-low)",
  rejected: "var(--severity-critical)",
  pending: "var(--severity-medium)",
  unknown: "var(--muted)",
};

const STATUS_BADGE_CLASS: Record<DiagramEdgeStatus, string> = {
  approved: "severity-low",
  rejected: "severity-critical",
  pending: "severity-medium",
  unknown: "",
};

// Deliberately distinct from STATUS_COLOR (no green/amber/red) so a node's
// zone ring is never mistaken for an approval/rejection signal.
const ZONE_COLOR: Record<DiagramNodeZone, string> = {
  internal: "var(--accent)",
  dmz: "var(--chart-4)",
  external: "var(--chart-3)",
  unknown: "var(--muted)",
};

const ZONE_LABEL: Record<DiagramNodeZone, string> = {
  internal: "Internal",
  dmz: "DMZ",
  external: "External",
  unknown: "Unknown zone",
};

const ROW_HEIGHT = 46;
const PADDING = 24;
const WIDTH = 820;
const COLUMN_MARGIN = 170;
const MIN_ZOOM = 0.4;
const MAX_ZOOM = 2.4;
const ZOOM_STEP = 0.2;
const DIMMED_OPACITY = 0.1;
const DIMMED_NODE_OPACITY = 0.3;

function truncateLabel(label: string, max = 24): string {
  return label.length > max ? `${label.slice(0, max - 1)}…` : label;
}

function portTokens(label: string): string[] {
  return label
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);
}

// One pass of barycenter ordering: place each right-side node near the
// average position of the left-side nodes it connects to, then do the same
// for the left side against the newly-ordered right side. A bipartite
// diagram with many connections is unreadable if node order is arbitrary --
// this doesn't eliminate every line crossing, but it untangles most of them
// without needing a full graph-layout library.
function barycenterOrder(ids: string[], neighbors: Map<string, string[]>, otherIndex: Map<string, number>): string[] {
  const scored = ids.map((id) => {
    const positions = (neighbors.get(id) ?? [])
      .map((n) => otherIndex.get(n))
      .filter((p): p is number => p !== undefined);
    const score = positions.length > 0 ? positions.reduce((a, b) => a + b, 0) / positions.length : Infinity;
    return { id, score };
  });
  scored.sort((a, b) => a.score - b.score);
  return scored.map((s) => s.id);
}

function layoutDiagram(diagram: NetworkDiagram) {
  let leftIds = diagram.nodes.filter((n) => n.role === "source" || n.role === "both").map((n) => n.id);
  let rightIds = diagram.nodes.filter((n) => n.role === "destination" || n.role === "both").map((n) => n.id);

  const sourcesOf = new Map<string, string[]>();
  const targetsOf = new Map<string, string[]>();
  for (const e of diagram.edges) {
    if (!targetsOf.has(e.source_id)) targetsOf.set(e.source_id, []);
    targetsOf.get(e.source_id)!.push(e.target_id);
    if (!sourcesOf.has(e.target_id)) sourcesOf.set(e.target_id, []);
    sourcesOf.get(e.target_id)!.push(e.source_id);
  }
  const initialLeftIndex = new Map(leftIds.map((id, i) => [id, i]));
  rightIds = barycenterOrder(rightIds, sourcesOf, initialLeftIndex);
  const rightIndex = new Map(rightIds.map((id, i) => [id, i]));
  leftIds = barycenterOrder(leftIds, targetsOf, rightIndex);

  const height = Math.max(leftIds.length, rightIds.length, 1) * ROW_HEIGHT + PADDING * 2;
  const leftX = COLUMN_MARGIN;
  const rightX = WIDTH - COLUMN_MARGIN;
  const leftPos = new Map(leftIds.map((id, i) => [id, PADDING + i * ROW_HEIGHT + ROW_HEIGHT / 2] as const));
  const rightPos = new Map(rightIds.map((id, i) => [id, PADDING + i * ROW_HEIGHT + ROW_HEIGHT / 2] as const));
  return { leftIds, rightIds, leftX, rightX, leftPos, rightPos, height };
}

// A connection crossing between two known, different zones crosses a
// firewall in reality -- "unknown" on either side isn't treated as a
// crossing since we don't actually have the evidence for one.
function crossesFirewall(edge: DiagramEdge, zoneById: Map<string, DiagramNodeZone>): boolean {
  const sz = zoneById.get(edge.source_id) ?? "unknown";
  const tz = zoneById.get(edge.target_id) ?? "unknown";
  return sz !== tz && sz !== "unknown" && tz !== "unknown";
}

// The live SVG inherits theme colors from the page's stylesheet via
// var(--token), but a downloaded file has no stylesheet at all -- without
// this, an exported diagram opened outside the app would render with
// missing/black strokes instead of the colors shown on screen.
function bakeInCssVars(svgMarkup: string): string {
  const styles = getComputedStyle(document.documentElement);
  return svgMarkup.replace(/var\((--[a-zA-Z0-9-]+)\)/g, (_, name: string) => {
    const resolved = styles.getPropertyValue(name).trim();
    return resolved || "#888888";
  });
}

function serializeExportableSvg(svg: SVGSVGElement): string {
  let markup = new XMLSerializer().serializeToString(svg);
  if (!markup.includes("xmlns=")) {
    markup = markup.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"');
  }
  return bakeInCssVars(markup);
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

type Selection = { type: "edge"; index: number } | { type: "node"; id: string } | null;

interface Props {
  headers: string[];
  rows: string[][];
}

export function NetworkDiagramView({ headers, rows }: Props) {
  const [diagram, setDiagram] = useState<NetworkDiagram | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [zoom, setZoom] = useState(1);
  const [animate, setAnimate] = useState(true);
  const [selected, setSelected] = useState<Selection>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  useEffect(() => {
    if (!diagram || diagram.nodes.length === 0) return;
    const { height } = layoutDiagram(diagram);
    // Large diagrams (many nodes) start zoomed out enough to see the whole
    // shape at once; small ones start at 100%. The zoom controls take over
    // from there.
    const fit = Math.min(1, 620 / height);
    setZoom(Math.max(MIN_ZOOM, Math.round(fit * 10) / 10));
    setSelected(null);
  }, [diagram]);

  async function handleGenerate() {
    setLoading(true);
    setError(null);
    try {
      setDiagram(await generateNetworkDiagram(headers, rows));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to generate the diagram");
    } finally {
      setLoading(false);
    }
  }

  function handleDownloadSvg() {
    if (!svgRef.current) return;
    const markup = serializeExportableSvg(svgRef.current);
    downloadBlob(new Blob([markup], { type: "image/svg+xml" }), "network-diagram.svg");
  }

  async function handleDownloadPng() {
    if (!svgRef.current || !diagram) return;
    const { height } = layoutDiagram(diagram);
    const markup = serializeExportableSvg(svgRef.current);
    const scale = 2;
    const svgUrl = URL.createObjectURL(new Blob([markup], { type: "image/svg+xml;charset=utf-8" }));
    try {
      const image = new Image();
      await new Promise<void>((resolve, reject) => {
        image.onload = () => resolve();
        image.onerror = () => reject(new Error("Could not render the diagram to an image"));
        image.src = svgUrl;
      });
      const canvas = document.createElement("canvas");
      canvas.width = WIDTH * scale;
      canvas.height = height * scale;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      const bg = getComputedStyle(document.documentElement).getPropertyValue("--surface").trim() || "#ffffff";
      ctx.fillStyle = bg;
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
      canvas.toBlob((blob) => {
        if (blob) downloadBlob(blob, "network-diagram.png");
      }, "image/png");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to export the diagram as an image");
    } finally {
      URL.revokeObjectURL(svgUrl);
    }
  }

  if (!diagram) {
    return (
      <div className="network-diagram-empty">
        <p className="empty-state">
          Ask the on-prem model to read {rows.length} row{rows.length === 1 ? "" : "s"} of this sheet and draw
          who connects to what, including firewall zones and traffic direction.
        </p>
        {error && <p className="error-text">{error}</p>}
        <button disabled={loading || rows.length === 0} onClick={() => void handleGenerate()}>
          {loading ? "Reading the sheet…" : "Generate network diagram"}
        </button>
      </div>
    );
  }

  if (diagram.nodes.length === 0) {
    return (
      <div className="network-diagram-empty">
        <p className="empty-state">{diagram.summary}</p>
        <button onClick={() => setDiagram(null)}>Try again</button>
      </div>
    );
  }

  const { leftIds, rightIds, leftX, rightX, leftPos, rightPos, height } = layoutDiagram(diagram);
  const labelById = new Map(diagram.nodes.map((n) => [n.id, n.label]));
  const zoneById = new Map(diagram.nodes.map((n) => [n.id, n.zone]));
  const midX = (leftX + rightX) / 2;

  function edgeOpacity(i: number, edge: DiagramEdge): number {
    if (!selected) return 0.78;
    if (selected.type === "edge") return selected.index === i ? 0.95 : DIMMED_OPACITY;
    return edge.source_id === selected.id || edge.target_id === selected.id ? 0.9 : DIMMED_OPACITY;
  }

  function nodeOpacity(id: string): number {
    if (!selected) return 1;
    if (selected.type === "node") {
      if (id === selected.id) return 1;
      const connected = diagram!.edges.some(
        (e) =>
          (e.source_id === selected.id && e.target_id === id) || (e.target_id === selected.id && e.source_id === id)
      );
      return connected ? 1 : DIMMED_NODE_OPACITY;
    }
    const edge = diagram!.edges[selected.index];
    return id === edge.source_id || id === edge.target_id ? 1 : DIMMED_NODE_OPACITY;
  }

  function selectEdge(i: number) {
    setSelected((s) => (s?.type === "edge" && s.index === i ? null : { type: "edge", index: i }));
  }

  function selectNode(id: string) {
    setSelected((s) => (s?.type === "node" && s.id === id ? null : { type: "node", id }));
  }

  const selectedEdge = selected?.type === "edge" ? diagram.edges[selected.index] : null;
  const selectedNode = selected?.type === "node" ? diagram.nodes.find((n) => n.id === selected.id) ?? null : null;
  const selectedNodeConnections =
    selected?.type === "node" ? diagram.edges.filter((e) => e.source_id === selected.id || e.target_id === selected.id) : [];

  return (
    <div className="network-diagram">
      <div className="network-diagram-header">
        <p className="panel-subtitle">{diagram.summary}</p>
        <button className="attachment-upload-button" disabled={loading} onClick={() => void handleGenerate()}>
          {loading ? "Regenerating…" : "Regenerate"}
        </button>
      </div>

      {error && <p className="error-text">{error}</p>}

      <div className="network-diagram-toolbar">
        <div className="network-diagram-legends">
          <div className="network-diagram-legend">
            {(Object.keys(STATUS_COLOR) as DiagramEdgeStatus[]).map((s) => (
              <span key={s} className="network-diagram-legend-item">
                <span className="network-diagram-swatch" style={{ background: STATUS_COLOR[s] }} />
                {s}
              </span>
            ))}
          </div>
          <div className="network-diagram-legend">
            {(Object.keys(ZONE_COLOR) as DiagramNodeZone[]).map((z) => (
              <span key={z} className="network-diagram-legend-item">
                <span className="network-diagram-swatch network-diagram-swatch-ring" style={{ borderColor: ZONE_COLOR[z] }} />
                {ZONE_LABEL[z]}
              </span>
            ))}
            <span className="network-diagram-legend-item">
              <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true">
                <use href="#firewall-icon" />
              </svg>
              Firewall boundary
            </span>
          </div>
        </div>

        <div className="network-diagram-controls">
          <button className={animate ? "sheet-tab active" : "sheet-tab"} onClick={() => setAnimate((a) => !a)}>
            {animate ? "Traffic animation: On" : "Traffic animation: Off"}
          </button>
          <div className="network-diagram-zoom" role="group" aria-label="Zoom">
            <button
              className="sheet-tab"
              onClick={() => setZoom((z) => Math.max(MIN_ZOOM, Math.round((z - ZOOM_STEP) * 10) / 10))}
              disabled={zoom <= MIN_ZOOM}
              aria-label="Zoom out"
            >
              −
            </button>
            <span className="network-diagram-zoom-level">{Math.round(zoom * 100)}%</span>
            <button
              className="sheet-tab"
              onClick={() => setZoom((z) => Math.min(MAX_ZOOM, Math.round((z + ZOOM_STEP) * 10) / 10))}
              disabled={zoom >= MAX_ZOOM}
              aria-label="Zoom in"
            >
              +
            </button>
          </div>
          <button className="sheet-tab" onClick={handleDownloadPng}>
            Download PNG
          </button>
          <button className="sheet-tab" onClick={handleDownloadSvg}>
            Download SVG
          </button>
        </div>
      </div>

      <div className="network-diagram-body">
        <div className="network-diagram-canvas">
          <svg
            ref={svgRef}
            viewBox={`0 0 ${WIDTH} ${height}`}
            width={WIDTH * zoom}
            height={height * zoom}
            role="img"
            aria-label="Network access diagram"
          >
            <defs>
              {(Object.keys(STATUS_COLOR) as DiagramEdgeStatus[]).map((s) => (
                <marker key={s} id={`arrow-${s}`} viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                  <path d="M0,0 L10,5 L0,10 z" fill={STATUS_COLOR[s]} />
                </marker>
              ))}
              <symbol id="firewall-icon" viewBox="0 0 16 16">
                <rect x="0.5" y="0.5" width="15" height="15" rx="2" fill="var(--surface)" stroke="var(--fg)" strokeWidth="1" />
                <path
                  d="M0.5 5.5H15.5 M0.5 10.5H15.5 M5.5 0.5V5.5 M10.5 0.5V5.5 M2.8 5.5V10.5 M8 5.5V10.5 M13.2 5.5V10.5 M5.5 10.5V15.5 M10.5 10.5V15.5"
                  stroke="var(--fg)"
                  strokeWidth="0.9"
                />
              </symbol>
            </defs>

            <rect x={0} y={0} width={WIDTH} height={height} fill="var(--surface)" onClick={() => setSelected(null)} />

            {diagram.edges.map((edge, i) => {
              const sy = leftPos.get(edge.source_id);
              const ty = rightPos.get(edge.target_id);
              if (sy === undefined || ty === undefined) return null;
              const path = `M ${leftX} ${sy} C ${midX} ${sy}, ${midX} ${ty}, ${rightX} ${ty}`;
              const labelY = (sy + ty) / 2;
              const hasFirewall = crossesFirewall(edge, zoneById);
              const contentY = hasFirewall ? labelY + 15 : labelY;
              const tokens = portTokens(edge.label);
              const portText = tokens.length > 1 ? `${tokens.length} ports` : edge.label;
              const opacity = edgeOpacity(i, edge);
              return (
                <g key={i} style={{ cursor: "pointer" }} onClick={() => selectEdge(i)}>
                  <path d={path} fill="none" stroke="transparent" strokeWidth={10} />
                  <path
                    d={path}
                    fill="none"
                    stroke={STATUS_COLOR[edge.status]}
                    strokeWidth={selected?.type === "edge" && selected.index === i ? 2.6 : 1.6}
                    opacity={opacity}
                    markerEnd={`url(#arrow-${edge.status})`}
                  >
                    <title>{`${labelById.get(edge.source_id) ?? edge.source_id} → ${labelById.get(edge.target_id) ?? edge.target_id}: ${edge.label} (${edge.status})${edge.reason ? ` — ${edge.reason}` : ""}`}</title>
                  </path>
                  {animate && (
                    <path
                      d={path}
                      className="network-diagram-flow-line"
                      fill="none"
                      stroke={STATUS_COLOR[edge.status]}
                      strokeWidth={2.2}
                      opacity={opacity > DIMMED_OPACITY ? 1 : 0}
                    />
                  )}
                  {hasFirewall && <use href="#firewall-icon" x={midX - 8} y={labelY - 8} width={16} height={16} opacity={opacity} />}
                  <text
                    x={midX}
                    y={contentY}
                    textAnchor="middle"
                    fontSize={10.5}
                    fill="var(--fg)"
                    stroke="var(--surface)"
                    strokeWidth={4}
                    strokeLinejoin="round"
                    paintOrder="stroke"
                    opacity={opacity}
                  >
                    {truncateLabel(portText, 20)}
                  </text>
                </g>
              );
            })}

            {leftIds.map((id) => {
              const y = leftPos.get(id)!;
              const label = labelById.get(id) ?? id;
              const zone = zoneById.get(id) ?? "unknown";
              return (
                <g key={`l-${id}`} style={{ cursor: "pointer" }} onClick={() => selectNode(id)} opacity={nodeOpacity(id)}>
                  <circle cx={leftX} cy={y} r={9} fill="transparent" />
                  <circle cx={leftX} cy={y} r={5} fill={ZONE_COLOR[zone]} />
                  <text x={leftX - 12} y={y} textAnchor="end" dominantBaseline="middle" fontSize={12} fill="var(--fg)">
                    {truncateLabel(label)}
                    <title>{`${label} (${ZONE_LABEL[zone]})`}</title>
                  </text>
                </g>
              );
            })}
            {rightIds.map((id) => {
              const y = rightPos.get(id)!;
              const label = labelById.get(id) ?? id;
              const zone = zoneById.get(id) ?? "unknown";
              return (
                <g key={`r-${id}`} style={{ cursor: "pointer" }} onClick={() => selectNode(id)} opacity={nodeOpacity(id)}>
                  <circle cx={rightX} cy={y} r={9} fill="transparent" />
                  <circle cx={rightX} cy={y} r={5} fill={ZONE_COLOR[zone]} />
                  <text x={rightX + 12} y={y} textAnchor="start" dominantBaseline="middle" fontSize={12} fill="var(--fg)">
                    {truncateLabel(label)}
                    <title>{`${label} (${ZONE_LABEL[zone]})`}</title>
                  </text>
                </g>
              );
            })}
          </svg>
        </div>

        <div className="network-diagram-details">
          {!selected && (
            <p className="empty-state">Click a system or connection in the diagram to see its full details here.</p>
          )}

          {selectedEdge && (
            <div className="network-diagram-detail-card">
              <div className="network-diagram-detail-header">
                <strong>{labelById.get(selectedEdge.source_id) ?? selectedEdge.source_id}</strong>
                <span className="network-diagram-detail-arrow">→</span>
                <strong>{labelById.get(selectedEdge.target_id) ?? selectedEdge.target_id}</strong>
              </div>
              <span className={`badge ${STATUS_BADGE_CLASS[selectedEdge.status]}`.trim()}>{selectedEdge.status}</span>
              <div className="network-diagram-detail-chips">
                {portTokens(selectedEdge.label).map((p, i) => (
                  <span key={i} className="network-diagram-chip">
                    {p}
                  </span>
                ))}
              </div>
              {selectedEdge.reason && <p className="network-diagram-detail-reason">{selectedEdge.reason}</p>}
              {!selectedEdge.reason && <p className="empty-state">No reason stated in the sheet for this connection.</p>}
            </div>
          )}

          {selectedNode && (
            <div className="network-diagram-detail-card">
              <div className="network-diagram-detail-header">
                <strong>{selectedNode.label}</strong>
                <span className="badge">{ZONE_LABEL[selectedNode.zone]}</span>
              </div>
              <p className="panel-subtitle network-diagram-detail-subtitle">
                {selectedNodeConnections.length} connection{selectedNodeConnections.length === 1 ? "" : "s"}
              </p>
              <ul className="network-diagram-detail-list">
                {selectedNodeConnections.map((e, i) => {
                  const isSource = e.source_id === selectedNode.id;
                  const otherId = isSource ? e.target_id : e.source_id;
                  const otherLabel = labelById.get(otherId) ?? otherId;
                  return (
                    <li key={i}>
                      <span className="network-diagram-status-dot" style={{ background: STATUS_COLOR[e.status] }} />
                      <span>
                        {isSource ? "→" : "←"} {otherLabel}
                      </span>
                      <span className="network-diagram-detail-list-meta">{e.label}</span>
                    </li>
                  );
                })}
              </ul>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
