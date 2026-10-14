"""필기 제출 검증과 정답 판정 (AI 판단을 그대로 믿지 않는 Python 비교)."""
import base64
import binascii
import io
import re
import unicodedata

from PIL import Image, ImageOps, UnidentifiedImageError

PNG_PREFIX = "data:image/png;base64,"
MIN_SIDE = 16


class HandwritingError(ValueError):
    """사용자에게 그대로 보여줄 수 있는 한국어 메시지를 담는다."""


def decode_submission(data_url: str, *, max_bytes: int, max_side: int) -> tuple[bytes, tuple[int, int]]:
    """컴포넌트가 보낸 data URL → 검증된 PNG 바이트. 실제 MIME·크기·용량·빈 화면을 서버에서 다시 확인한다."""
    if not isinstance(data_url, str) or not data_url.startswith(PNG_PREFIX):
        raise HandwritingError("PNG 이미지가 아닙니다.")
    encoded = data_url[len(PNG_PREFIX):]
    if len(encoded) > max_bytes * 4 // 3 + 4:
        raise HandwritingError("필기 이미지가 너무 큽니다. 여백을 줄이거나 다시 써 주세요.")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise HandwritingError("이미지 데이터가 손상되었습니다.") from None
    if len(raw) > max_bytes:
        raise HandwritingError("필기 이미지가 너무 큽니다. 여백을 줄이거나 다시 써 주세요.")
    try:
        with Image.open(io.BytesIO(raw)) as probe:
            fmt, size = probe.format, probe.size
            probe.verify()
        with Image.open(io.BytesIO(raw)) as img:
            img.load()
            if img.mode in ("RGBA", "LA", "P"):
                bg = Image.new("RGBA", img.size, "white")
                bg.alpha_composite(img.convert("RGBA"))
                img = bg
            gray = img.convert("L")
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        raise HandwritingError("이미지를 읽을 수 없습니다.") from None
    if fmt != "PNG":
        raise HandwritingError("PNG 이미지가 아닙니다.")
    if min(size) < MIN_SIDE or max(size) > max_side:
        raise HandwritingError("이미지 크기가 허용 범위를 벗어났습니다.")
    # 거의 흰색(240 이상)만 있으면 빈 필기로 본다
    if ImageOps.invert(gray).point(lambda v: 255 if v > 15 else 0).getbbox() is None:
        raise HandwritingError("필기가 비어 있습니다. 먼저 단어를 써 주세요.")
    return raw, size


_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", "‐": "-", "‑": "-"})
_EDGE_PUNCT = " .,!?;:\"'`()[]"


def normalize_text(text: str) -> str:
    """NFKC 정규화 → 따옴표/대시 통일 → 소문자(casefold) → 공백 1칸 → 앞뒤 문장부호 제거."""
    text = unicodedata.normalize("NFKC", text or "").translate(_QUOTES).casefold()
    return re.sub(r"\s+", " ", text).strip(_EDGE_PUNCT + "\n\t")


def is_correct_spelling(written: str, target: str) -> bool:
    """철자 채점 정책.
    - 대소문자 무시, 앞뒤 공백·마침표 무시.
    - 구문(공백/하이픈 포함 정답)은 공백과 하이픈을 같은 구분자로 본다: well-known == well known.
    - 그 외 철자 차이는 모두 오답 (붙여 쓰기 'lookup' ≠ 'look up').
    """
    a, b = normalize_text(written), normalize_text(target)
    if not a or not b:
        return False
    if re.search(r"[\s-]", b):
        a, b = re.sub(r"\s*-\s*|\s+", " ", a), re.sub(r"\s*-\s*|\s+", " ", b)
    return a == b


def contains_target(sentence: str, target: str) -> bool:
    """작문 모드: 목표 단어(기본 굴절형 -s/-es/-ed/-d/-ing 포함)가 문장에 쓰였는지. 의미 적절성은 판단하지 않음."""
    s, t = normalize_text(sentence), normalize_text(target)
    if not t:
        return False
    stem = re.escape(t[:-1]) + r"(?:e)?" if t.endswith("e") else re.escape(t)
    return re.search(rf"\b{stem}(?:s|es|ed|d|ing)?\b", s) is not None
