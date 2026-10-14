"""FSRS 복습 엔진 연결부: 카드 계산은 py-fsrs, 저장은 store.record_review(원자적·멱등).

- 시간은 모두 UTC. '오늘'의 경계만 APP_TIMEZONE(기본 Asia/Seoul)으로 계산한다.
- 학습 평가는 사용자가 고른 Again/Hard/Good/Easy만 쓴다(AI가 평가를 정하지 않음).
- 레거시 memorized/wrong 기록으로 가짜 복습 날짜를 만들지 않는다.
"""
import random
import time as _time
import uuid
from datetime import datetime, time, timedelta, timezone

from fsrs import Card, Rating, Scheduler

from services.config import utcnow

# 공식 기본 파라미터(desired_retention=0.9)를 그대로 쓴다. 퍼징만 끄는 이유:
# 버튼에 미리 보여준 '다음 복습' 시각과 실제 저장 시각이 같아야 하기 때문.
SCHEDULER = Scheduler(enable_fuzzing=False)

RATING_LABELS = {1: "Again · 기억 못함", 2: "Hard · 어렵게 기억", 3: "Good · 보통", 4: "Easy · 쉽게 기억"}


class ReviewConflict(Exception):
    """두 기기가 동시에 같은 카드를 갱신해 재시도 한도를 넘김."""


def new_card(now: datetime) -> Card:
    return Card(due=now)


def card_from_progress(row: dict | None, now: datetime) -> Card:
    return Card.from_dict(row["fsrs_card"]) if row else new_card(now)


def suggested_rating(correct: bool | None) -> int:
    """정오답 확정 후 기본 추천값: 오답 → Again, 정답 → Good. 최종 선택은 사용자."""
    return 1 if correct is False else 3


def preview_due(row: dict | None, now: datetime, scheduler: Scheduler = SCHEDULER) -> dict[int, datetime]:
    card = card_from_progress(row, now)
    return {r: scheduler.review_card(card, Rating(r), now)[0].due for r in (1, 2, 3, 4)}


def submit_review(store, *, word_id: str, rating: int, mode: str, correct: bool | None,
                  attempt_id: str | None = None, now: datetime | None = None,
                  duration_ms: int | None = None, device_type: str | None = None,
                  session_id: str | None = None, scheduler: Scheduler = SCHEDULER,
                  max_retries: int = 5) -> dict:
    """학습 결과 1건 저장. 같은 attempt_id를 다시 보내면 'duplicate'로 끝나고 카드는 그대로다.

    version이 바뀌었으면(다른 기기가 먼저 저장) 최신 카드를 다시 읽어 그 위에서 재계산한다.
    """
    if rating not in (1, 2, 3, 4):
        raise ValueError("rating은 1~4(Again/Hard/Good/Easy)만 허용됩니다.")
    attempt_id = attempt_id or str(uuid.uuid4())
    now = now or utcnow()
    for attempt in range(max_retries):
        if attempt:
            _time.sleep(random.uniform(0.02, 0.1) * attempt)  # 동시 저장 충돌 시 짧은 지터 후 재시도
        row = store.get_progress_one(word_id)
        card = card_from_progress(row, now)
        updated, _log = scheduler.review_card(card, Rating(rating), now)
        status = store.record_review(
            attempt_id=attempt_id, word_id=word_id, expected_version=row["version"] if row else 0,
            fsrs_card=updated.to_dict(), due_at=updated.due, reviewed_at=now, rating=rating,
            correct=correct, mode=mode, duration_ms=duration_ms, device_type=device_type,
            session_id=session_id, due_before=row["due_at"] if row else None)
        if status in ("ok", "duplicate"):
            return {"status": status, "attempt_id": attempt_id, "due_at": updated.due}
    raise ReviewConflict("다른 기기에서 동시에 저장 중입니다. 잠시 후 다시 시도하세요.")


def day_bounds(now: datetime, tz) -> tuple[datetime, datetime]:
    """현지 날짜 기준 오늘 00:00 ~ 내일 00:00 (UTC로 반환)."""
    local = now.astimezone(tz)
    start = datetime.combine(local.date(), time.min, tzinfo=tz)
    return start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc)


def build_today_queue(words: list[dict], progress: dict[str, dict], now: datetime, tz, *,
                      new_limit: int = 10, review_limit: int = 30, legacy_wrong: set | None = None,
                      recent_wrong_ids: set | None = None) -> dict:
    """출제 순서: 기한 지난 카드 → 오늘 만기(지금 가능) → 새 단어 (학습량 제한 적용).

    - 오늘 안에 만기지만 아직 시각이 안 된 카드(예: Again 후 10분 뒤)는 'later_today'로 세기만 하고 큐에 넣지 않는다.
    - 반복 오답은 FSRS 일정을 앞당기지 않고, 만기가 아닌 카드 중 '추가 연습' 후보로만 보여준다.
    """
    today_start, tomorrow = day_bounds(now, tz)
    legacy_wrong = legacy_wrong or set()
    recent_wrong_ids = recent_wrong_ids or set()
    overdue, due_today, later_today, repeat_wrong, fresh = [], [], [], [], []
    for w in words:
        row = progress.get(w["id"])
        if row is None:
            fresh.append(w)
        elif row["due_at"] < today_start:
            overdue.append((row["due_at"], w))
        elif row["due_at"] <= now:
            due_today.append((row["due_at"], w))
        elif row["due_at"] < tomorrow:
            later_today.append(w)
        elif row["lapse_count"] >= 2 or w["id"] in recent_wrong_ids:
            repeat_wrong.append((-row["lapse_count"], w))
    overdue.sort(key=lambda x: x[0])
    due_today.sort(key=lambda x: x[0])
    repeat_wrong.sort(key=lambda x: x[0])
    # 새 단어: 예전 앱에서 틀렸던 단어(legacy)를 먼저, 그다음 원본 번호 순
    fresh.sort(key=lambda w: (w["no"] not in legacy_wrong, w["no"]))
    reviews = [w for _, w in overdue + due_today][:review_limit]
    return {
        "overdue": [w for _, w in overdue],
        "due_today": [w for _, w in due_today],
        "later_today": later_today,
        "repeat_wrong": [w for _, w in repeat_wrong],
        "new": fresh[:new_limit],
        "new_total": len(fresh),
        "queue": reviews + fresh[:new_limit],
    }


def estimate_minutes(card_count: int, events: list[dict], default_sec: int = 20) -> int:
    """예상 소요 시간: 최근 기록의 중앙 응답 시간(없으면 20초) × 카드 수."""
    durations = sorted(e["duration_ms"] for e in events if e.get("duration_ms"))
    sec = durations[len(durations) // 2] / 1000 if durations else default_sec
    return max(1, round(card_count * min(sec, 180) / 60)) if card_count else 0


def retrievability(row: dict, now: datetime, scheduler: Scheduler = SCHEDULER) -> float:
    """FSRS 모델이 추정한 현재 기억 확률(실측 정답률 아님)."""
    return scheduler.get_card_retrievability(Card.from_dict(row["fsrs_card"]), now)
