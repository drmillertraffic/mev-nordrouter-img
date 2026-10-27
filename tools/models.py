"""``list_image_models`` MCP tool: list image-capable models with pricing."""

from typing import Annotated, Optional
from pydantic import Field

from utils.config import get_config
from utils.errors import ANTICIPATED, tool_error
from utils.model_families import format_catalog_for_user


async def list_image_models(
    type_filter: Annotated[
        Optional[str],
        Field(description="Optional filter by mode: 'generate', 'edit', 'upscale', 'remove_bg'."),
    ] = None,
    available_only: Annotated[
        bool,
        Field(description="Ignored for backwards compatibility; all listed models are available."),
    ] = True,
) -> dict:
    """Return curated image models with USD and RUB pricing per generation.

    Returns clean model families ('gpt-image-2', 'nano-banana-pro', 'grok', 'qwen3-pro',
    'recraft-upscale', 'recraft-remove-bg'). The server automatically picks the right
    gateway model ID and mode (t2i vs i2i) when you call generate_image or edit_image.
    """
    try:
        config = get_config()
        catalog = format_catalog_for_user(usd_rub_rate=config.usd_rub)
        if type_filter:
            catalog = [m for m in catalog if type_filter in m["modes"]]
        return {
            "usd_rub_rate": config.usd_rub,
            "models": catalog,
        }
    except ANTICIPATED as exc:
        raise tool_error(exc) from exc
