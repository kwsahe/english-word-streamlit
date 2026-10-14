"""필기 제출 검증 · 철자 판정 · '필기 → OCR → 사용자 수정 → 채점 → 1회 저장' 흐름."""
import base64
import io
import json
from datetime import datetime, timedelta, timezone

import pytest
from PIL import Image, ImageDraw

from services.ai import AIError, FakeProvider
from services.handwriting import (HandwritingError, contains_target, decode_submission, is_correct_spelling,
                                  normalize_text)

LIMITS = dict(max_bytes=1_500_000, max_side=2048)


def png_url(img: Image.Image, fmt="PNG") -> str:
    buf = io.BytesIO()
    img.save(buf, fmt)
    return f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}"


def ink(size=(400, 160), text="implement"):
    img = Image.new("RGB", size, "white")
    ImageDraw.Draw(img).text((20, 60), text, fill="black")
    return img


def test_valid_png_accepted():
    raw, size = decode_submission(png_url(ink()), **LIMITS)
    assert raw[:8] == b"\x89PNG\r\n\x1a\n" and size == (400, 160)


@pytest.mark.parametrize("payload, msg", [
    (png_url(Image.new("RGB", (300, 100), "white")), "비어"),                 # 빈 필기
    (png_url(Image.new("RGBA", (300, 100), (0, 0, 0, 0))), "비어"),          # 투명 = 빈 화면
    ("data:image/jpeg;base64,AAAA", "PNG"),                                 # MIME 위장
    ("data:image/png;base64,@@@@", "손상"),                                  # base64 오류
    ("data:image/png;base64," + base64.b64encode(b"not a png at all").decode(), "읽을 수"),
    (png_url(ink(size=(3000, 100))), "크기"),                                # 픽셀 상한
    (png_url(ink(size=(10, 10))), "크기"),                                   # 너무 작음
])
def test_invalid_submissions_rejected(payload, msg):
    with pytest.raises(HandwritingError, match=msg):
        decode_submission(payload, **LIMITS)


def test_jpeg_bytes_with_png_header_rejected():
    buf = io.BytesIO()
    ink().save(buf, "JPEG")
    with pytest.raises(HandwritingError, match="PNG"):
        decode_submission("data:image/png;base64," + base64.b64encode(buf.getvalue()).decode(), **LIMITS)


def test_byte_limit():
    noisy = Image.effect_noise((900, 900), 100).convert("RGB")
    with pytest.raises(HandwritingError, match="너무 큽니다"):
        decode_submission(png_url(noisy), max_bytes=50_000, max_side=2048)


@pytest.mark.parametrize("written, target, ok", [
    ("implement", "implement", True),
    ("Implement.", "implement", True),          # 대소문자·마침표 무시
    ("  implement ", "implement", True),
    ("implemant", "implement", False),
    ("ｉｍｐｌｅｍｅｎｔ", "implement", True),   # 전각 → NFKC
    ("look up", "look up", True),
    ("look  up", "look up", True),
    ("look-up", "look up", True),               # 구문: 공백·하이픈 동일 취급
    ("lookup", "look up", False),               # 붙여 쓰기는 오답
    ("", "implement", False),
])
def test_spelling_policy(written, target, ok):
    assert is_correct_spelling(written, target) is ok


def test_normalize_quotes_and_dashes():
    assert normalize_text("Don’t — go") == "don't - go"


def test_contains_target_inflections():
    assert contains_target("We implemented the plan.", "implement")
    assert contains_target("She is making tea", "make")
    assert not contains_target("We planned it.", "implement")


# ── 흐름: 앱 화면 없이 서비스 계층만으로 계약 확인 ──
def test_ocr_edit_then_grade_records_once(tmp_path):
    from services import study
    from services.ai import AIService
    from services.store import LocalStore
    store = LocalStore(str(tmp_path / "t.db"))
    fake = FakeProvider([json.dumps({"recognized_text": "implemant", "candidates": ["implement"],
                                     "uncertain": True, "notes": "", "schema_version": 1})])
    ai = AIService(fake, store, model_main="m", model_lite="l", daily_budget=10, sleep=lambda s: None)
    png, _ = decode_submission(png_url(ink()), **LIMITS)
    ocr = ai.ocr(png)
    assert ocr.recognized_text == "implemant"
    # OCR 결과 그대로면 오답이지만, 사용자가 실제 필기를 보고 고친 값으로 채점한다
    assert not is_correct_spelling(ocr.recognized_text, "implement")
    confirmed = "implement"
    assert is_correct_spelling(confirmed, "implement")
    now = datetime(2026, 10, 14, tzinfo=timezone.utc)
    aid = "11111111-1111-4111-8111-111111111111"
    store.add_writing_attempt({"attempt_id": aid, "word_id": "w", "mode": "spell", "ocr_text": ocr.recognized_text,
                               "confirmed_text": confirmed, "status": "ocr", "correct": True, "created_at": now})
    for _ in range(2):  # 같은 시도를 두 번 저장해도 1회만 반영
        study.submit_review(store, word_id="w", rating=3, mode="handwriting:spell", correct=True,
                            attempt_id=aid, now=now)
    attempts = store.list_writing_attempts(now - timedelta(days=1))
    assert len(attempts) == 1 and attempts[0]["ocr_text"] != attempts[0]["confirmed_text"]
    assert len(store.list_events(now - timedelta(days=1))) == 1


def test_ocr_prompt_never_contains_answer(tmp_path):
    from services.ai import AIService
    from services.store import LocalStore
    fake = FakeProvider([json.dumps({"recognized_text": "x", "candidates": [], "uncertain": False})])
    ai = AIService(fake, LocalStore(str(tmp_path / "t.db")), model_main="m", model_lite="l", daily_budget=5)
    ai.ocr(b"\x89PNG fake")
    assert fake.calls[0]["image"] and "implement" not in fake.calls[0]["prompt"]


def test_ocr_failure_keeps_manual_path(tmp_path):
    from services.ai import AIService
    from services.store import LocalStore
    ai = AIService(FakeProvider([AIError("rate_limited", retry_after=99)]), LocalStore(str(tmp_path / "t.db")),
                   model_main="m", model_lite="l", daily_budget=5, sleep=lambda s: None)
    with pytest.raises(AIError) as e:
        ai.ocr(b"png")
    assert e.value.kind == "rate_limited" and "한도" in e.value.user_message
