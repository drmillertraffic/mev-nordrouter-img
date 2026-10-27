"""Model families and capability routing for NordRouter.

Curated catalog of user-facing model families.
"""

from dataclasses import dataclass
from typing import Literal

Contour = Literal["v1", "media"]
Mode = Literal["t2i", "i2i", "upscale", "remove_bg"]


@dataclass(frozen=True)
class ModelFamily:
    id: str
    name: str
    vendor: str
    contour: Contour
    t2i_id: str | None
    i2i_id: str | None
    est_usd_t2i: float | None
    est_usd_i2i: float | None
    description: str
    aliases: tuple[str, ...] = ()

    @property
    def can_generate(self) -> bool:
        return self.t2i_id is not None

    @property
    def can_edit(self) -> bool:
        return self.i2i_id is not None


CATALOG: tuple[ModelFamily, ...] = (
    ModelFamily(
        id="gpt-image-2",
        name="GPT Image 2",
        vendor="OpenAI",
        contour="v1",
        t2i_id="openai/gpt-image-2",
        i2i_id="openai/gpt-image-2",
        est_usd_t2i=0.05,
        est_usd_i2i=0.0375,
        description="OpenAI: фотореализм, текст на картинках, редактирование. До 4K.",
        aliases=("openai/gpt-image-2", "gpt-image", "gpt2"),
    ),
    ModelFamily(
        id="nano-banana-pro",
        name="Nano Banana Pro",
        vendor="Google",
        contour="media",
        t2i_id="image/nano-banana-pro",
        i2i_id="image/nano-banana-edit",
        est_usd_t2i=0.1125,
        est_usd_i2i=0.025,
        description="Google Imagen 3 (Pro): высокая детализация, реалистичные текстуры.",
        aliases=("image/nano-banana-pro", "nano-banana", "nano-banana-edit"),
    ),
    ModelFamily(
        id="grok",
        name="Grok Image",
        vendor="xAI",
        contour="media",
        t2i_id="image/grok",
        i2i_id="image/grok-edit",
        est_usd_t2i=0.025,
        est_usd_i2i=0.025,
        description="xAI Grok: креативность, точное следование промпту, быстрая генерация.",
        aliases=("image/grok", "image/grok-edit", "grok-image"),
    ),
    ModelFamily(
        id="qwen3-pro",
        name="Qwen Image 3 Pro",
        vendor="Alibaba",
        contour="media",
        t2i_id="image/qwen3-pro",
        i2i_id="image/qwen3-pro-edit",
        est_usd_t2i=0.0438,
        est_usd_i2i=0.0438,
        description="Alibaba Qwen 3 Pro: текст на картинках, высокая детализация, сильный i2i.",
        aliases=("image/qwen3-pro", "image/qwen3-pro-edit", "qwen3", "qwen"),
    ),
    ModelFamily(
        id="recraft-upscale",
        name="Recraft Upscale",
        vendor="Recraft",
        contour="media",
        t2i_id=None,
        i2i_id="image/recraft-upscale",
        est_usd_t2i=None,
        est_usd_i2i=0.0063,
        description="Recraft: увеличение разрешения и чёткости без искажения стиля.",
        aliases=("image/recraft-upscale", "upscale"),
    ),
    ModelFamily(
        id="recraft-remove-bg",
        name="Recraft Remove Background",
        vendor="Recraft",
        contour="media",
        t2i_id=None,
        i2i_id="image/recraft-remove-bg",
        est_usd_t2i=None,
        est_usd_i2i=0.0063,
        description="Recraft: аккуратное удаление фона с сохранением мелких деталей.",
        aliases=("image/recraft-remove-bg", "remove-bg", "remove_bg"),
    ),
)


@dataclass(frozen=True)
class ResolvedModel:
    family: ModelFamily
    gateway_id: str
    contour: Contour
    mode: Mode
    est_usd: float | None


def find_family(name_or_id: str) -> ModelFamily | None:
    clean = (name_or_id or "").strip().lower()
    if not clean:
        return None
    for f in CATALOG:
        if f.id.lower() == clean or any(a.lower() == clean for a in f.aliases):
            return f
        if f.t2i_id and f.t2i_id.lower() == clean:
            return f
        if f.i2i_id and f.i2i_id.lower() == clean:
            return f
    for f in CATALOG:
        if clean in f.id.lower() or f.id.lower() in clean:
            return f
    return None


def resolve_model(name_or_id: str | None, mode: Mode = "t2i") -> ResolvedModel:
    if not name_or_id:
        if mode in ("t2i", "i2i"):
            family = CATALOG[0]
        elif mode == "upscale":
            family = next(f for f in CATALOG if f.id == "recraft-upscale")
        elif mode == "remove_bg":
            family = next(f for f in CATALOG if f.id == "recraft-remove-bg")
        else:
            family = CATALOG[0]
    else:
        family = find_family(name_or_id)
        if family is None:
            available = ", ".join(f.id for f in CATALOG)
            raise ValueError(
                f"Неизвестная модель: '{name_or_id}'. Доступные модели: {available}"
            )

    if mode == "t2i":
        if not family.can_generate:
            raise ValueError(
                f"Модель '{family.name}' ({family.id}) предназначена только для "
                f"обработки изображений (upscale/remove_bg), а не генерации с нуля."
            )
        return ResolvedModel(
            family=family,
            gateway_id=family.t2i_id,  # type: ignore[arg-type]
            contour=family.contour,
            mode=mode,
            est_usd=family.est_usd_t2i,
        )

    if mode in ("i2i", "upscale", "remove_bg"):
        if not family.can_edit:
            raise ValueError(
                f"Модель '{family.name}' ({family.id}) не поддерживает обработку изображений."
            )
        return ResolvedModel(
            family=family,
            gateway_id=family.i2i_id,  # type: ignore[arg-type]
            contour=family.contour,
            mode=mode,
            est_usd=family.est_usd_i2i,
        )

    raise ValueError(f"Неизвестный режим: {mode}")


def format_catalog_for_user(usd_rub_rate: float = 95.0) -> list[dict]:
    result = []
    for f in CATALOG:
        usd = f.est_usd_t2i if f.est_usd_t2i is not None else f.est_usd_i2i
        rub = round(usd * usd_rub_rate, 2) if usd is not None else None
        modes = []
        if f.can_generate:
            modes.append("generate")
        if f.can_edit:
            if f.id == "recraft-upscale":
                modes.append("upscale")
            elif f.id == "recraft-remove-bg":
                modes.append("remove_bg")
            else:
                modes.append("edit")
        result.append({
            "id": f.id,
            "name": f.name,
            "vendor": f.vendor,
            "modes": modes,
            "price": {
                "usd": f"≈ ${usd:.4f}" if usd else "—",
                "rub": f"≈ {rub:.2f} ₽" if rub else "—",
                "per": "1 генерация / обработка",
            },
            "description": f.description,
        })
    return result

