"""CLI entrypoint for running the Redfish MCP server."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from typing import Any, Literal

from mcp.shared import jsonrpc_dispatcher as jsonrpc_dispatcher_module

from mirastack_redfish_mcp.config import load_config
from mirastack_redfish_mcp.runtime import RedfishRuntime
from mirastack_redfish_mcp.server import create_server

DISCOVERY_ONLY_WARNING = (
    "No Redfish endpoints configured. Serving tool discovery only.\n"
    "Set MIRASTACK_REDFISH_HOST/USERNAME/PASSWORD or provide an endpoints\n"
    "file to enable BMC operations."
)
_STDIO_INLINE_TOOLS_LIST_PATCHED = False


def _install_stdio_inline_tools_list_patch() -> None:
    """Process tools/list inline so piped scanner traffic survives immediate EOF."""
    global _STDIO_INLINE_TOOLS_LIST_PATCHED
    if _STDIO_INLINE_TOOLS_LIST_PATCHED:
        return

    original_init = jsonrpc_dispatcher_module.JSONRPCDispatcher.__init__

    def patched_init(
        self: Any,
        read_stream: Any,
        write_stream: Any,
        *,
        transport_builder: Callable[[Any], Any] | None = None,
        peer_cancel_mode: Literal["interrupt", "signal"] = "interrupt",
        raise_handler_exceptions: bool = False,
        inline_methods: frozenset[str] = frozenset(),
        on_stream_exception: Callable[[Exception], Any] | None = None,
    ) -> None:
        if "initialize" in inline_methods and "tools/list" not in inline_methods:
            inline_methods = frozenset(set(inline_methods) | {"tools/list"})
        original_init(
            self,
            read_stream,
            write_stream,
            transport_builder=transport_builder,
            peer_cancel_mode=peer_cancel_mode,
            raise_handler_exceptions=raise_handler_exceptions,
            inline_methods=inline_methods,
            on_stream_exception=on_stream_exception,
        )

    jsonrpc_dispatcher_module.JSONRPCDispatcher.__init__ = patched_init  # type: ignore[method-assign]
    _STDIO_INLINE_TOOLS_LIST_PATCHED = True


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the MIRASTACK Redfish MCP server.")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http", "sse"),
        default="stdio",
        help="MCP transport",
    )
    parser.add_argument("--host", default=None, help="Host for streamable-http/sse")
    parser.add_argument("--port", type=int, default=None, help="Port for streamable-http/sse")
    parser.add_argument("--path", default=None, help="Path for streamable-http endpoint")
    parser.add_argument(
        "--stateless-http",
        action="store_true",
        default=False,
        help="Enable stateless mode for streamable-http transport",
    )
    parser.add_argument(
        "--json-response",
        action="store_true",
        default=False,
        help="Enable JSON response mode for streamable-http transport",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    config = load_config()
    if not config.endpoints:
        sys.stderr.write(f"{DISCOVERY_ONLY_WARNING}\n")
    if args.host:
        config.streamable_http_host = args.host
    if args.port:
        config.streamable_http_port = args.port
    if args.path:
        config.streamable_http_path = args.path

    runtime = RedfishRuntime(config=config)
    server = create_server(runtime)

    if args.transport == "stdio":
        _install_stdio_inline_tools_list_patch()
        server.run(transport="stdio")
        return 0

    if args.transport == "streamable-http":
        server.run(
            transport="streamable-http",
            host=config.streamable_http_host,
            port=config.streamable_http_port,
            streamable_http_path=config.streamable_http_path,
            stateless_http=args.stateless_http,
            json_response=args.json_response,
        )
        return 0

    server.run(
        transport="sse",
        host=config.streamable_http_host,
        port=config.streamable_http_port,
        sse_path="/sse",
        message_path="/messages",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
