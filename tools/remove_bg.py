"""``remove_background`` MCP tool: remove background using Recraft Remove Background."""

from typing import Annotated, Optional
from pydantic import Field

from utils.api_client import NordRouterClient
from utils.config import get_config
from utils.errors import ANTICIPATED, tool_error
from utils.image_processor import (
    add_suffix,
    file_to_data_uri,
    resolve_project_path,
    save_image_bytes,
)


async def remove_background(
    input_path: Annotated[str, Field(description="Path to the source image, relative to the project root.")],
    output_path: Annotated[
        Optional[str],
        Field(description="Path to save the result. Defaults to the input path with an '_nobg' suffix."),
    ] = None,
) -> dict:
    """Remove background from an image using Recraft Remove Background (image/recraft-remove-bg)."""
    config = get_config()

    try:
        src = resolve_project_path(input_path, config.project_root)
        if not src.is_file():
            raise FileNotFoundError(f"Input image not found: {src}")

        data_url = file_to_data_uri(src)

        async with NordRouterClient(config) as client:
            result = await client.remove_background(image_data_url=data_url)
    except ANTICIPATED as exc:
        raise tool_error(exc) from exc

    out = resolve_project_path(output_path, config.project_root) if output_path else add_suffix(src, "_nobg")
    p = save_image_bytes(result.data, out, result.content_type)

    return {
        "model": "recraft-remove-bg",
        "saved": [str(p)],
        "cost": {
            "usd": result.cost_usd,
            "rub": result.cost_rub,
            "gateway_model": result.gateway_model,
        },
    }
