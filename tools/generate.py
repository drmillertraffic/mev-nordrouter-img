"""``generate_image`` MCP tool: generate a new image from a text prompt."""

from typing import Annotated, Optional
from pydantic import Field

from utils.api_client import NordRouterClient
from utils.config import get_config
from utils.errors import ANTICIPATED, tool_error
from utils.image_processor import add_suffix, resolve_project_path, save_image_bytes


async def generate_image(
    prompt: Annotated[str, Field(description="Text description of the image to generate.")],
    output_path: Annotated[
        str,
        Field(description="Path to save the image(s), relative to the project root (e.g. public/images/logo.png)."),
    ],
    model: Annotated[
        str,
        Field(description=(
            "Model family or exact gateway ID. Short names: 'gpt-image-2', 'nano-banana-pro', "
            "'grok', 'qwen3-pro'. The server auto-selects the correct gateway endpoint."
        )),
    ] = "gpt-image-2",
    aspect_ratio: Annotated[
        str,
        Field(description="Aspect ratio for /media models (e.g. '1:1', '16:9', '9:16'). Ignored for v1 models."),
    ] = "1:1",
    resolution: Annotated[
        str,
        Field(description="Resolution tier for /media models ('1k', '2k', '4k'). Ignored for v1 models."),
    ] = "1k",
    size: Annotated[
        Optional[str],
        Field(description="Exact size for v1 models (e.g. '1024x1024'). Ignored for /media models."),
    ] = None,
    count: Annotated[int, Field(description="Number of variants to generate (1-4).", ge=1, le=4)] = 1,
    quality: Annotated[Optional[str], Field(description="Quality hint for v1 models only.")] = None,
) -> dict:
    """Generate images using any supported model family with automatic contour routing."""
    config = get_config()

    try:
        async with NordRouterClient(config) as client:
            results = await client.generate(
                model=model,
                prompt=prompt,
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                size=size,
                quality=quality,
                n=count,
            )
    except ANTICIPATED as exc:
        raise tool_error(exc) from exc

    out_path = resolve_project_path(output_path, config.project_root)
    saved: list[str] = []
    costs: list[dict] = []

    if len(results) == 1 and count == 1:
        p = save_image_bytes(results[0].data, out_path, results[0].content_type)
        saved.append(str(p))
    else:
        for i, res in enumerate(results, start=1):
            p = save_image_bytes(res.data, add_suffix(out_path, f"_v{i}"), res.content_type)
            saved.append(str(p))

    for res in results:
        costs.append({
            "usd": res.cost_usd,
            "rub": res.cost_rub,
            "gateway_model": res.gateway_model,
        })

    return {
        "model": model,
        "saved": saved,
        "cost": costs,
    }
