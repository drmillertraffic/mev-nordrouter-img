"""``edit_image`` MCP tool: edit an existing image in the project."""

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


async def edit_image(
    input_path: Annotated[
        str,
        Field(description="Path to the source image, relative to the project root."),
    ],
    prompt: Annotated[str, Field(description="Editing instruction describing the desired change.")],
    output_path: Annotated[
        Optional[str],
        Field(description="Path to save the result. Defaults to the input path with an '_edited' suffix."),
    ] = None,
    model: Annotated[
        str,
        Field(description=(
            "Model family or exact gateway ID for editing. Short names: 'gpt-image-2', "
            "'nano-banana-pro', 'grok', 'qwen3-pro'. The server auto-selects the correct i2i endpoint."
        )),
    ] = "gpt-image-2",
    aspect_ratio: Annotated[
        str,
        Field(description="Aspect ratio for /media models (e.g. '1:1', '16:9'). Ignored for v1 models."),
    ] = "1:1",
    resolution: Annotated[
        str,
        Field(description="Resolution tier for /media models ('1k', '2k', '4k'). Ignored for v1 models."),
    ] = "1k",
) -> dict:
    """Edit an existing image using any supported model family with automatic contour routing."""
    config = get_config()

    try:
        src = resolve_project_path(input_path, config.project_root)
        if not src.is_file():
            raise FileNotFoundError(f"Input image not found: {src}")

        data_url = file_to_data_uri(src)

        async with NordRouterClient(config) as client:
            result = await client.edit(
                model=model,
                prompt=prompt,
                image_data_url=data_url,
                aspect_ratio=aspect_ratio,
                resolution=resolution,
            )
    except ANTICIPATED as exc:
        raise tool_error(exc) from exc

    out = resolve_project_path(output_path, config.project_root) if output_path else add_suffix(src, "_edited")
    p = save_image_bytes(result.data, out, result.content_type)

    return {
        "model": model,
        "saved": [str(p)],
        "cost": {
            "usd": result.cost_usd,
            "rub": result.cost_rub,
            "gateway_model": result.gateway_model,
        },
    }
