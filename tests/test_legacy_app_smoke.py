"""기존 7개 학습 기능 회귀 테스트 (Gemini 키·Supabase 없이 실행)."""
import json

import openpyxl

LEGACY_TABS = ["📖 학습", "✍️ 쓰기 연습", "📝 시험", "♾️ 무한", "📋 단어장", "✏️ 단어 관리", "📊 통계"]


def _button(at, label):
    return next(b for b in at.button if b.label == label)


def test_all_legacy_tabs_render_without_ai(app_test):
    at = app_test()
    labels = [t.label for t in at.tabs]
    for tab in LEGACY_TABS:
        assert tab in labels
    # 키가 없으면 AI 전용 버튼은 숨겨지고 일반 학습은 동작해야 한다.
    assert not any("AI" in b.label for b in at.button)
    assert "✨ AI 토익 4지선다" not in at.radio(key="t_mode").options


def test_flashcard_reveal_and_memorize(app_test, data_copy):
    at = app_test()
    before = set(at.session_state.memorized)
    _button(at, "🔍 정답 보기").click().run()
    assert not at.exception
    assert any("card-back" in m.value for m in at.markdown)
    toggle = next(b for b in at.button if b.label in ("✅ 암기 완료", "↩️ 암기 취소"))
    toggle.click().run()
    saved = set(json.loads((data_copy / "progress.json").read_text(encoding="utf-8"))["memorized"])
    assert saved != before and saved == set(at.session_state.memorized)


def test_regular_multiple_choice_test_records_session(app_test, data_copy):
    at = app_test()
    before = len(json.loads((data_copy / "progress.json").read_text(encoding="utf-8"))["sessions"])
    at.radio(key="t_mode").set_value("4지선다").run()
    _button(at, "🚀 시험 시작").click().run()
    assert at.session_state.test_active
    at.button(key="FormSubmitter:test_form-✅ 제출하기").click().run()
    assert not at.exception
    assert at.session_state.test_submitted
    after = json.loads((data_copy / "progress.json").read_text(encoding="utf-8"))["sessions"]
    assert len(after) == before + 1


def test_subjective_and_toeic_modes_start(app_test):
    at = app_test()
    for mode in ("주관식", "토익식 빈칸"):
        at.radio(key="t_mode").set_value(mode).run()
        _button(at, "🚀 시험 시작").click().run()
        assert not at.exception and at.session_state.test_active
        _button(at, "❌ 시험 취소").click().run()


def test_infinite_test_answer_flow(app_test):
    at = app_test()
    _button(at, "🚀 무한 시험 시작").click().run()
    assert at.session_state.inf_active
    at.button(key="inf_c_0").click().run()
    assert not at.exception
    assert at.session_state.inf_session_total == 1


def test_word_add_edit_delete_in_excel_copy(app_test, data_copy):
    at = app_test()
    at.text_input(key="add_word_input").input("zzqtestword").run()
    # 폼 안 위젯은 제출과 같은 실행에서 값이 확정된다.
    at.text_input(key="add_meaning_input").input("테스트 뜻")
    at.button(key="FormSubmitter:add_word_form-➕ 추가하기").click().run()
    assert not at.exception
    ws = openpyxl.load_workbook(data_copy / "Word.xlsx")["영어 단어장"]
    assert any(r[1] == "zzqtestword" for r in ws.iter_rows(min_row=2, values_only=True))

    at.radio(key="mgmt_action").set_value("🗑️ 단어 삭제").run()
    at.text_input(key="del_search").input("zzqtestword").run()
    next(b for b in at.button if b.key and b.key.startswith("del_btn_")).click().run()
    _button(at, "🗑️ 삭제 확인").click().run()
    ws = openpyxl.load_workbook(data_copy / "Word.xlsx")["영어 단어장"]
    assert not any(r[1] == "zzqtestword" for r in ws.iter_rows(min_row=2, values_only=True))


def test_wordbook_and_stats_render(app_test):
    at = app_test()
    assert len(at.dataframe) >= 2  # 단어장 + 통계 표
    at.text_input(key="wb_search").input("a").run()
    assert not at.exception


def test_db_mode_signup_import_and_cross_device(data_copy):
    """로그인 모드: 가입 → Word.xlsx 가져오기 → 암기 체크 → 다른 기기(새 세션) 로그인 시 동일."""
    import os
    import uuid

    import pytest
    from streamlit.testing.v1 import AppTest

    from conftest import ROOT
    url, key = os.environ.get("WORDLOOP_TEST_SUPABASE_URL"), os.environ.get("WORDLOOP_TEST_SUPABASE_ANON_KEY")
    if not (url and key):
        pytest.skip("Supabase 테스트 DB 미설정")
    email, pw = f"wl-app-{uuid.uuid4().hex[:8]}@example.com", "test-password-123"

    def device():
        at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)
        at.secrets["SUPABASE_URL"], at.secrets["SUPABASE_ANON_KEY"] = url, key
        at.run()
        return at

    pc = device()
    assert "처음 사용 (가입)" in [t.label for t in pc.tabs]      # 로그인 전에는 학습 화면이 보이지 않음
    assert "📖 학습" not in [t.label for t in pc.tabs]
    pc.text_input(key="wl_signup_email").input(email)
    pc.text_input(key="wl_signup_pw").input(pw)
    pc.button(key="FormSubmitter:wl_signup-가입하기").click().run()
    import_btn = next(b for b in pc.button if b.label.startswith("📥") and "단어 가져오기" in b.label)
    import_btn.click().run()
    assert not pc.exception
    assert all(t in [x.label for x in pc.tabs] for t in LEGACY_TABS)
    next(b for b in pc.button if b.label == "✅ 암기 완료").click().run()
    memorized = set(pc.session_state.memorized)
    assert len(memorized) == 1
    # progress.json이 있으면 1회 가져오기 버튼이 보여야 한다
    assert any(b.key == "wl_import_progress" for b in pc.button)

    tablet = device()
    tablet.text_input(key="wl_login_email").input(email)
    tablet.text_input(key="wl_login_pw").input(pw)
    tablet.button(key="FormSubmitter:wl_login-로그인").click().run()
    assert not tablet.exception
    assert set(tablet.session_state.memorized) == memorized
