from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from services import analytics, study
from services.store import LocalStore

SEOUL = ZoneInfo("Asia/Seoul")
NOW = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)


def ev(word, days_ago, correct, due_before=None):
    return {"word_id": word, "created_at": NOW - timedelta(days=days_ago), "correct": correct,
            "due_before": due_before}


def test_review_metrics_window_accuracy_adherence():
    events = [
        ev("a", 1, True), ev("a", 0.5, False, due_before=NOW - timedelta(days=0.6)),   # 만기 당일 수행
        ev("b", 3, None), ev("c", 2, True, due_before=NOW - timedelta(days=5)),        # 3일 늦음
        ev("d", 40, True),                                                             # 30일 밖
    ]
    m7 = analytics.review_metrics(events, NOW, SEOUL, 7)
    assert m7["reviews"] == 4 and m7["graded"] == 3 and m7["accuracy"] == round(2 / 3, 3)
    assert m7["new_learned"] == 2 and m7["adherence"] == 0.5 and m7["adherence_n"] == 2
    assert sum(d["reviews"] for d in m7["series"]) == 4
    assert analytics.review_metrics(events, NOW, SEOUL, 30)["reviews"] == 4
    assert analytics.review_metrics([], NOW, SEOUL, 7)["accuracy"] is None    # 표본 없으면 숫자를 만들지 않음


def test_recovery_vs_once_correct_are_different():
    events = [
        ev("a", 5, False), ev("a", 3, True),          # 틀렸다가 회복
        ev("b", 5, True), ev("b", 3, False),          # 맞혔다가 틀림 → 회복 아님
        ev("c", 4, False),                            # 아직 회복 못함
        ev("d", 2, True),
    ]
    o = analytics.word_outcomes(events)
    assert o["graded_words"] == 4 and o["once_correct"] == 0.75
    assert o["wrong_words"] == 3 and o["recovery"] == round(1 / 3, 3)


def test_handwriting_correction_rate():
    attempts = [
        {"status": "ocr", "ocr_text": "implemant", "confirmed_text": "implement"},
        {"status": "ocr", "ocr_text": "Cat.", "confirmed_text": "cat"},     # 정규화 후 같음 → 수정 아님
        {"status": "manual", "ocr_text": None, "confirmed_text": "x"},
        {"status": "self", "ocr_text": None, "confirmed_text": ""},
    ]
    h = analytics.handwriting_metrics(attempts)
    assert h == {"attempts": 4, "ocr": 2, "user_correction_rate": 0.5, "manual": 1, "self": 1}


def test_ai_metrics():
    def u(status, hours=1, t_in=10, t_out=5):
        return {"status": status, "created_at": NOW - timedelta(hours=hours), "tokens_in": t_in, "tokens_out": t_out}
    usage = [u("ok"), u("ok"), u("ok", hours=30), u("invalid"), u("rate_limited"), u("cache_hit", t_in=None),
             u("cache_hit", t_in=None), u("reported", t_in=None)]
    a = analytics.ai_metrics(usage, NOW)
    assert a["calls"] == 5 and a["calls_24h"] == 4
    assert a["schema_pass_rate"] == 0.75 and a["error_rate"] == 0.2
    assert a["cache_hit_rate"] == 0.4 and a["reported"] == 1 and a["report_rate"] == round(1 / 3, 3)


def test_predicted_retention_is_model_estimate(tmp_path):
    store = LocalStore(str(tmp_path / "t.db"))
    study.submit_review(store, word_id="w", rating=3, mode="m", correct=True, now=NOW - timedelta(days=3))
    r = analytics.predicted_retention(store.get_progress(), NOW)
    assert r["cards"] == 1 and 0 < r["mean"] <= 1
    assert analytics.predicted_retention({}, NOW) == {"mean": None, "cards": 0}
