"""
Claude Vision analyzer — enhanced for MTF and full metadata extraction.
"""

import base64
import hashlib
import json
import logging
import time
from io import BytesIO
from typing import Optional, List, Tuple

from anthropic import Anthropic, APIError, APIConnectionError, RateLimitError
from PIL import Image
from pydantic import ValidationError

from app.config import settings
from app.core.prompts import SINGLE_IMAGE_PROMPT, MTF_PROMPT
from app.schemas.analysis import AnalysisResult

logger = logging.getLogger(__name__)

MAX_IMAGE_DIM = 1568  # Anthropic recommendation for vision
STABLE_CLAUDE_MODEL = "claude-sonnet-4-6"

MODEL_ALIASES = {
    "claude-sonnet-4-20250514": STABLE_CLAUDE_MODEL,
    "claude-opus-4-20250514": STABLE_CLAUDE_MODEL,
    "claude-3-5-sonnet-20241022": STABLE_CLAUDE_MODEL,
}

# Token cost per 1M tokens (USD) — adjust if pricing changes
MODEL_PRICING = {
    "claude-fable-5": {"input": 3.00, "output": 15.00},
    "claude-opus-4-8": {"input": 15.00, "output": 75.00},
    "claude-opus-4-7": {"input": 15.00, "output": 75.00},
    "claude-opus-4-6": {"input": 15.00, "output": 75.00},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    "claude-sonnet-4-5-20250929": {"input": 3.00, "output": 15.00},
    "claude-haiku-4-5-20251001": {"input": 1.00, "output": 5.00},
}

_client: Optional[Anthropic] = None


def _normalize_model(model: Optional[str]) -> str:
    model_name = (model or STABLE_CLAUDE_MODEL).strip()
    normalized = MODEL_ALIASES.get(model_name, model_name)
    if normalized != model_name:
        logger.warning("Unsupported Claude model %s replaced with %s", model_name, normalized)
    return normalized


def get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _client


class AnalyzerError(Exception):
    """Domain-level analyzer error."""


# ─── Image preprocessing ───

def prepare_image(image_bytes: bytes) -> Tuple[str, str, str]:
    """
    Validate, resize if needed, base64-encode.
    Returns (base64_data, media_type, sha256_hex).
    """
    try:
        img = Image.open(BytesIO(image_bytes))
        img.load()
    except Exception as e:
        raise AnalyzerError(f"الصورة غير صالحة: {e}")

    if max(img.size) > MAX_IMAGE_DIM:
        img.thumbnail((MAX_IMAGE_DIM, MAX_IMAGE_DIM), Image.LANCZOS)

    buf = BytesIO()
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGB")
    img.save(buf, format="JPEG", quality=92, optimize=True)
    encoded_bytes = buf.getvalue()
    image_hash = hashlib.sha256(encoded_bytes).hexdigest()
    return (
        base64.b64encode(encoded_bytes).decode("utf-8"),
        "image/jpeg",
        image_hash,
    )


def _strip_json_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    # Some models prepend "json" tag without fence
    if text.lower().startswith("json\n"):
        text = text[5:].strip()
    return text


# ─── Cost calculation ───

def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    pricing = MODEL_PRICING.get(model)
    if not pricing:
        # Default to stable Sonnet pricing if unknown
        pricing = MODEL_PRICING[STABLE_CLAUDE_MODEL]
    return (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000


# ─── Main entry points ───

def analyze_single_chart(
    image_bytes: bytes,
    extra_context: Optional[str] = None,
    model: Optional[str] = None
) -> dict:
    """Analyze ONE chart image."""
    image_b64, media_type, image_hash = prepare_image(image_bytes)
    return _run_analysis(
        prompt=SINGLE_IMAGE_PROMPT,
        images=[(image_b64, media_type)],
        image_hashes=[image_hash],
        extra_context=extra_context,
        model=model,
        is_mtf=False,
    )


def analyze_mtf(
    images_bytes: List[bytes],
    extra_context: Optional[str] = None,
    model: Optional[str] = None
) -> dict:
    """
    Analyze multiple chart images (multi-timeframe).
    Images should be ordered from HIGHEST to LOWEST timeframe.
    """
    if not (2 <= len(images_bytes) <= settings.MAX_IMAGES_PER_ANALYSIS):
        raise AnalyzerError(
            f"عدد الصور يجب أن يكون بين 2 و {settings.MAX_IMAGES_PER_ANALYSIS}"
        )
    prepared = [prepare_image(b) for b in images_bytes]
    images = [(p[0], p[1]) for p in prepared]
    hashes = [p[2] for p in prepared]
    return _run_analysis(
        prompt=MTF_PROMPT,
        images=images,
        image_hashes=hashes,
        extra_context=extra_context,
        model=model,
        is_mtf=True,
    )


def _run_analysis(
    prompt: str,
    images: List[Tuple[str, str]],
    image_hashes: List[str],
    extra_context: Optional[str],
    model: Optional[str],
    is_mtf: bool,
) -> dict:
    """Internal — executes Claude call and packages metadata."""
    user_text_parts = []
    if is_mtf:
        user_text_parts.append(
            f"حلّل هذه الـ {len(images)} شارتات بشكل MTF متكامل. "
            "الصور مرتبة من الـ HTF للـ LTF. أرجع JSON منظم بالـ schema المطلوب فقط."
        )
    else:
        user_text_parts.append(
            "حلّل هذا الشارت بشكل كامل. أرجع JSON منظم بالـ schema المطلوب فقط."
        )
    if extra_context:
        user_text_parts.append(f"\n📝 سياق إضافي:\n{extra_context.strip()}")

    user_content = []
    for b64, mt in images:
        user_content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": mt, "data": b64},
        })
    user_content.append({"type": "text", "text": "\n".join(user_text_parts)})

    chosen_model = _normalize_model(model or settings.CLAUDE_MODEL)
    client = get_client()
    start = time.monotonic()

    try:
        response = client.messages.create(
            model=chosen_model,
            max_tokens=settings.MAX_OUTPUT_TOKENS,
            system=prompt,
            messages=[{"role": "user", "content": user_content}],
        )
    except RateLimitError as e:
        raise AnalyzerError(f"تجاوز حد الـ API: {e}")
    except APIConnectionError as e:
        raise AnalyzerError(f"خطأ اتصال: {e}")
    except APIError as e:
        raise AnalyzerError(f"خطأ Anthropic API: {e}")
    except Exception as e:
        raise AnalyzerError(f"خطأ غير متوقع: {e}")

    duration_ms = int((time.monotonic() - start) * 1000)

    text_blocks = [b.text for b in response.content if hasattr(b, "text")]
    if not text_blocks:
        raise AnalyzerError("الـ AI لم يرجع نص.")
    raw_text = _strip_json_fences("".join(text_blocks))

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as e:
        logger.error("Invalid JSON: %s", raw_text[:1000])
        raise AnalyzerError(f"JSON غير صالح من الـ AI: {e}")

    # Validate
    try:
        validated = AnalysisResult(**data)
        result = validated.model_dump()
    except ValidationError as e:
        logger.warning("Schema validation issues: %s", e)
        result = data
        if not isinstance(result.get("warnings_ar"), list):
            result["warnings_ar"] = []
        result["warnings_ar"].insert(
            0, f"⚠️ بيانات غير مكتملة: {len(e.errors())} حقل تحتاج مراجعة"
        )

    cost = estimate_cost(
        chosen_model,
        response.usage.input_tokens,
        response.usage.output_tokens,
    )

    result["_meta"] = {
        "model": response.model,
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "cost_usd": round(cost, 5),
        "duration_ms": duration_ms,
        "is_mtf": is_mtf,
        "image_count": len(images),
        "image_hashes": image_hashes,
    }
    return result
