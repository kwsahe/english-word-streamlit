"""미전송 기록 큐. 함수가 아니라 JSON 데이터로 담아 브라우저에 보관하고, 새로고침 후에도 재전송한다.

항목은 모두 멱등(attempt_id / session_id)이라 여러 번 보내도 한 번만 반영된다.
토큰·이메일은 담지 않는다(단어 ID, 평가, 확정 답안 정도).
"""
import json

from services import study
from services.config import parse_dt, to_utc_iso


def review_item(*, word_id, rating, mode, correct, attempt_id, now, duration_ms=None, device_type=None,
                session_id=None, writing: dict | None = None) -> dict:
    item = {"op": "review", "id": str(attempt_id), "word_id": str(word_id), "rating": rating, "mode": mode,
            "correct": correct, "now": to_utc_iso(now), "duration_ms": duration_ms, "device_type": device_type,
            "session_id": session_id}
    if writing:
        item["writing"] = {**writing, "created_at": to_utc_iso(writing["created_at"])}
    return item


def test_session_item(row: dict) -> dict:
    return {"op": "test_session", "id": str(row["session_id"]),
            "row": {**row, "session_id": str(row["session_id"]), "finished_at": to_utc_iso(row["finished_at"])}}


def apply(store, item: dict):
    """항목 1개 저장. 실패하면 StoreError / study.ReviewConflict를 그대로 올린다."""
    if item["op"] == "review":
        if item.get("writing"):
            w = item["writing"]
            store.add_writing_attempt({**w, "created_at": parse_dt(w["created_at"])})
        return study.submit_review(store, word_id=item["word_id"], rating=item["rating"], mode=item["mode"],
                                   correct=item["correct"], attempt_id=item["id"], now=parse_dt(item["now"]),
                                   duration_ms=item.get("duration_ms"), device_type=item.get("device_type"),
                                   session_id=item.get("session_id"))
    if item["op"] == "test_session":
        row = item["row"]
        store.add_test_session({**row, "finished_at": parse_dt(row["finished_at"])})
        return {"status": "ok"}
    raise ValueError(f"알 수 없는 항목: {item.get('op')}")


def merge(*queues: list[dict]) -> list[dict]:
    seen, out = set(), []
    for q in queues:
        for item in q:
            if item.get("id") not in seen:
                seen.add(item.get("id"))
                out.append(item)
    return out


def dumps(items: list[dict]) -> str:
    """빈 큐는 ''(브라우저 저장소에서 삭제)."""
    return json.dumps(items, ensure_ascii=False) if items else ""


def loads(text: str | None) -> list[dict]:
    try:
        items = json.loads(text) if text else []
    except ValueError:
        return []  # 손상된 값은 버린다
    return [i for i in items if isinstance(i, dict) and i.get("op") in ("review", "test_session") and i.get("id")]
