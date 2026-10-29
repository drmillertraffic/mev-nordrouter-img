"""``batch_generate`` MCP tool: generate with several models at once."""

from typing import Annotated, Optional
import asyncio

from pydantic import Field

from utils.api_client import NordRouterClient
from utils.config import get_config
from utils.errors import tool_error
from utils.image_processor import (
    resolve_project_path,
    sanitize_filename,
    save_image_bytes,
)


async def batch_generate(
    prompt: Annotated[str, Field(description="Text description of the image.")],
    models: Annotated[
        list[str],
        Field(description=(
            "List of model families or gateway IDs to use. Use ONLY when the user explicitly asks to compare models. "
            "For single-model generation, use generate_image with default 'gpt-image-2' instead."
        )),
    ],
    output_dir: Annotated[
        str,
        Field(description=(
            "Directory to save results, relative to NORDROUTER_PROJECT_ROOT "
            "(currently /Users/evmelnik/Documents/aiDev). Include the project subdirectory, e.g. 'Chats/banners/'."
        )),
    ],
    aspect_ratio: Annotated[str, Field(description="Aspect ratio for /media models.")] = "1:1",
    resolution: Annotated[
        str,
        Field(description=(
            "Resolution tier for /media models. DEFAULT: '1k' (web-optimized). "
            "Use '2k' only if user explicitly requests higher quality. Never use '4k' unless explicitly asked."
        )),
    ] = "1k",
    size: Annotated[Optional[str], Field(description="Exact size for v1 models.")] = None,
) -> dict:
    """Generate an image with several models at once and save each result.

    Requests are sent in parallel. Results are saved as ``<output_dir>/<model-name>.<ext>``.
    Returns a mapping of model -> path, costs, and any per-model errors.
    """
    config = get_config()

    async with NordRouterClient(config) as client:
        coros = [
            client.generate(
                model=m,
                prompt=prompt,
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                size=size,
                n=1,
            )
            for m in models
        ]
        batches = await asyncio.gather(*coros, return_exceptions=True)

    out_dir = resolve_project_path(output_dir, config.project_root)
    out_dir.mkdir(parents=True, exist_ok=True)

    results: dict[str, str] = {}
    costs: dict[str, dict] = {}
    errors: dict[str, str] = {}

    for model, batch in zip(models, batches):
        if isinstance(batch, BaseException):
            errors[model] = str(batch) or batch.__class__.__name__
            continue
        if not batch:
            errors[model] = "No image returned"
            continue

        res = batch[0]
        path = save_image_bytes(res.data, out_dir / sanitize_filename(model), res.content_type)
        results[model] = str(path)
        costs[model] = {
            "usd": res.cost_usd,
            "rub": res.cost_rub,
            "gateway_model": res.gateway_model,
        }

    if not results:
        summary = "; ".join(f"{m}: {e}" for m, e in errors.items())
        raise tool_error(
            ValueError(f"No images were generated. {summary or 'Unknown error.'}")
        )

    return {"results": results, "costs": costs, "errors": errors}
