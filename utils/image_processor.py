"""Image helpers: format detection, base64 encoding, saving and conversion."""

from pathlib import Path
import base64
import io
import logging
import mimetypes
import re

from PIL import Image

logger = logging.getLogger(__name__)

# Pillow format name -> (mime type, extension)
_FORMAT_MAP: dict[str, tuple[str, str]] = {
    "png": ("image/png", ".png"),
    "jpeg": ("image/jpeg", ".jpg"),
    "jpg": ("image/jpeg", ".jpg"),
    "webp": ("image/webp", ".webp"),
    "gif": ("image/gif", ".gif"),
    "bmp": ("image/bmp", ".bmp"),
    "tiff": ("image/tiff", ".tiff"),
    "avif": ("image/avif", ".avif"),
}

# extension -> Pillow save format (used when re-encoding to match a requested extension)
_EXT_TO_PIL: dict[str, str] = {
    ".png": "PNG",
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".webp": "WEBP",
    ".gif": "GIF",
    ".bmp": "BMP",
    ".tiff": "TIFF",
}


def detect_image_format(data: bytes) -> tuple[str, str]:
    """Return ``(mime_type, extension)`` for an in-memory image."""
    try:
        with Image.open(io.BytesIO(data)) as im:
            fmt = (im.format or "").lower()
            if fmt in _FORMAT_MAP:
                return _FORMAT_MAP[fmt]
    except Exception:
        pass

    # Fallback to magic bytes.
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return _FORMAT_MAP["png"]
    if data.startswith(b"\xff\xd8\xff"):
        return _FORMAT_MAP["jpeg"]
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return _FORMAT_MAP["webp"]
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return _FORMAT_MAP["gif"]
    if data.startswith(b"BM"):
        return _FORMAT_MAP["bmp"]

    return ("image/png", ".png")


def content_type_to_ext(content_type: str | None) -> str:
    """Map an HTTP ``Content-Type`` header to a file extension (empty if unknown)."""
    if not content_type:
        return ""
    ctype = content_type.split(";")[0].strip().lower()
    for _fmt, (mime, ext) in _FORMAT_MAP.items():
        if mime == ctype:
            return ext
    return mimetypes.guess_extension(ctype) or ""


def file_to_data_uri(path: str | Path) -> str:
    """Read an image file and return it as a ``data:...;base64,...`` URI."""
    p = Path(path)
    data = p.read_bytes()
    mime, _ext = detect_image_format(data)
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{b64}"


def file_to_base64(path: str | Path) -> str:
    """Read an image file and return its raw base64 string (no ``data:`` prefix)."""
    return base64.b64encode(Path(path).read_bytes()).decode("ascii")


def _convert_image(data: bytes, pil_format: str) -> bytes:
    """Re-encode image bytes into another format via Pillow (best effort)."""
    try:
        with Image.open(io.BytesIO(data)) as im:
            if pil_format == "JPEG":
                im = im.convert("RGB")
            buf = io.BytesIO()
            im.save(buf, format=pil_format)
            return buf.getvalue()
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.warning("Image conversion to %s failed (%s); saving original bytes", pil_format, exc)
        return data


def save_image_bytes(data: bytes, path: str | Path, content_type: str | None = None) -> Path:
    """
    Save image bytes to ``path``, creating parent directories.

    A missing or unrecognised extension (say ``model-3.1-preview``, whose
    ``.1-preview`` is part of the name, not an extension) gets the extension of
    the actual image format appended. A known extension that differs from the
    actual format re-encodes the image to match the request.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    _mime, detected_ext = detect_image_format(data)

    target = p.suffix.lower()
    target_pil = _EXT_TO_PIL.get(target)
    detected_pil = _EXT_TO_PIL.get(detected_ext)

    if target_pil is None:
        # No extension at all, or a suffix that is not an image format.
        p = p.with_name(p.name + detected_ext)
    elif target_pil != detected_pil:
        data = _convert_image(data, target_pil)

    p.write_bytes(data)
    return p


def sanitize_filename(name: str) -> str:
    """Turn an arbitrary model name into a safe file-name fragment."""
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")
    return name or "image"


def add_suffix(path: str | Path, suffix: str) -> Path:
    """Insert ``suffix`` before the extension (``a.png`` -> ``a_v1.png``)."""
    p = Path(path)
    return p.with_name(f"{p.stem}{suffix}{p.suffix}")


def resolve_project_path(path: str | Path, project_root: Path) -> Path:
    """Resolve a possibly-relative path against the configured project root."""
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = project_root / p
    return p.resolve()
