"""학습 분석 지표 (순수 함수). 실측 지표와 FSRS 모델 추정치를 구분하고, 표본 수를 함께 돌려준다."""
from collections import defaultdict
from datetime import datetime, timedelta

from services import study
from services.handwriting import normalize_text

REAL_CALLS = {"ok", "invalid", "rate_limited", "timeout", "error", "model"}


def _ratio(num: int, den: int) -> float | None:
    return round(num / den, 3) if den else None


def review_metrics(events: list[dict], now: datetime, tz, days: int) -> dict:
    since = now - timedelta(days=days)
    ev = [e for e in events if e["created_at"] >= since]
    graded = [e for e in ev if e.get("correct") is not None]
    daily = defaultdict(lambda: {"reviews": 0, "graded": 0, "correct": 0})
    for e in ev:
        d = daily[e["created_at"].astimezone(tz).date().isoformat()]
        d["reviews"] += 1
        if e.get("correct") is not None:
            d["graded"] += 1
            d["correct"] += int(e["correct"])
    series = [{"date": k, "reviews": v["reviews"],
               "accuracy": _ratio(v["correct"], v["graded"])} for k, v in sorted(daily.items())]
    # 복습 이행률: 만기가 있던 복습 중 만기 당일(현지 날짜)까지 수행한 비율
    due_reviews = [e for e in ev if e.get("due_before")]
    on_time = sum(1 for e in due_reviews
                  if e["created_at"].astimezone(tz).date() <= _dt(e["due_before"]).astimezone(tz).date())
    return {
        "days": days, "reviews": len(ev), "graded": len(graded),
        "accuracy": _ratio(sum(e["correct"] for e in graded), len(graded)),
        "new_learned": sum(1 for e in ev if not e.get("due_before")),
        "adherence": _ratio(on_time, len(due_reviews)), "adherence_n": len(due_reviews),
        "series": series,
    }


def word_outcomes(events: list[dict]) -> dict:
    """'틀렸던 단어를 다시 맞힌 비율'과 '한 번이라도 맞힌 단어 비율'을 구분해 계산."""
    by_word = defaultdict(list)
    for e in sorted(events, key=lambda e: e["created_at"]):
        if e.get("correct") is not None:
            by_word[e["word_id"]].append(bool(e["correct"]))
    ever_wrong = {w: seq for w, seq in by_word.items() if False in seq}
    recovered = sum(1 for seq in ever_wrong.values() if True in seq[seq.index(False) + 1:])
    return {
        "graded_words": len(by_word),
        "once_correct": _ratio(sum(1 for seq in by_word.values() if True in seq), len(by_word)),
        "wrong_words": len(ever_wrong),
        "recovery": _ratio(recovered, len(ever_wrong)),
    }


def handwriting_metrics(attempts: list[dict]) -> dict:
    ocr = [a for a in attempts if a["status"] == "ocr"]
    edited = sum(1 for a in ocr if normalize_text(a.get("ocr_text") or "") != normalize_text(a.get("confirmed_text") or ""))
    return {
        "attempts": len(attempts), "ocr": len(ocr),
        "user_correction_rate": _ratio(edited, len(ocr)),
        "manual": sum(1 for a in attempts if a["status"] == "manual"),
        "self": sum(1 for a in attempts if a["status"] == "self"),
    }


def ai_metrics(usage: list[dict], now: datetime) -> dict:
    calls = [u for u in usage if u["status"] in REAL_CALLS]
    ok = sum(1 for u in calls if u["status"] == "ok")
    invalid = sum(1 for u in calls if u["status"] == "invalid")
    hits = sum(1 for u in usage if u["status"] == "cache_hit")
    today = [u for u in calls if _dt(u["created_at"]) >= now - timedelta(hours=24)]
    return {
        "calls": len(calls), "calls_24h": len(today),
        "error_rate": _ratio(len(calls) - ok - invalid, len(calls)),
        "schema_pass_rate": _ratio(ok, ok + invalid),
        "cache_hit_rate": _ratio(hits, hits + ok),
        "reported": sum(1 for u in usage if u["status"] == "reported"),
        "report_rate": _ratio(sum(1 for u in usage if u["status"] == "reported"), ok),
        "tokens_in": sum(u.get("tokens_in") or 0 for u in calls),
        "tokens_out": sum(u.get("tokens_out") or 0 for u in calls),
    }


def predicted_retention(progress: dict[str, dict], now: datetime) -> dict:
    """FSRS 모델이 추정한 현재 평균 기억 확률. 실측 정답률이 아님."""
    vals = []
    for row in progress.values():
        try:
            vals.append(study.retrievability(row, now))
        except Exception:
            continue
    return {"mean": round(sum(vals) / len(vals), 3) if vals else None, "cards": len(vals)}


def _dt(value) -> datetime:
    from services.config import parse_dt
    return value if isinstance(value, datetime) else parse_dt(value)
