"""포트폴리오 데모용 '합성' 학습 기록 생성 (실제 사용자 기록 아님).

실행: .venv/Scripts/python scripts/seed_demo.py --db <새 SQLite 경로> [--days 21] [--seed 7]
- 기존 파일이 있으면 거부한다(실제 data/wordloop.db 덮어쓰기 방지).
- 앱을 이 DB로 띄우려면: WORDLOOP_DB_PATH=<경로> streamlit run app.py
"""
import argparse
import random
import sys
import uuid
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services import migrate, study  # noqa: E402
from services.store import LocalStore  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--days", type=int, default=21)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    if Path(args.db).exists():
        sys.exit(f"이미 존재: {args.db} — 새 경로를 지정하세요(덮어쓰지 않음)")
    rng = random.Random(args.seed)
    store = LocalStore(args.db)
    words = migrate.read_excel_words(str(ROOT / "Word.xlsx"))
    pool = rng.sample(words, 120)
    skill = {w["no"]: rng.uniform(0.45, 0.95) for w in pool}  # 단어별 가상 숙련도
    today = datetime.now(timezone.utc).date()
    n_events = 0
    for d in range(args.days, 0, -1):
        day = datetime.combine(today - timedelta(days=d), time(11, 0), tzinfo=timezone.utc)
        if rng.random() < 0.2:
            continue  # 쉬는 날
        progress = store.get_progress()
        due = [w for w in pool if (wid := migrate.word_uuid("local", w["no"])) in progress
               and progress[wid]["due_at"] <= day + timedelta(hours=12)]
        fresh = [w for w in pool if migrate.word_uuid("local", w["no"]) not in progress][:rng.randint(4, 9)]
        for i, w in enumerate(due[:25] + fresh):
            wid = migrate.word_uuid("local", w["no"])
            correct = rng.random() < skill[w["no"]]
            skill[w["no"]] = min(0.98, skill[w["no"]] + 0.04)  # 복습할수록 조금씩 향상
            rating = 1 if not correct else rng.choice([2, 3, 3, 3, 4])
            mode = rng.choice(["today:플래시카드", "today:객관식", "handwriting:spell", "handwriting:spell"])
            now = day + timedelta(minutes=i * 2)
            aid = str(uuid.uuid4())
            if mode.startswith("handwriting"):
                ocr = w["word"] if rng.random() > 0.15 else w["word"][:-1] + "x"
                store.add_writing_attempt({"attempt_id": aid, "word_id": wid, "mode": "spell", "ocr_text": ocr,
                                           "confirmed_text": w["word"] if correct else ocr, "status": "ocr",
                                           "correct": correct, "created_at": now, "feedback": {"demo": True}})
                store.log_ai_usage({"feature": "ocr", "model_id": "demo", "status": "ok", "tokens_in": 1100,
                                    "tokens_out": 40, "created_at": now})
            study.submit_review(store, word_id=wid, rating=rating, mode=mode, correct=correct, attempt_id=aid,
                                now=now, duration_ms=rng.randint(4000, 25000), device_type="tablet")
            n_events += 1
        for status in rng.choices(["cache_hit", "ok", "invalid"], [6, 3, 1], k=4):
            store.log_ai_usage({"feature": "example", "model_id": "demo", "status": status, "created_at": day})
    print(f"합성 기록 생성: 복습 {n_events}회, 단어 {len(store.get_progress())}개 → {args.db}")


if __name__ == "__main__":
    main()
