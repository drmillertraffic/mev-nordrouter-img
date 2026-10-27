"""Report tool failures with their own text.

The MCP SDK withholds the message of any exception a tool raises unless it is a
``ToolError``: a crash reaches the client as the bare ``Error executing tool
<name>``. Every failure this server anticipates — an unusable model, a missing
input file, a gateway rejection, a timeout — is converted here, so the calling
agent sees *why* the call failed and can react instead of retrying blindly.
"""

from __future__ import annotations

import httpx
from mcp.server.mcpserver.exceptions import ToolError

from .api_client import NordRouterError

# Failures whose text is both safe and useful to show the client. Anything else
# stays a crash: the SDK logs its traceback and reports a generic message.
ANTICIPATED: tuple[type[BaseException], ...] = (
    ValueError,
    FileNotFoundError,
    NordRouterError,
    RuntimeError,
    httpx.HTTPError,
)


def tool_error(exc: BaseException) -> ToolError:
    """Build a ``ToolError`` carrying a message the client is allowed to read."""
    if isinstance(exc, ToolError):
        return exc

    if isinstance(exc, NordRouterError) and exc.status is not None:
        return ToolError(
            f"NordRouter rejected the request (HTTP {exc.status}, "
            f"code {exc.code or 'unknown'}): {exc}"
        )

    if isinstance(exc, httpx.TimeoutException):
        return ToolError(
            "NordRouter request timed out. Image generation can take a minute or "
            "more; retry, or reduce 'count' / 'quality'."
        )

    return ToolError(str(exc) or exc.__class__.__name__)
