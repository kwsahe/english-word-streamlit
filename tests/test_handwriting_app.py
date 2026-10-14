"""✍️ 쓰기 연습 탭 화면 흐름 (AppTest). 캔버스 컴포넌트의 '제출' 이벤트만 가짜로 넣는다."""
import json
import sqlite3
from types import SimpleNamespace

import pytest

from services.ai import AIError, FakeProvider
from test_handwriting import ink, png_url


@pytest.fixture
def hw_app(app_test, monkeypatch, data_copy):
    from views import ai_ui, handwriting
    pending = {"submit": None}

    def fake_canvas(**kw):
        fake_canvas.calls.append(kw)
        sub, pending["submit"] = pending["submit"], None    # 트리거 값은 그 실행에서만 존재
        return SimpleNamespace(submit=sub)
    fake_canvas.calls = []
    monkeypatch.setattr(handwriting, "handwriting_canvas", fake_canvas)

    def use_provider(provider):
        monkeypatch.setattr(ai_ui, "PROVIDER_OVERRIDE", provider)

    def submit(at, sid, png=None):
        pending["submit"] = {"png": png or png_url(ink()), "submit_id": sid, "strokes": 4, "points": 80,
                             "pointer_types": ["pen", "touch"], "ignored_touch": 3}
        at.run()
        assert not at.exception, at.exception

    def db_rows(table):
        con = sqlite3.connect(data_copy / "wordloop.db")
        con.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in con.execute(f"select * from {table}")]
        finally:
            con.close()

    return SimpleNamespace(app_test=app_test, canvas=fake_canvas, use_provider=use_provider, submit=submit,
                           db_rows=db_rows)


def _current_word(at):
    from services import migrate
    from conftest import ROOT
    words = {w["id"]: w for w in migrate.read_excel_words(str(ROOT / "Word.xlsx"))
             for w in [{**w, "id": migrate.word_uuid("local", w["no"])}]}
    ids = at.session_state.hw_list
    return words[ids[at.session_state.hw_idx % len(ids)]]


def test_ocr_misread_user_fix_then_single_save(hw_app):
    hw_app.use_provider(FakeProvider(handler=lambda prompt, schema: json.dumps(
        {"recognized_text": "zzwrong", "candidates": ["zzwr0ng"], "uncertain": True, "notes": "", "schema_version": 1})))
    at = hw_app.app_test()
    assert hw_app.canvas.calls[-1]["submit_label"] == "AI 인식"
    word = _current_word(at)
    hw_app.submit(at, "sub-1")
    att = at.session_state.hw_att
    assert at.session_state.hw_phase == "confirm"
    box = at.text_input(key=f"hw_text_{att['attempt_id']}")
    assert box.value == "zzwrong"                      # AI 인식값이 미리 채워짐
    assert hw_app.db_rows("review_events") == []       # 확인 전에는 아무것도 저장 안 됨

    box.set_value(word["word"])                        # 사용자가 실제 필기를 보고 수정
    at.button(key="hw_confirm").click().run()
    assert at.session_state.hw_att["correct"] is True and at.session_state.hw_phase == "rate"
    good = at.button(key="hw_rate_3")
    assert good.proto.type == "primary"                # 정답이면 Good 추천
    good.click().run()
    assert not at.exception

    events = hw_app.db_rows("review_events")
    attempts = hw_app.db_rows("writing_attempts")
    assert len(events) == 1 and events[0]["rating"] == 3 and events[0]["mode"] == "handwriting:spell"
    assert len(attempts) == 1 and attempts[0]["ocr_text"] == "zzwrong" and attempts[0]["confirmed_text"] == word["word"]
    assert json.loads(attempts[0]["feedback"])["edited"] is True
    assert at.session_state.hw_phase == "write"        # 다음 문제로 이동
    assert hw_app.canvas.calls[-1]["clear_keys"]       # 완료한 문제 초안 삭제 요청


def test_duplicate_submit_event_processed_once(hw_app):
    calls = []
    hw_app.use_provider(FakeProvider(handler=lambda p, s: calls.append(1) or json.dumps(
        {"recognized_text": "abc", "candidates": [], "uncertain": False})))
    at = hw_app.app_test()
    hw_app.submit(at, "same-id")
    at.session_state.hw_phase = "write"                # 다시 쓰기 상태에서 같은 이벤트가 또 와도
    hw_app.submit(at, "same-id")
    assert len(calls) == 1


def test_ai_failure_keeps_drawing_and_allows_manual_grading(hw_app):
    hw_app.use_provider(FakeProvider(handler=lambda p, s: (_ for _ in ()).throw(AIError("rate_limited", retry_after=99))))
    at = hw_app.app_test()
    word = _current_word(at)
    hw_app.submit(at, "sub-429")
    assert at.session_state.hw_phase == "confirm"
    assert at.session_state.hw_att.get("png")          # 필기 이미지는 남아 있음(재인식/수동 채점 가능)
    assert any("한도" in w.value for w in at.warning)
    at.button(key="hw_manual_ng").click().run()
    assert at.session_state.hw_att["correct"] is False
    assert at.button(key="hw_rate_1").proto.type == "primary"   # 오답이면 Again 추천
    at.button(key="hw_rate_1").click().run()
    ev = hw_app.db_rows("review_events")
    wa = hw_app.db_rows("writing_attempts")
    assert len(ev) == 1 and ev[0]["rating"] == 1 and wa[0]["status"] == "manual"
    assert word["word"]


def test_no_ai_key_direct_input_path(hw_app):
    at = hw_app.app_test()                              # PROVIDER_OVERRIDE 없음 + 키 없음
    assert hw_app.canvas.calls[-1]["submit_label"] == "제출 · 직접 입력"
    word = _current_word(at)
    hw_app.submit(at, "sub-manual")
    att = at.session_state.hw_att
    at.text_input(key=f"hw_text_{att['attempt_id']}").set_value(word["word"].upper())
    at.button(key="hw_confirm").click().run()
    assert at.session_state.hw_att["correct"] is True and at.session_state.hw_att["status"] == "manual"


def test_trace_mode_self_rating_without_ocr(hw_app):
    hw_app.use_provider(FakeProvider(handler=lambda p, s: pytest.fail("따라쓰기는 OCR을 호출하지 않아야 함")))
    at = hw_app.app_test()
    at.radio(key="hw_mode").set_value("따라쓰기").run()
    word = _current_word(at)
    assert hw_app.canvas.calls[-1]["guide"] == word["word"]
    hw_app.submit(at, "sub-trace")
    assert at.session_state.hw_phase == "rate"
    at.button(key="hw_rate_4").click().run()
    assert hw_app.db_rows("writing_attempts")[0]["status"] == "self"


def test_blank_png_is_rejected_without_state_change(hw_app):
    from PIL import Image
    at = hw_app.app_test()
    hw_app.submit(at, "sub-blank", png=png_url(Image.new("RGB", (300, 100), "white")))
    assert at.session_state.hw_phase == "write"
    assert any("비어" in w.value for w in at.warning)
    assert hw_app.db_rows("writing_attempts") == []
