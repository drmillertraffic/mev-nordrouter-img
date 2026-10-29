"""Asynchronous HTTP client for the NordRouter image endpoints.

Supports two gateway contours:
1. '/v1' — OpenAI-compatible endpoints (/v1/images/generations, /v1/chat/completions).
2. '/media' — NordRouter media pipeline (/media/upload, /media/generate, /media/job/<id>).
"""

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse
import asyncio
import base64
import logging
import re

import httpx

from .config import Config
from .model_families import resolve_model, ResolvedModel

logger = logging.getLogger(__name__)

_MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\((https?://[^\s)]+)\)")
_DATA_URI_RE = re.compile(r"data:(?P<mime>[^;,]+);base64,(?P<b64>[A-Za-z0-9+/=\s]+)")


@dataclass
class ImageResult:
    """A single generated or edited image returned by the API."""

    data: bytes
    content_type: str
    source: str  # "url" or "b64"
    cost_usd: float | None = None
    cost_rub: float | None = None
    gateway_model: str = ""


class NordRouterError(RuntimeError):
    """An error response from the NordRouter API."""

    def __init__(
        self, message: str, status: int | None = None, code: str | None = None
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


def _raw_image_urls(text: str) -> list[str]:
    urls: list[str] = []
    for token in re.findall(r"https?://[^\s\"'<>]+", text):
        clean = token.rstrip(").,;:!?")
        path = urlparse(clean).path.lower()
        if any(path.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif")) or "/media/file/" in clean:
            urls.append(clean)
    return urls


class NordRouterClient:
    """Async client handling both /v1 and /media contours."""

    def __init__(self, config: Config) -> None:
        self._config = config
        base = config.base_url.rstrip("/")
        if base.endswith("/v1"):
            self._host = base[:-3].rstrip("/")
            self._v1_base = base
        else:
            self._host = base
            self._v1_base = f"{base}/v1"
        self._media_base = f"{self._host}/media"

        self._client = httpx.AsyncClient(
            timeout=config.timeout,
            headers={"Authorization": f"Bearer {config.api_key}"},
        )

    async def __aenter__(self) -> "NordRouterClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self._client.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    # -- media contour helpers --------------------------------------------
    async def upload_media_image(self, data_url: str) -> str:
        """Upload a data URL (data:image/...;base64,...) to /media/upload.

        Returns the public gateway URL (e.g. https://nordrouter.net/media/file/up-...?raw=1).
        """
        url = f"{self._media_base}/upload"
        logger.info("POST %s (uploading %d chars)", url, len(data_url))
        try:
            resp = await self._client.post(
                url,
                json={"data": data_url},
                headers={"Content-Type": "application/json"},
            )
        except httpx.TimeoutException as exc:
            raise RuntimeError(f"Timed out after {self._config.timeout}s uploading image") from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"HTTP error uploading image: {exc}") from exc

        if resp.status_code >= 400:
            raise NordRouterError(
                f"Image upload failed ({resp.status_code}): {resp.text[:500]}",
                status=resp.status_code,
            )

        data = resp.json()
        file_url = data.get("url")
        if not file_url:
            raise RuntimeError(f"Upload response missing 'url': {data}")
        return file_url

    async def _media_job(self, model_id: str, input_payload: dict[str, Any]) -> ImageResult:
        """Submit a job to /media/generate and poll until done."""
        gen_url = f"{self._media_base}/generate"
        body = {"model": model_id, "input": input_payload}
        logger.info("POST %s model=%s", gen_url, model_id)

        try:
            resp = await self._client.post(gen_url, json=body)
        except httpx.TimeoutException as exc:
            raise RuntimeError(f"Timed out after {self._config.timeout}s submitting job") from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"HTTP error submitting job: {exc}") from exc

        if resp.status_code >= 400:
            raise NordRouterError(
                f"Generation failed ({resp.status_code}): {resp.text[:500]}",
                status=resp.status_code,
            )

        job_info = resp.json()
        poll_url = job_info.get("poll")
        if not poll_url:
            raise RuntimeError(f"No poll URL in response: {job_info}")

        start = asyncio.get_event_loop().time()
        max_wait = self._config.timeout
        delay = 2.0

        while True:
            elapsed = asyncio.get_event_loop().time() - start
            if elapsed > max_wait:
                raise RuntimeError(
                    f"Timed out after {max_wait:.0f}s waiting for job completion ({poll_url})"
                )

            await asyncio.sleep(delay)
            if delay < 4.0:
                delay += 0.5

            try:
                poll_resp = await self._client.get(poll_url)
            except httpx.HTTPError as exc:
                logger.warning("Poll request failed, retrying: %s", exc)
                continue

            if poll_resp.status_code >= 400:
                raise NordRouterError(
                    f"Poll failed ({poll_resp.status_code}): {poll_resp.text[:500]}",
                    status=poll_resp.status_code,
                )

            data = poll_resp.json()
            status = data.get("status")
            if status in ("done", "completed", "success"):
                cost_usd = data.get("cost_usd")
                cost_rub = (
                    round(cost_usd * self._config.usd_rub, 2)
                    if cost_usd is not None
                    else None
                )
                result_url = data.get("result_url")
                if not result_url and data.get("results"):
                    result_url = data["results"][0].get("url")
                if not result_url:
                    raise RuntimeError(f"Job completed but no result_url: {data}")

                img_res = await self._download(result_url)
                img_res.cost_usd = cost_usd
                img_res.cost_rub = cost_rub
                img_res.gateway_model = model_id
                return img_res

            if status in ("failed", "error"):
                err = data.get("error") or "Unknown error"
                raise RuntimeError(f"Generation job failed: {err}")

    # -- download helper --------------------------------------------------
    async def _download(self, url: str) -> ImageResult:
        logger.info("Downloading %s", url)
        try:
            client_noauth = httpx.AsyncClient(timeout=httpx.Timeout(self._config.timeout, connect=30.0), follow_redirects=True)
            async with client_noauth:
                resp = await client_noauth.get(url)
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Failed to download image {url}: {exc}") from exc
        if resp.status_code >= 400:
            raise RuntimeError(f"Failed to download image {url}: HTTP {resp.status_code}")
        ctype = resp.headers.get("content-type", "").split(";")[0].strip() or "image/png"
        return ImageResult(data=resp.content, content_type=ctype, source="url")

    # -- v1 contour helpers -----------------------------------------------
    async def _v1_images_generate(
        self,
        model: str,
        prompt: str,
        size: str | None = None,
        quality: str | None = None,
    ) -> ImageResult:
        url = f"{self._v1_base}/images/generations"
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "n": 1,
            "safety_filter": self._config.safety_filter,
        }
        if size:
            payload["size"] = size
        if quality:
            payload["quality"] = quality

        logger.info("POST %s (model=%s)", url, model)
        try:
            resp = await self._client.post(
                url, json=payload, headers={"Content-Type": "application/json"}
            )
        except httpx.TimeoutException as exc:
            raise RuntimeError(f"Timed out after {self._config.timeout}s calling {url}") from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"HTTP error calling {url}: {exc}") from exc

        if resp.status_code >= 400:
            raise NordRouterError(
                f"v1 generation failed ({resp.status_code}): {resp.text[:500]}",
                status=resp.status_code,
            )

        data = resp.json().get("data", [])
        if not data:
            raise RuntimeError(f"No image data returned from {url}: {resp.text[:500]}")

        item = data[0]
        if item.get("b64_json"):
            img = ImageResult(
                data=base64.b64decode(item["b64_json"]),
                content_type="image/png",
                source="b64",
                gateway_model=model,
            )
        elif item.get("url"):
            img = await self._download(item["url"])
            img.gateway_model = model
        else:
            raise RuntimeError(f"Unrecognized data format: {item}")

        img.cost_usd = 0.05
        img.cost_rub = round(0.05 * self._config.usd_rub, 2)
        return img

    @staticmethod
    def _aspect_to_v1_size(aspect_ratio: str) -> str:
        """Convert aspect ratio to OpenAI v1-compatible size string.
        GPT Image 2 supports: 1024x1024, 1536x1024 (landscape), 1024x1536 (portrait)."""
        landscape = {"16:9", "21:9", "4:3", "5:4"}
        portrait = {"9:16", "3:4", "4:5"}
        if aspect_ratio in landscape:
            return "1536x1024"
        if aspect_ratio in portrait:
            return "1024x1536"
        return "1024x1024"

    # Standard aspect ratios accepted by the NordRouter /media pipeline.
    _STANDARD_ASPECT_RATIOS: tuple[str, ...] = (
        "1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "5:4", "4:5", "21:9",
    )

    @classmethod
    def _normalize_aspect_ratio(cls, aspect_ratio: str) -> str:
        """Snap a possibly custom aspect ratio (e.g. '1620:1087') to the nearest
        standard ratio accepted by the NordRouter /media pipeline.

        The web UI sends exact pixel ratios when the user picks 'Auto' with a
        reference image; the gateway rejects anything outside its whitelist.
        """
        ar = (aspect_ratio or "").strip()
        if ar in cls._STANDARD_ASPECT_RATIOS:
            return ar
        try:
            parts = ar.split(":")
            if len(parts) != 2:
                return "1:1"
            w, h = float(parts[0]), float(parts[1])
            if w <= 0 or h <= 0:
                return "1:1"
            ratio = w / h
        except (ValueError, ZeroDivisionError):
            return "1:1"

        # Map each standard ratio to its numeric value and pick the closest.
        best = "1:1"
        best_diff = float("inf")
        for std in cls._STANDARD_ASPECT_RATIOS:
            sw, sh = std.split(":")
            diff = abs(ratio - float(sw) / float(sh))
            if diff < best_diff:
                best_diff = diff
                best = std
        return best

    # -- high-level unified interface -------------------------------------
    async def generate(
        self,
        model: str | None,
        prompt: str,
        aspect_ratio: str = "1:1",
        resolution: str = "1k",
        size: str | None = None,
        quality: str | None = None,
        n: int = 1,
    ) -> list[ImageResult]:
        """Generate images using any model family or exact gateway ID."""
        resolved = resolve_model(model, mode="t2i")
        results: list[ImageResult] = []

        for _ in range(max(1, int(n))):
            if resolved.contour == "v1":
                v1_size = size or self._aspect_to_v1_size(aspect_ratio)
                img = await self._v1_images_generate(
                    model=resolved.gateway_id,
                    prompt=prompt,
                    size=v1_size,
                    quality=quality,
                )
            else:
                input_payload: dict[str, Any] = {
                    "prompt": prompt,
                    "aspect_ratio": self._normalize_aspect_ratio(aspect_ratio),
                    "resolution": resolution,
                    "safety_filter": self._config.safety_filter,
                }
                img = await self._media_job(resolved.gateway_id, input_payload)

            results.append(img)

        return results

    async def edit(
        self,
        model: str | None,
        prompt: str,
        image_data_url: str | list[str],
        aspect_ratio: str = "1:1",
        resolution: str = "1k",
    ) -> ImageResult:
        """Edit an existing image using any model family or exact gateway ID.

        ``image_data_url`` may be a single data URL (str) or a list of data URLs.
        When multiple images are supplied the first goes into ``image`` and the
        second into ``image2`` (for /media models that support it, e.g. Qwen3).
        For the /v1 contour every image is added as a separate ``image_url``
        content block so the model can reference them by order in the prompt.
        """
        # Normalise to a list while keeping backward compatibility.
        if isinstance(image_data_url, str):
            image_data_urls: list[str] = [image_data_url]
        else:
            image_data_urls = [u for u in image_data_url if u]
        if not image_data_urls:
            raise ValueError("edit() requires at least one image")

        resolved = resolve_model(model, mode="i2i")

        if resolved.contour == "v1":
            content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
            for data_url in image_data_urls:
                content.append({"type": "image_url", "image_url": {"url": data_url}})
            payload = {
                "model": resolved.gateway_id,
                "modalities": ["image", "text"],
                "messages": [{"role": "user", "content": content}],
                "safety_filter": self._config.safety_filter,
            }
            url = f"{self._v1_base}/chat/completions"
            resp = await self._client.post(
                url, json=payload, headers={"Content-Type": "application/json"}
            )
            if resp.status_code >= 400:
                raise NordRouterError(
                    f"v1 edit failed ({resp.status_code}): {resp.text[:500]}",
                    status=resp.status_code,
                )
            text = ((resp.json().get("choices", [{}])[0].get("message") or {}).get("content")) or ""
            urls = _MD_IMAGE_RE.findall(text) or _raw_image_urls(text)
            if not urls:
                raise RuntimeError(f"No image returned from v1 edit: {text[:500]}")
            img = await self._download(urls[0])
            img.gateway_model = resolved.gateway_id
            img.cost_usd = 0.0375
            img.cost_rub = round(0.0375 * self._config.usd_rub, 2)
            return img

        # /media contour: upload every image, then map to image / image2 fields.
        uploaded_urls: list[str] = []
        for data_url in image_data_urls:
            uploaded_urls.append(await self.upload_media_image(data_url))

        input_payload: dict[str, Any] = {
            "prompt": prompt,
            "image": uploaded_urls[0],
            "aspect_ratio": self._normalize_aspect_ratio(aspect_ratio),
            "resolution": resolution,
            "safety_filter": self._config.safety_filter,
        }
        # Models like qwen3-pro-edit / qwen3-edit accept a second reference via "image2".
        if len(uploaded_urls) > 1:
            input_payload["image2"] = uploaded_urls[1]
        return await self._media_job(resolved.gateway_id, input_payload)

    async def generate_with_refs(
        self,
        model: str | None,
        prompt: str,
        image_urls: list[str],
        aspect_ratio: str = "1:1",
        resolution: str = "1k",
    ) -> ImageResult:
        """Generate an image with reference images via /media/generate.

        Used for models that accept ``image`` in the generate input but do not
        have a dedicated i2i/edit endpoint (e.g. z-image, imagen4).
        ``image_urls`` must already be uploaded gateway URLs (not data URLs).
        Only the first image is passed as ``image``; extras are ignored.
        """
        resolved = resolve_model(model, mode="t2i")
        if resolved.contour != "media":
            raise ValueError(f"generate_with_refs only supports /media contour, got {resolved.contour}")
        input_payload: dict[str, Any] = {
            "prompt": prompt,
            "aspect_ratio": self._normalize_aspect_ratio(aspect_ratio),
            "resolution": resolution,
            "safety_filter": self._config.safety_filter,
            "image": image_urls[0],
        }
        return await self._media_job(resolved.gateway_id, input_payload)

    async def upscale(self, image_data_url: str) -> ImageResult:
        """Upscale an image using Recraft Upscale."""
        resolved = resolve_model("recraft-upscale", mode="upscale")
        uploaded_url = await self.upload_media_image(image_data_url)
        input_payload: dict[str, Any] = {"image": uploaded_url}
        return await self._media_job(resolved.gateway_id, input_payload)

    async def remove_background(self, image_data_url: str) -> ImageResult:
        """Remove background using Recraft Remove Background."""
        resolved = resolve_model("recraft-remove-bg", mode="remove_bg")
        uploaded_url = await self.upload_media_image(image_data_url)
        input_payload: dict[str, Any] = {"image": uploaded_url}
        return await self._media_job(resolved.gateway_id, input_payload)

