"""Per-model request profiles.

NordRouter models differ in which request fields they accept: some reject a
``size``, some take ``quality``, and a few are listed by ``/v1/models`` but are
not usable at all. Sending a field a model does not understand makes the gateway
reject the whole request with ``invalid_request`` even though the model itself is
fine.

This module keeps that knowledge in one place. The payload builders in
``utils.api_client`` only send fields listed in a model's profile, so a request
is always valid for the model it targets.
"""

from __future__ import annotations

from dataclasses import dataclass

CHAT = "chat"
IMAGES = "images"

# Fields a payload may contain, per endpoint contour.
CHAT_FIELDS = frozenset({"modalities", "messages", "safety_filter"})
IMAGE_FIELDS = frozenset({"prompt", "n", "size", "quality", "safety_filter"})

# Order in which fields are dropped when the gateway rejects a payload, from
# least to most important. ``safety_filter`` goes last: dropping it re-enables
# server-side moderation, so it is only sacrificed as a last resort.
CHAT_OPTIONAL_ORDER = ("safety_filter",)
IMAGE_OPTIONAL_ORDER = ("quality", "size", "n", "safety_filter")

# Substrings that route a model to ``POST /v1/images/generations``. Everything
# else (including ``google/gemini-3.1-flash-image-preview``) goes through
# ``POST /v1/chat/completions`` with ``modalities``.
_ENDPOINT_HINTS = (
    "gpt-image",
    "dall-e",
    "dalle",
    "seedream",
    "imagen",
    "flux",
    "stable",
    "sdxl",
    "recraft",
    "ideogram",
    "midjourney",
    "playground",
)

# Substrings that identify image-capable models. Note the absence of a bare
# "nano": that used to pull text models such as ``openai/gpt-5.4-nano`` into the
# image list.
_IMAGE_HINTS = _ENDPOINT_HINTS + (
    "nano-banana",
    "-image",  # e.g. google/gemini-3.1-flash-image-preview
)


@dataclass(frozen=True)
class ModelProfile:
    """Which request fields a model actually accepts."""

    endpoint: str
    fields: frozenset[str]
    available: bool = True
    note: str = ""
    image_model: bool = True

    def supports(self, name: str) -> bool:
        return name in self.fields

    def filter_payload(self, payload: dict) -> dict:
        """Drop every key the model does not understand.

        ``model`` is always kept: it selects the model rather than describing it.
        """
        return {
            key: value
            for key, value in payload.items()
            if key == "model" or self.supports(key)
        }

    @property
    def optional_order(self) -> tuple[str, ...]:
        return CHAT_OPTIONAL_ORDER if self.endpoint == CHAT else IMAGE_OPTIONAL_ORDER


_CHAT_PROFILE = ModelProfile(endpoint=CHAT, fields=CHAT_FIELDS)
_IMAGES_PROFILE = ModelProfile(endpoint=IMAGES, fields=IMAGE_FIELDS)

# Verified against the live API; see the README section "Профили моделей".
_PROFILES: dict[str, ModelProfile] = {
    "google/gemini-3.1-flash-image-preview": _CHAT_PROFILE,
    "openai/gpt-image-2": _IMAGES_PROFILE,
    "bytedance/seedream-5.0-pro": ModelProfile(
        endpoint=IMAGES,
        fields=frozenset({"prompt"}),
        available=False,
        note=(
            "not usable through /v1: the gateway rejects every request with "
            "invalid_request; only image/seedream-5.0-pro-edit (i2i) exists on "
            "the media API"
        ),
    ),
    "openai/gpt-5.4-nano:fjord": ModelProfile(
        endpoint=CHAT,
        fields=frozenset(),
        available=False,
        image_model=False,
        note="text model listed in /v1/models by mistake; returns 404 model_not_found",
    ),
    "search/openai/gpt-5.4-nano:fjord": ModelProfile(
        endpoint=CHAT,
        fields=frozenset(),
        available=False,
        image_model=False,
        note="text model listed in /v1/models by mistake; returns 404 model_not_found",
    ),
}

# Fallbacks for models we have not verified yet. Keys are substrings of the id.
_PREFIX_RULES: tuple[tuple[str, ModelProfile], ...] = (
    ("gpt-image", _IMAGES_PROFILE),
    ("dall-e", _IMAGES_PROFILE),
    ("imagen", _IMAGES_PROFILE),
    ("flux", _IMAGES_PROFILE),
    ("nano-banana", _IMAGES_PROFILE),
    ("seedream", _IMAGES_PROFILE),
)


def classify(model: str) -> str:
    """Return ``"images"`` or ``"chat"`` — which endpoint serves the model."""
    m = model.lower()
    return IMAGES if any(hint in m for hint in _ENDPOINT_HINTS) else CHAT


def get_profile(model: str) -> ModelProfile:
    """Return the profile for ``model`` (exact, then pattern, then default)."""
    exact = _PROFILES.get(model)
    if exact is not None:
        return exact

    m = model.lower()
    for prefix, profile in _PREFIX_RULES:
        if prefix in m:
            return profile

    return _IMAGES_PROFILE if classify(model) == IMAGES else _CHAT_PROFILE


def is_image_capable(model_id: str) -> bool:
    """Whether the id is an image model (``available`` is reported separately)."""
    profile = _PROFILES.get(model_id)
    if profile is not None:
        return profile.image_model

    m = model_id.lower()
    return any(hint in m for hint in _IMAGE_HINTS)
