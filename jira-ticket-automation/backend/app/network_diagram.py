from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from app.config import Settings
from app.llm import get_llm_client
from app.llm.base import StructuredLLMClient

# Network topology data is sensitive, so this defaults to the on-prem model
# (DEFAULT_LLM_PROVIDER=onprem in .env) rather than Anthropic's API. Unlike
# earlier, that's no longer hardcoded here -- get_llm_client() follows
# whichever provider is currently active via /api/settings/llm, so switching
# to Anthropic there (a visible, deliberate action, not a silent default)
# also applies here.
MAX_DIAGRAM_ROWS = 150

# Extracting a graph from dozens of sheet rows under strict JSON-schema
# guided decoding is much slower than the short classification/summary
# prompts this same on-prem model normally serves -- settings.request_timeout_seconds
# (15s by default) was tuned for those, not this, and was measured to time
# out on a real multi-row sheet.
DIAGRAM_LLM_TIMEOUT_SECONDS = 120.0


class NodeRole(str, Enum):
    SOURCE = "source"
    DESTINATION = "destination"
    BOTH = "both"


class NodeZone(str, Enum):
    INTERNAL = "internal"
    DMZ = "dmz"
    EXTERNAL = "external"
    UNKNOWN = "unknown"


class EdgeStatus(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    PENDING = "pending"
    UNKNOWN = "unknown"


class DiagramNode(BaseModel):
    id: str = Field(description="Stable identifier for this system, e.g. its hostname or IP")
    label: str = Field(description="Short display label, e.g. 'web01 (10.0.0.1)'")
    role: NodeRole
    zone: NodeZone = Field(
        description=(
            "Network zone this system sits in, for drawing firewall boundaries between "
            "zones. Use private/RFC1918-range IPs or internal-sounding hostnames as a signal "
            "for 'internal'; explicit DMZ/perimeter mentions for 'dmz'; public IPs, internet, "
            "or named external/third-party systems for 'external'; 'unknown' if it can't be "
            "inferred from the row."
        )
    )


class DiagramEdge(BaseModel):
    source_id: str = Field(description="Must match a node id from the nodes list")
    target_id: str = Field(description="Must match a node id from the nodes list")
    label: str = Field(description="Short connection label, e.g. 'TCP/443 HTTPS' or 'Port 22'")
    status: EdgeStatus
    reason: str | None = Field(
        default=None,
        description=(
            "The row's stated justification/business reason for this access, or its stated "
            "reason for rejection/pending status, taken from a reason/justification/comment "
            "column if the sheet has one. Null if the sheet doesn't state one -- never invent one."
        ),
    )


class NetworkDiagram(BaseModel):
    nodes: list[DiagramNode]
    edges: list[DiagramEdge]
    summary: str = Field(description="1-2 plain-language sentences describing what this sheet grants")


_SYSTEM_PROMPT = """\
You read a network access spreadsheet (column names vary -- source host/IP, \
destination host/IP, port, protocol, service, an approval/status column, and \
a reason/justification column are common but never guaranteed to use those \
exact names) and turn it into a network diagram of who talks to what, drawn \
the way a network engineer would: with realistic firewall zone boundaries, \
not just a flat list of connections.

For each data row, identify:
- The source system: the requester's host/IP/system opening the connection.
- The destination system: the host/IP/system being accessed.
- A short label for the connection (port and/or protocol/service if given).
- A status if the row indicates one (approved/rejected/pending) -- use \
  "unknown" if the row doesn't indicate a status at all.
- A reason: the row's own stated business justification, or its own stated \
  reason for a rejected/pending status, if a reason/justification/comment \
  column exists. Leave it null if the sheet doesn't state one -- never \
  invent a plausible-sounding one.

Then produce:
- nodes: one entry per distinct system mentioned (dedupe the same host/IP \
  across rows), each with a stable id, a short display label, a role, and a \
  zone. Set role to "source" if it never appears as a destination, \
  "destination" if it never appears as a source, or "both" if it does both. \
  Set zone using real network-security judgment: private/RFC1918 IP ranges \
  (10.x, 172.16-31.x, 192.168.x) or internal-sounding hostnames are \
  "internal"; anything explicitly described as DMZ/perimeter/edge is "dmz"; \
  public IPs, internet-facing names, or named external/third-party systems \
  are "external"; use "unknown" only when the row gives no usable signal.
- edges: one entry per source->destination pair (merge duplicate rows for \
  the same pair, combining their labels into one, e.g. "22, 443", and \
  keeping one representative reason if several duplicate rows had one).
- summary: 1-2 plain-language sentences describing what this access sheet \
  grants, for someone who hasn't read the raw sheet.

A connection between two systems in different zones crosses a firewall in \
reality -- get the zone classification right, since that's what the diagram \
will draw a firewall boundary on.

If the sheet's columns don't look like network access data at all (no \
recognizable source/destination information), return empty nodes and edges \
and explain why in summary instead of guessing.\
"""


def _format_sheet(headers: list[str], rows: list[list[str]]) -> str:
    lines = ["Columns: " + " | ".join(headers), ""]
    for row in rows[:MAX_DIAGRAM_ROWS]:
        lines.append(" | ".join(row))
    if len(rows) > MAX_DIAGRAM_ROWS:
        lines.append(f"... ({len(rows) - MAX_DIAGRAM_ROWS} more rows omitted)")
    return "\n".join(lines)


async def generate_network_diagram(
    headers: list[str],
    rows: list[list[str]],
    settings: Settings,
    llm_client: StructuredLLMClient | None = None,
) -> NetworkDiagram:
    owns_client = llm_client is None
    llm_client = llm_client or get_llm_client(settings, timeout=DIAGRAM_LLM_TIMEOUT_SECONDS)
    try:
        return await llm_client.parse(
            system=_SYSTEM_PROMPT,
            user_content=_format_sheet(headers, rows),
            output_model=NetworkDiagram,
        )
    finally:
        if owns_client:
            aclose = getattr(llm_client, "aclose", None)
            if aclose is not None:
                await aclose()
