"""
NordRouter Web Backend — FastAPI application
Reuses the existing core (utils/api_client.py, utils/model_families.py) directly.
"""
import os, sys, json, time, uuid, hashlib, asyncio, base64, logging
from pathlib import Path
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from utils.api_client import NordRouterClient
from utils.config import get_config
from utils.model_families import format_catalog_for_user

app = FastAPI(title="NordRouter Web UI")

WEB_DIR = Path(__file__).resolve().parent.parent
STORAGE_DIR = WEB_DIR / "storage"
IMAGES_DIR = STORAGE_DIR / "images"
THUMBS_DIR = STORAGE_DIR / "thumbs"
for d in [IMAGES_DIR, THUMBS_DIR]:
    d.mkdir(parents=True, exist_ok=True)
STATE_FILE = STORAGE_DIR / "state.json"


def _make_image_id(prefix: str = "") -> str:
    """Generate a timestamp-based image ID for chronological file sorting.
    Format: {unix_ts_ms}_{prefix} or just {unix_ts_ms}_ref for references."""
    ts_ms = int(time.time() * 1000)
    if prefix:
        # Sanitize prefix: replace non-alphanumeric with dashes
        safe = "".join(c if c.isalnum() or c == "-" else "-" for c in prefix.lower())
        return f"{ts_ms}_{safe}"
    return f"{ts_ms}_ref"


def _save_data_url(data_url: str) -> str:
    """Persist an uploaded reference (data URL) to disk, return its /api/images URL."""
    header, _, b64 = data_url.partition(",")
    ext = "jpg" if "jpeg" in header else ("webp" if "webp" in header else "png")
    image_id = _make_image_id()
    (IMAGES_DIR / f"{image_id}.{ext}").write_bytes(base64.b64decode(b64))
    return f"/api/images/{image_id}"


_MIME_BY_EXT = {".png": "image/png", ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg", ".webp": "image/webp"}


def _resolve_reference(ref: str) -> tuple[str, str | None]:
    """Normalize a reference coming from the frontend.

    The frontend may send either:
      * a base64 data URL (fresh upload/paste), or
      * an /api/images/<id> URL (restored from history/feed or variation flow).

    Returns (persisted_url, data_url). ``data_url`` is a valid
    ``data:image/...;base64,...`` string ready for the NordRouter upload,
    or None if the reference cannot be resolved.
    """
    if not ref:
        return ref, None

    if ref.startswith("data:"):
        header, _, b64 = ref.partition(",")
        if not b64:
            return ref, None
        try:
            base64.b64decode(b64)
        except Exception:
            logger.warning("_resolve_reference: invalid base64 payload (header=%s)", header[:60])
            return ref, None
        return _save_data_url(ref), ref

    # /api/images/<id> (possibly with query string) → read back from disk
    path = ref.split("?")[0]
    image_id = path.rstrip("/").split("/")[-1]
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        p = IMAGES_DIR / f"{image_id}{ext}"
        if p.exists():
            raw = p.read_bytes()
            if not raw:
                logger.warning("_resolve_reference: empty file %s", p)
                return ref, None
            mime = _MIME_BY_EXT.get(ext, "image/png")
            return ref, f"data:{mime};base64,{base64.b64encode(raw).decode()}"

    logger.warning("_resolve_reference: image not found on disk for %s", ref)
    return ref, None


cfg = get_config()
WEB_PASSWORD = os.environ.get("WEB_PASSWORD", "admin")
client = NordRouterClient(config=cfg)

generations = {}  # gen_id -> {params, cards}


# ---- Auth ----
class LoginRequest(BaseModel):
    password: str

@app.post("/api/auth/login")
async def login(req: LoginRequest):
    if req.password != WEB_PASSWORD:
        raise HTTPException(status_code=401, detail="Неверный пароль")
    token = hashlib.sha256(f"{WEB_PASSWORD}:{time.time()}".encode()).hexdigest()[:32]
    return {"token": token}

async def verify_token(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True

# ---- Models catalog ----
@app.get("/api/models")
async def get_models(_=Depends(verify_token)):
    try:
        catalog = format_catalog_for_user(usd_rub_rate=cfg.usd_rub)
        return {"models": catalog}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---- Generate ----
class GenerateRequest(BaseModel):
    prompt: str
    models: list[str]
    variants: int = 1
    aspect_ratio: str = "1:1"
    resolution: str = "1k"
    format: str = "png"
    enhance_prompt: bool = False
    comment: Optional[str] = None
    references: list[str] = []
    style_name: Optional[str] = None

@app.post("/api/generate")
async def generate(req: GenerateRequest, _=Depends(verify_token)):
    gen_id = str(uuid.uuid4())
    cards = []
    for model_id in req.models:
        for v in range(req.variants):
            cards.append({"status": "pending", "model": model_id, "image_id": None, "error": None})
    params = req.dict()
    raw_refs = list(req.references)
    logger.info("generate: %d refs, lengths=%s", len(raw_refs), [len(r) for r in raw_refs])

    # Normalize every reference: accept both fresh data URLs and already
    # persisted /api/images/<id> URLs (history restore / variation flow).
    persisted_refs: list[str] = []
    refs_data: list[str] = []
    for r in raw_refs:
        persisted, data_url = _resolve_reference(r)
        persisted_refs.append(persisted)
        if data_url:
            refs_data.append(data_url)
        else:
            logger.warning("generate: reference could not be resolved to a data URL: %s", r[:80])

    params["references"] = persisted_refs
    generations[gen_id] = {"params": params, "cards": cards,
                           "created_at": datetime.utcnow().isoformat(),
                           "_refs_data": refs_data}
    asyncio.create_task(_run_generation(gen_id))
    _persist_state()
    return {"generation_id": gen_id, "total_cards": len(cards)}


async def _run_generation(gen_id: str):
    gen = generations[gen_id]
    params = gen["params"]
    refs = gen.get("_refs_data") or []
    idx = 0
    for model_id in params["models"]:
        for v in range(params["variants"]):
            try:
                gen["cards"][idx]["status"] = "generating"
                if refs:
                    # Use first reference for edit mode
                    result = await client.edit(
                        model=model_id, prompt=params["prompt"],
                        image_data_url=refs[0],
                        aspect_ratio=params["aspect_ratio"],
                        resolution=params["resolution"],
                    )
                else:
                    results = await client.generate(
                        model=model_id, prompt=params["prompt"],
                        aspect_ratio=params["aspect_ratio"],
                        resolution=params["resolution"], n=1,
                    )
                    result = results[0] if results else None

                if result and result.data:
                    image_id = _make_image_id(model_id)
                    ext = "png" if params["format"] == "png" else "jpg"
                    img_path = IMAGES_DIR / f"{image_id}.{ext}"
                    img_path.write_bytes(result.data)
                    gen["cards"][idx]["image_id"] = image_id
                    gen["cards"][idx]["status"] = "done"
                else:
                    gen["cards"][idx]["status"] = "error"
                    gen["cards"][idx]["error"] = "No image returned"
            except Exception as e:
                gen["cards"][idx]["status"] = "error"
                gen["cards"][idx]["error"] = str(e)
            idx += 1
            _persist_state()


@app.get("/api/generate/{gen_id}/status")
async def get_gen_status(gen_id: str, _=Depends(verify_token)):
    if gen_id not in generations:
        raise HTTPException(status_code=404, detail="Not found")
    return {"cards": generations[gen_id]["cards"]}


class RetryRequest(BaseModel):
    prompt: str
    model: str
    aspect_ratio: str = "1:1"
    resolution: str = "1k"
    format: str = "png"
    references: list[str] = []


@app.post("/api/generate/retry")
async def retry_single(req: RetryRequest, _=Depends(verify_token)):
    """Retry generation for a single model. Returns {image_id} or {error}."""
    try:
        raw_refs = list(req.references)
        refs_data: list[str] = []
        for r in raw_refs:
            _persisted, data_url = _resolve_reference(r)
            if data_url:
                refs_data.append(data_url)
            else:
                logger.warning("retry: reference could not be resolved to a data URL: %s", r[:80])

        if refs_data:
            result = await client.edit(
                model=req.model, prompt=req.prompt,
                image_data_url=refs_data[0],
                aspect_ratio=req.aspect_ratio,
                resolution=req.resolution,
            )
        else:
            results = await client.generate(
                model=req.model, prompt=req.prompt,
                aspect_ratio=req.aspect_ratio,
                resolution=req.resolution, n=1,
            )
            result = results[0] if results else None

        if result and result.data:
            image_id = _make_image_id(req.model)
            ext = "png" if req.format == "png" else "jpg"
            img_path = IMAGES_DIR / f"{image_id}.{ext}"
            img_path.write_bytes(result.data)
            return {"image_id": image_id, "model": req.model}
        else:
            return {"error": "No image returned"}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/images/{image_id}")
async def get_image(image_id: str):
    for ext in ["png", "jpg", "jpeg", "webp"]:
        path = IMAGES_DIR / f"{image_id}.{ext}"
        if path.exists():
            media = "jpeg" if ext == "jpg" else ext
            return FileResponse(path, media_type=f"image/{media}")
    raise HTTPException(status_code=404, detail="Image not found")


# ---- History (in-memory + JSON persistence) ----
def _gen_status(gen):
    cards = gen["cards"]
    if any(c["status"] in ("pending", "generating") for c in cards):
        return "generating"
    if cards and all(c["status"] == "error" for c in cards):
        return "error"
    return "done"


def _history_item(gid, gen):
    cards = gen["cards"]
    done = [c for c in cards if c["status"] == "done"]
    return {
        "id": gid,
        "prompt": gen["params"]["prompt"],
        "comment": gen["params"].get("comment"),
        "models_count": len(set(c["model"] for c in cards)),
        "created_at": gen["created_at"],
        "status": _gen_status(gen),
        "previews": [f"/api/images/{c['image_id']}" for c in done[:4]],
        "images": [f"/api/images/{c['image_id']}" for c in done],
        "done_count": len(done),
        "total_count": len(cards),
        "params": gen["params"],
        "cards": cards,
    }


@app.get("/api/history")
async def get_history(_=Depends(verify_token)):
    items = [_history_item(gid, gen) for gid, gen in
             sorted(generations.items(), key=lambda x: x[1]["created_at"], reverse=True)]
    return {"items": items}


@app.get("/api/history/{gen_id}")
async def get_history_item(gen_id: str, _=Depends(verify_token)):
    if gen_id not in generations:
        raise HTTPException(status_code=404, detail="Not found")
    return _history_item(gen_id, generations[gen_id])


@app.delete("/api/history/{gen_id}")
async def delete_history(gen_id: str, _=Depends(verify_token)):
    generations.pop(gen_id, None)
    _persist_state()
    return {"ok": True}


# ---- Templates ----
DEFAULT_TEMPLATES = [
    {"id": 1, "name": "Каталожная съёмка белья", "category": "Fashion",
     "description": "Профессиональная каталожная фотография нижнего белья на модели",
     "prompt_skeleton": "Professional catalog photography of lingerie on a model, studio lighting, clean white background",
     "variables": [{"name": "color", "label": "Цвет белья", "example": "чёрное кружевное"}],
     "recommended_models": ["flux-2-pro", "ideogram-v3"], "aspect_ratio": "3:4", "resolution": "1k"},
    {"id": 2, "name": "Баннер Яндекс.Директ", "category": "Баннеры",
     "description": "Рекламный баннер с товаром и текстом для контекстной рекламы",
     "prompt_skeleton": "Advertising banner for web, product photography with bold text overlay, {style} design",
     "variables": [{"name": "style", "label": "Стиль", "example": "яркий / сдержанный / с кнопкой"}],
     "recommended_models": ["flux-2-pro", "gpt-image-2"], "aspect_ratio": "16:9", "resolution": "1k"},
    {"id": 3, "name": "Флэтлей товара", "category": "Карточки маркетплейсов",
     "description": "Раскладка товара на плоской поверхности сверху",
     "prompt_skeleton": "Flat lay product photography from above, {product} on {surface}, natural lighting",
     "variables": [{"name": "product", "label": "Товар", "example": "косметика"},
                   {"name": "surface", "label": "Поверхность", "example": "мраморный стол"}],
     "recommended_models": ["flux-2-pro", "seedream"], "aspect_ratio": "1:1", "resolution": "1k"},
    {"id": 4, "name": "Карточка товара для маркетплейса", "category": "Карточки маркетплейсов",
     "description": "Основное фото для карточки товара на Wildberries/Ozon",
     "prompt_skeleton": "Product photography for marketplace listing, {product} on clean background, studio lighting",
     "variables": [{"name": "product", "label": "Товар", "example": "кроссовки Nike"}],
     "recommended_models": ["flux-2-pro", "ideogram-v3", "seedream"], "aspect_ratio": "4:5", "resolution": "1k", "type": "prompt"},
    # Style templates (applied as wrapper around content)
    {"id": 101, "name": "Продающий", "icon": "🎯", "category": "Стиль",
     "description": "Яркие акценты, крупный заголовок, CTA",
     "prompt_template": "Рекламный баннер в продающем стиле. Яркие акценты, крупный заголовок, кнопка CTA, светлый фон, энергичная композиция.\n\nТекст на баннере:\n{content}",
     "type": "style"},
    {"id": 102, "name": "Индустриальный", "icon": "🏭", "category": "Стиль",
     "description": "Тёмный фон, минимум декора, технический",
     "prompt_template": "Индустриальный стиль. Тёмный фон, минимум декора, техническая эстетика, металлические текстуры, строгая геометрия.\n\nТекст на баннере:\n{content}",
     "type": "style"},
    {"id": 103, "name": "Минимализм", "icon": "✨", "category": "Стиль",
     "description": "Много воздуха, тонкая типографика",
     "prompt_template": "Минималистичный стиль. Много воздуха, тонкая типографика, нейтральные цвета, чистая композиция.\n\nТекст на баннере:\n{content}",
     "type": "style"},
    {"id": 104, "name": "Тёмная тема", "icon": "🌙", "category": "Стиль",
     "description": "Чёрный фон, неоновые акценты",
     "prompt_template": "Тёмная тема. Чёрный фон, неоновые акценты, контрастный текст, глубокие тени.\n\nТекст на баннере:\n{content}",
     "type": "style"},
    {"id": 105, "name": "Киберпанк", "icon": "⚡", "category": "Стиль",
     "description": "Глитч-эффекты, неон, футуризм",
     "prompt_template": "Киберпанк стиль. Глитч-эффекты, неон, футуризм, pink/cyan/purple градиенты, цифровые артефакты.\n\nТекст на баннере:\n{content}",
     "type": "style"},
]
templates_store = {t["id"]: t for t in DEFAULT_TEMPLATES}
_next_tid = 106

@app.get("/api/templates")
async def get_templates(_=Depends(verify_token)):
    return {"templates": list(templates_store.values())}

@app.post("/api/templates")
async def create_template(data: dict, _=Depends(verify_token)):
    global _next_tid; tid = _next_tid; _next_tid += 1
    data["id"] = tid; templates_store[tid] = data; _persist_state(); return data

@app.put("/api/templates/{tid}")
async def update_template(tid: int, data: dict, _=Depends(verify_token)):
    if tid not in templates_store: raise HTTPException(status_code=404)
    data["id"] = tid; templates_store[tid] = data; _persist_state(); return data

@app.delete("/api/templates/{tid}")
async def delete_template(tid: int, _=Depends(verify_token)):
    templates_store.pop(tid, None); _persist_state(); return {"ok": True}

@app.post("/api/templates/{tid}/duplicate")
async def duplicate_template(tid: int, _=Depends(verify_token)):
    global _next_tid
    if tid not in templates_store: raise HTTPException(status_code=404)
    nid = _next_tid; _next_tid += 1
    dup = {**templates_store[tid], "id": nid, "name": templates_store[tid]["name"] + " (копия)"}
    templates_store[nid] = dup; _persist_state(); return dup


# ---- Favorites ----
favorites_store = set()

@app.get("/api/favorites")
async def get_favorites(_=Depends(verify_token)):
    return {"favorites": list(favorites_store)}

@app.post("/api/favorites/{model_id}")
async def toggle_favorite(model_id: str, _=Depends(verify_token)):
    if model_id in favorites_store: favorites_store.discard(model_id)
    else: favorites_store.add(model_id)
    _persist_state()
    return {"favorites": list(favorites_store)}


# ---- State persistence (MVP: JSON file) ----
def _persist_state():
    try:
        data = {
            "generations": {gid: {"params": g["params"], "cards": g["cards"],
                                  "created_at": g["created_at"]}
                            for gid, g in generations.items()},
            "templates": list(templates_store.values()),
            "next_tid": _next_tid,
            "favorites": list(favorites_store),
        }
        STATE_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _load_state():
    global _next_tid
    if not STATE_FILE.exists():
        return
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return
    for gid, g in (data.get("generations") or {}).items():
        for c in g.get("cards", []):
            if c.get("status") in ("pending", "generating"):
                c["status"] = "error"
                c["error"] = "Прервано перезапуском сервера"
        generations[gid] = g
    saved_templates = data.get("templates")
    if saved_templates:
        templates_store.clear()
        for t in saved_templates:
            templates_store[t["id"]] = t
        _next_tid = max([t["id"] for t in saved_templates] + [0]) + 1
        # Migrate: replace old style templates with new defaults
        old_style_ids = {tid for tid, t in templates_store.items() if t.get("type") == "style"}
        new_style_ids = {t["id"] for t in DEFAULT_TEMPLATES if t.get("type") == "style"}
        # Remove old styles that are not in the new set
        for old_id in old_style_ids - new_style_ids:
            del templates_store[old_id]
        # Add/update new styles
        for t in DEFAULT_TEMPLATES:
            if t.get("type") == "style":
                templates_store[t["id"]] = t
                _next_tid = max(_next_tid, t["id"] + 1)
        _persist_state()
    favorites_store.update(data.get("favorites") or [])


_load_state()


# ---- Serve static frontend ----
app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="static")