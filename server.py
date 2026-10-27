"""NordRouter image generation MCP server (stdio transport)."""

import logging
import sys

from mcp.server.mcpserver import MCPServer

from tools.batch import batch_generate
from tools.edit import edit_image
from tools.generate import generate_image
from tools.models import list_image_models
from tools.remove_bg import remove_background
from tools.upscale import upscale_image

# MCP reserves stdout for the JSON-RPC protocol, so logs MUST go to stderr.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stderr,
)

mcp = MCPServer(
    name="mev-nordrouter-img",
    title="NordRouter Image Generation",
    description=(
        "Generate and edit images via the NordRouter API using Gemini image models "
        "(chat/completions) and GPT Image 2 (images/generations), with multi-variant "
        "and multi-model batch support."
    ),
    version="1.0.0",
)

# Register the tools. The decorator derives each tool's name/description/schema
# from the function's signature, docstring and Pydantic field metadata.
mcp.tool()(generate_image)
mcp.tool()(edit_image)
mcp.tool()(list_image_models)
mcp.tool()(batch_generate)
mcp.tool()(upscale_image)
mcp.tool()(remove_background)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
