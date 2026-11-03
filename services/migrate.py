"""Word.xlsx / progress.json → DB 이전.

원칙
- 원본 파일은 읽기만 한다 (수정·삭제 없음).
- word_id는 (소유자, 원본 번호)로 결정되는 UUIDv5 → 재실행해도 같은 행이 되어 중복 입력이 없다.
- 같은 철자·다의어는 병합하지 않는다 (번호 단위로 이전).
- progress.json에는 복습 시각·난이도가 없으므로 FSRS 리뷰 로그를 만들지 않는다.
  memorized/wrong/correct/sessions는 legacy_state로만 보존하고 FSRS는 첫 신규 복습부터 시작한다.
"""
import csv
import hashlib
import json
import uuid

import openpyxl

SHEET_NAME = "영어 단어장"
WORD_NAMESPACE = uuid.UUID("6f1c2b3e-8d0a-4c55-9a7e-2b1f0c9d7e31")
EMPTY_LEGACY = {"memorized": [], "wrong": [], "correct": [], "sessions": []}


def word_uuid(owner: str | None, source_no: int) -> str:
    return str(uuid.uuid5(WORD_NAMESPACE, f"{owner or 'public'}:{int(source_no)}"))


def read_excel_words(path: str) -> list[dict]:
    """기존 app.load_words와 같은 규칙으로 '영어 단어장' 시트를 읽는다."""
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb[SHEET_NAME]
    result, auto_no = [], 1
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, values_only=True):
        if not row[1]:
            continue
        no_val = row[0] if row[0] else auto_no
        result.append({
            "no": no_val,
            "word": str(row[1]).strip(),
            "meaning": str(row[2]).strip() if row[2] else "",
            "example": str(row[3]).strip() if row[3] else "",
            "category": str(row[8]).strip() if len(row) > 8 and row[8] else "기타",
            "ai_example": str(row[9]).strip() if len(row) > 9 and row[9] else "",
            "_extra": list(row[4:6]),
        })
        auto_no = int(no_val) + 1
    return result


def content_checksum(words: list[dict]) -> str:
    """번호·단어·뜻·예문·카테고리·AI예문 기준 SHA-256 (DB 왕복 후 비교용)."""
    items = sorted(
        (int(w["no"]), w["word"], w["meaning"], w["example"], w["category"], w.get("ai_example", ""))
        for w in words
    )
    return hashlib.sha256(json.dumps(items, ensure_ascii=False).encode()).hexdigest()


def _json_safe(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def vocabulary_rows(words: list[dict], owner: str | None) -> list[dict]:
    return [{
        "word_id": word_uuid(owner, w["no"]),
        "owner_user_id": owner,
        "source_no": int(w["no"]),
        "word": w["word"],
        "meaning": w["meaning"],
        "example": w["example"],
        "ai_example": w.get("ai_example", ""),
        "category": w["category"] or "기타",
        "extra": {"memo": _json_safe((w.get("_extra") or [None, None])[0]),
                  "input_date": _json_safe((w.get("_extra") or [None, None])[1])},
    } for w in words]


def words_from_rows(rows: list[dict]) -> list[dict]:
    """DB vocabulary 행 → 기존 앱의 단어 dict 형태."""
    out = []
    for r in sorted(rows, key=lambda r: (r.get("source_no") or 10**9, r["word"])):
        extra = r.get("extra") or {}
        out.append({
            "id": str(r["word_id"]), "no": r["source_no"], "word": r["word"], "meaning": r["meaning"],
            "example": r["example"], "category": r["category"], "ai_example": r.get("ai_example", ""),
            "_extra": [extra.get("memo"), extra.get("input_date")],
        })
    return out


def legacy_state(progress: dict | None, valid_nos: set) -> dict:
    """progress.json → legacy_state. 존재하지 않는 단어 번호는 버리고 나머지는 그대로 보존."""
    progress = progress or {}
    return {
        "memorized": sorted(n for n in progress.get("memorized", []) if n in valid_nos),
        "wrong": sorted(n for n in progress.get("wrong", []) if n in valid_nos),
        "correct": sorted(n for n in progress.get("correct", []) if n in valid_nos),
        "sessions": list(progress.get("sessions", [])),
    }


def merge_legacy(server: dict, incoming: dict) -> dict:
    """두 기기의 legacy 진도를 합친다(합집합). 시험 기록은 같은 항목을 한 번만 남긴다."""
    server = {**EMPTY_LEGACY, **(server or {})}
    incoming = {**EMPTY_LEGACY, **(incoming or {})}
    seen, sessions = set(), []
    for s in server["sessions"] + incoming["sessions"]:
        key = json.dumps(s, sort_keys=True, ensure_ascii=False)
        if key not in seen:
            seen.add(key)
            sessions.append(s)
    sessions.sort(key=lambda s: s.get("date", ""))
    wrong = set(server["wrong"]) | set(incoming["wrong"])
    correct = (set(server["correct"]) | set(incoming["correct"])) - wrong
    return {"memorized": sorted(set(server["memorized"]) | set(incoming["memorized"])),
            "wrong": sorted(wrong), "correct": sorted(correct), "sessions": sessions}


def write_mapping(path: str, rows: list[dict]) -> None:
    """원본 번호 ↔ word_id 매핑 (비공개 로컬 파일, Git 제외 경로에 저장)."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["source_no", "word_id"])
        for r in rows:
            w.writerow([r["source_no"], r["word_id"]])


def import_vocabulary(store, words: list[dict]) -> dict:
    """사용자 소유 단어로 가져오기. 이미 있는 행은 덮어쓰지 않는다(앱에서 수정한 내용 보호)."""
    rows = vocabulary_rows(words, store.user_id)
    existing = {str(r["word_id"]) for r in store.list_vocabulary()}
    new_rows = [r for r in rows if r["word_id"] not in existing]
    store.upsert_vocabulary(new_rows)
    after = [r for r in store.list_vocabulary() if r.get("owner_user_id") == store.user_id]
    imported = [r for r in after if r["word_id"] in {x["word_id"] for x in rows}]
    return {
        "source_count": len(rows),
        "inserted": len(new_rows),
        "skipped_existing": len(rows) - len(new_rows),
        "db_count": len(imported),
        "source_checksum": content_checksum(words),
        "db_checksum": content_checksum(words_from_rows(imported)),
    }


def import_legacy_progress(store, progress: dict, valid_nos: set, now) -> str:
    """progress.json 1회 가져오기. 이미 가져왔으면 아무것도 하지 않는다."""
    profile = store.ensure_profile()
    if profile.get("legacy_imported_at"):
        return "already_imported"
    merged = merge_legacy(profile.get("legacy_state") or {}, legacy_state(progress, valid_nos))
    store.save_legacy_state(merged, mark_imported=True, now=now)
    return "imported"
