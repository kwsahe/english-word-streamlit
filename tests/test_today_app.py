"""🏠 오늘 탭: FSRS 큐 · 빠른 복습 · 목표량 저장 (AppTest, 로컬 모드)."""
import json
import sqlite3


def _rows(data_copy, sql):
    con = sqlite3.connect(data_copy / "wordloop.db")
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def _metric(at, label):
    return next(m.value for m in at.metric if m.label == label)


def test_flashcard_review_saves_once_and_advances(app_test, data_copy):
    at = app_test()
    assert _metric(at, "새 단어") == "10개" and _metric(at, "오늘 완료") == "0회"
    first = at.session_state.today_att["word_id"]
    at.button(key="today_show").click().run()
    good = at.button(key="today_rate_3")
    assert good.proto.type == "primary"            # 자기평가 기본 추천 Good
    good.click().run()
    assert not at.exception
    assert _rows(data_copy, "select count(*) from review_events")[0][0] == 1
    assert at.session_state.today_att["word_id"] != first     # 다음 카드로 이동
    assert _metric(at, "오늘 완료") == "1회"
    assert any("저장됨" in t.value for t in at.toast)


def test_multiple_choice_wrong_suggests_again_and_updates_legacy(app_test, data_copy):
    at = app_test()
    at.radio(key="today_mode").set_value("객관식").run()
    att = at.session_state.today_att
    wrong_idx = next(i for i, c in enumerate(att["choices"]) if c != _word(att["word_id"])["word"])
    at.button(key=f"today_c_{wrong_idx}").click().run()
    assert at.session_state.today_att["correct"] is False
    again = at.button(key="today_rate_1")
    assert again.proto.type == "primary"
    again.click().run()
    ev = _rows(data_copy, "select rating, correct, mode from review_events")
    assert ev == [(1, 0, "today:객관식")]
    progress = json.loads((data_copy / "progress.json").read_text(encoding="utf-8"))
    assert _word(att["word_id"])["no"] in progress["wrong"]   # 기존 오답 표시에도 반영
    # Again 카드는 1분 뒤 만기 → 바로 다시 출제하지 않음
    assert at.session_state.today_att["word_id"] != att["word_id"]


def test_typing_correct(app_test, data_copy):
    at = app_test()
    at.radio(key="today_mode").set_value("타이핑").run()
    word = _word(at.session_state.today_att["word_id"])
    at.text_input(key="today_typed").input(f"  {word['word'].upper()}. ")
    at.button(key="FormSubmitter:today_type-채점").click().run()
    assert at.session_state.today_att["correct"] is True
    at.button(key="today_rate_4").click().run()
    assert _rows(data_copy, "select rating, correct from review_events") == [(4, 1)]


def test_goals_persist_and_shape_queue(app_test, data_copy):
    at = app_test()
    at.slider(key="goal_new").set_value(3)
    at.button(key="goal_save").click().run()
    assert _metric(at, "새 단어") == "3개"
    saved = _rows(data_copy, "select data from settings")[0][0]
    assert json.loads(saved)["goals"]["new_limit"] == 3
    at2 = app_test()                                 # 새 세션(새로고침)에서도 유지
    assert _metric(at2, "새 단어") == "3개"


def test_skip_does_not_record(app_test, data_copy):
    at = app_test()
    first = at.session_state.today_att["word_id"]
    at.button(key="today_skip").click().run()
    assert at.session_state.today_att["word_id"] != first
    assert _rows(data_copy, "select count(*) from review_events")[0][0] == 0


def _word(word_id):
    from conftest import ROOT
    from services import migrate
    for w in migrate.read_excel_words(str(ROOT / "Word.xlsx")):
        if migrate.word_uuid("local", w["no"]) == word_id:
            return w
    raise KeyError(word_id)
