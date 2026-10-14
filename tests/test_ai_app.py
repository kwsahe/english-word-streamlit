"""AI 토익 시험 화면: 일부 문항 검증 실패 → 로컬 대체 문제, 신고 → 캐시 무효화 (FakeProvider)."""
import json
import re
import sqlite3

import pytest

from services.ai import AIError, FakeProvider


def toeic_handler(prompt, schema):
    targets = json.loads(re.search(r"목표 단어: (\[.*?\])\n", prompt).group(1))
    bank = json.loads(re.search(r"선택지 후보 단어: (\[.*\])", prompt).group(1))
    qs = []
    for i, t in enumerate(targets):
        others = [b for b in bank if b.lower() != t["word"].lower()][:3]
        sentence = "Please check the _____ before the meeting." if i == 0 else f"The {t['word']} is _____ here."
        qs.append({"no": t["no"], "sentence": sentence, "choices": [t["word"], *others], "correct": t["word"],
                   "translation": "번역", "explanation": "해설"})
    return json.dumps({"questions": qs})


@pytest.fixture
def ai_app(app_test, monkeypatch):
    from views import ai_ui

    def run(handler):
        monkeypatch.setattr(ai_ui, "PROVIDER_OVERRIDE", FakeProvider(handler=handler))
        return app_test()
    return run


def test_ai_toeic_partial_invalid_falls_back_and_report(ai_app, data_copy):
    at = ai_app(toeic_handler)
    at.radio(key="t_mode").set_value("✨ AI 토익 4지선다").run()
    next(b for b in at.button if b.label == "🚀 시험 시작").click().run()
    assert not at.exception and at.session_state.test_active
    assert at.session_state.test_ai_count == 1                       # 첫 문항만 검증 통과
    data = at.session_state.test_toeic_data
    assert len(data) == len(at.session_state.test_questions)        # 나머지는 대체 문제로 채움
    assert sum(1 for d in data.values() if d.get("ai_generated")) == 1
    at.button(key="FormSubmitter:test_form-✅ 제출하기").click().run()
    reports = [b for b in at.button if (b.key or "").startswith("report_q_")]
    assert len(reports) == 1                                         # 신고 버튼은 AI 문항에만
    reports[0].click().run()
    con = sqlite3.connect(data_copy / "wordloop.db")
    try:
        statuses = [r[0] for r in con.execute("select status from ai_usage")]
        valid = [r[0] for r in con.execute("select valid from ai_cache where feature = 'toeic'")]
    finally:
        con.close()
    assert "reported" in statuses and statuses.count("invalid") == len(data) - 1
    assert valid == [0]                                              # 신고된 문제는 재사용 안 함


def test_ai_toeic_total_failure_keeps_regular_test_usable(ai_app):
    def fail(prompt, schema):
        raise AIError("rate_limited", retry_after=99)
    at = ai_app(fail)
    at.radio(key="t_mode").set_value("✨ AI 토익 4지선다").run()
    next(b for b in at.button if b.label == "🚀 시험 시작").click().run()
    assert not at.session_state.test_active
    assert any("한도" in w.value for w in at.warning)
    at.radio(key="t_mode").set_value("4지선다").run()                 # 무AI 경로는 그대로
    next(b for b in at.button if b.label == "🚀 시험 시작").click().run()
    assert at.session_state.test_active
