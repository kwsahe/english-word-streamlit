"""📊 학습 분석 대시보드 — FSRS·필기·AI 지표. 표본 수를 같이 보여주고, 모델 추정치는 따로 표시한다."""
from datetime import timedelta

import pandas as pd
import streamlit as st

from services import analytics, study
from services.config import app_tz, utcnow
from services.store import StoreError


def _pct(v):
    return "—" if v is None else f"{v * 100:.0f}%"


def render(*, store, words):
    st.markdown("### 📈 학습 분석 (FSRS · S펜 · AI)")
    now, tz = utcnow(), app_tz()
    try:
        events = store.list_events(now - timedelta(days=30))
        attempts = store.list_writing_attempts(now - timedelta(days=30))
        usage = store.list_ai_usage(now - timedelta(days=30))
        progress = store.get_progress()
    except StoreError:
        st.error("분석 데이터를 불러오지 못했습니다(동기화 실패). 아래 기존 통계는 그대로 볼 수 있어요.")
        return
    q = study.build_today_queue(words, progress, now, tz, new_limit=10**6, review_limit=10**6)
    m7 = analytics.review_metrics(events, now, tz, 7)
    m30 = analytics.review_metrics(events, now, tz, 30)
    outcomes = analytics.word_outcomes(events)
    hw = analytics.handwriting_metrics(attempts)
    ai = analytics.ai_metrics(usage, now)
    ret = analytics.predicted_retention(progress, now)
    today_start, _ = study.day_bounds(now, tz)

    c = st.columns(4)
    c[0].metric("전체 단어", f"{len(words)}개")
    c[1].metric("오늘 복습 예정", f"{len(q['overdue']) + len(q['due_today']) + len(q['later_today'])}개")
    c[2].metric("오늘 복습 완료", f"{sum(1 for e in events if e['created_at'] >= today_start)}회")
    c[3].metric("FSRS 학습 시작 단어", f"{len(progress)}개", help="한 번 이상 새 복습(FSRS)을 한 단어")

    c = st.columns(4)
    c[0].metric("7일 정답률(실측)", _pct(m7["accuracy"]), help=f"채점 {m7['graded']}회 기준")
    c[1].metric("30일 정답률(실측)", _pct(m30["accuracy"]), help=f"채점 {m30['graded']}회 기준")
    c[2].metric("오답 회복률", _pct(outcomes["recovery"]),
                help=f"틀린 적 있는 단어 {outcomes['wrong_words']}개 중 이후 다시 맞힌 비율")
    c[3].metric("한 번이라도 맞힌 비율", _pct(outcomes["once_correct"]),
                help=f"채점된 단어 {outcomes['graded_words']}개 기준 (회복률과 다른 지표)")

    c = st.columns(4)
    c[0].metric("복습 이행률(30일)", _pct(m30["adherence"]), help=f"만기 당일까지 수행한 비율, 표본 {m30['adherence_n']}회")
    c[1].metric("예상 기억 유지율", _pct(ret["mean"]),
                help=f"FSRS 모델 추정치(카드 {ret['cards']}개 평균). 실측 정답률이 아닙니다.")
    c[2].metric("S펜 필기 시도(30일)", f"{hw['attempts']}회", help=f"AI 인식 {hw['ocr']} · 수동 채점 {hw['manual']} · 따라쓰기 {hw['self']}")
    c[3].metric("OCR 결과 사용자 수정률", _pct(hw["user_correction_rate"]), help=f"AI 인식 {hw['ocr']}회 중 수정 후 확정한 비율")

    if m30["series"]:
        df = pd.DataFrame(m30["series"]).set_index("date")
        st.caption("최근 30일 일별 복습 횟수 / 정답률")
        left, right = st.columns(2)
        left.bar_chart(df[["reviews"]], height=200)
        right.line_chart(df[["accuracy"]].dropna(), height=200)
    else:
        st.info("아직 새 복습(FSRS) 기록이 없습니다. 🏠 오늘 탭이나 ✍️ 쓰기 연습에서 복습하면 지표가 쌓입니다.")

    with st.expander("🤖 AI 사용량 · 품질 (최근 30일)"):
        a = st.columns(4)
        a[0].metric("최근 24시간 요청", f"{ai['calls_24h']}회")
        a[1].metric("응답 형식 통과율", _pct(ai["schema_pass_rate"]))
        a[2].metric("캐시 적중률", _pct(ai["cache_hit_rate"]))
        a[3].metric("오류율", _pct(ai["error_rate"]))
        st.caption(f"30일 실제 호출 {ai['calls']}회 · 신고 {ai['reported']}건(생성 대비 {_pct(ai['report_rate'])}) · "
                   f"토큰 입력 {ai['tokens_in']:,} / 출력 {ai['tokens_out']:,} (API 응답 메타데이터 기준)")

    feedback = [a for a in attempts if a.get("mode") == "compose" and (a.get("feedback") or {}).get("ai")]
    if feedback:
        with st.expander(f"✍️ AI 작문 교정 기록 ({len(feedback)}건)"):
            by_id = {w["id"]: w["word"] for w in words}
            st.dataframe(pd.DataFrame([{
                "단어": by_id.get(str(a["word_id"]), "?"), "내 문장": a.get("confirmed_text"),
                "교정": a["feedback"]["ai"].get("corrected"), "요약": a["feedback"]["ai"].get("summary_ko"),
            } for a in feedback[-20:]]), hide_index=True, width="stretch")
    st.caption("※ 표본이 적을 때의 비율은 크게 흔들립니다. FSRS 효과 비교 방법은 docs/AI_EVALUATION.md 참고.")
