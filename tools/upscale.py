"""``upscale_image`` MCP tool: upscale an image using Recraft Upscale."""

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


async def upscale_image(
    input_path: Annotated[str, Field(description="Path to the source image, relative to the project root.")],
    output_path: Annotated[
        Optional[str],
        Field(description="Path to save the upscaled result. Defaults to the input path with an '_upscaled' suffix."),
    ] = None,
) -> dict:
    """Upscale an image using Recraft Upscale (image/recraft-upscale)."""
    config = get_config()

    try:
        src = resolve_project_path(input_path, config.project_root)
        if not src.is_file():
            raise FileNotFoundError(f"Input image not found: {src}")

        data_url = file_to_data_uri(src)

        async with NordRouterClient(config) as client:
            result = await client.upscale(image_data_url=data_url)
    except ANTICIPATED as exc:
        raise tool_error(exc) from exc

    out = resolve_project_path(output_path, config.project_root) if output_path else add_suffix(src, "_upscaled")
    p = save_image_bytes(result.data, out, result.content_type)

    return {
        "model": "recraft-upscale",
        "saved": [str(p)],
        "cost": {
            "usd": result.cost_usd,
            "rub": result.cost_rub,
            "gateway_model": result.gateway_model,
        },
    }
