"""Gemini 무료 API 연결 확인 (실제 요청 최대 3회: 텍스트 LITE 1 + 텍스트 MAIN 1 + 손글씨 OCR 1).

실행: .venv/Scripts/python scripts/gemini_smoke.py [--list-only]
- 키는 .streamlit/secrets.toml 또는 환경변수 GEMINI_API_KEY 에서 읽고, 출력하지 않는다.
- 결과는 이 PC의 임시 SQLite에만 기록한다(운영 DB 사용 안 함).
- 무료 한도는 https://aistudio.google.com/rate-limit 에서 확인. 결제 프로젝트면 과금될 수 있음.
"""
import os
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from services.ai import AIError, AIService, GeminiProvider  # noqa: E402
from datetime import timedelta  # noqa: E402

from services.config import DEFAULTS, utcnow  # noqa: E402
from services.store import LocalStore  # noqa: E402


def setting(name):
    secrets = ROOT / ".streamlit" / "secrets.toml"
    data = tomllib.loads(secrets.read_text(encoding="utf-8")) if secrets.exists() else {}
    return os.environ.get(name) or data.get(name) or DEFAULTS.get(name)


def handwriting_png(text="implement") -> bytes:
    img = Image.new("RGB", (640, 200), "white")
    try:
        font = ImageFont.truetype("segoepr.ttf", 72)  # Windows 손글씨체(없으면 기본 글꼴)
    except OSError:
        font = ImageFont.load_default(size=72)
    ImageDraw.Draw(img).text((30, 50), text, fill="black", font=font)
    import io
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def main():
    key = setting("GEMINI_API_KEY")
    if not key:
        print("GEMINI_API_KEY 없음 → AI 꺼짐 모드로 동작 (정상)")
        return 0
    provider = GeminiProvider(key)
    main_m, lite_m = setting("GEMINI_MODEL_MAIN"), setting("GEMINI_MODEL_LITE")
    available = set(provider.list_models())
    for m in (main_m, lite_m):
        print(f"[모델] {m}: {'사용 가능' if m in available else '목록에 없음 → GEMINI_MODEL_* 변경 필요'}")
    if "--list-only" in sys.argv:
        return 0
    with tempfile.TemporaryDirectory() as tmp:
        store = LocalStore(str(Path(tmp) / "smoke.db"))
        fallback = lite_m if str(setting("GEMINI_ALLOW_FALLBACK")).lower() == "true" else None
        ai = AIService(provider, store, model_main=main_m, model_lite=lite_m, daily_budget=6, fallback_model=fallback)
        checks = [
            ("LITE 예문", lambda: ai.example("implement", "실행하다", "토익")),
            ("MAIN OCR", lambda: ai.ocr(handwriting_png("implement"))),
        ]
        ok = True
        for name, fn in checks:
            try:
                r = fn()
                print(f"[성공] {name} (사용 모델: {ai.last_model}): {r.model_dump()}")
            except AIError as e:
                ok = False
                print(f"[실패] {name}: kind={e.kind} detail={e.detail}")
        cached = ai.example("implement", "실행하다", "토익")  # 캐시 적중 → API 호출 없음
        usage = store.list_ai_usage(utcnow() - timedelta(days=1))
        print(f"[캐시] 재요청 결과 있음: {bool(cached)} · 사용량 기록: {[(u['model_id'], u['status']) for u in usage]}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
