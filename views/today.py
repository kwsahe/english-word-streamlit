"""🏠 오늘 — FSRS 오늘 복습 현황 + 빠른 복습(플래시카드 · 객관식 · 타이핑)."""
import html
import uuid
from datetime import timedelta

import streamlit as st

from services import study
from services.config import app_tz, utcnow
from services.handwriting import is_correct_spelling
from services.store import StoreError
from views import account

DEFAULT_GOALS = {"new_limit": 10, "review_limit": 30}


def goals(store) -> dict:
    if "wl_goals" not in st.session_state:
        try:
            saved = store.get_settings().get("goals", {})
        except StoreError:
            saved = {}
        st.session_state.wl_goals = {**DEFAULT_GOALS, **saved}
    return st.session_state.wl_goals


def render(*, store, words, make_choices, on_legacy_result, legacy_wrong: set):
    st.subheader("🏠 오늘의 복습")
    now, tz = utcnow(), app_tz()
    g = goals(store)
    try:
        progress = store.get_progress()
        events = store.list_events(now - timedelta(days=7))
    except StoreError:
        st.error("복습 기록을 불러오지 못했습니다(동기화 실패). 아래 기존 학습 탭은 그대로 쓸 수 있어요.")
        return
    recent_wrong = {e["word_id"] for e in events if e.get("correct") is False}
    q = study.build_today_queue(words, progress, now, tz, new_limit=g["new_limit"], review_limit=g["review_limit"],
                                legacy_wrong=legacy_wrong, recent_wrong_ids=recent_wrong)
    graded = [e for e in events if e.get("correct") is not None]
    acc = f"{sum(e['correct'] for e in graded) / len(graded) * 100:.0f}%" if graded else "기록 없음"
    today_start, _ = study.day_bounds(now, tz)
    done_today = sum(1 for e in events if e["created_at"] >= today_start)

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("기한 지남", f"{len(q['overdue'])}개")
    m2.metric("지금 복습", f"{len(q['due_today'])}개", help="오늘 만기이고 지금 풀 수 있는 카드")
    m3.metric("새 단어", f"{len(q['new'])}개", help=f"아직 FSRS 기록이 없는 단어 {q['new_total']}개 중 오늘 목표량")
    m4.metric("오늘 완료", f"{done_today}회")
    m5.metric("최근 7일 정답률", acc, help=f"채점된 {len(graded)}회 기준 (실측)")
    st.caption(f"예상 소요 약 {study.estimate_minutes(len(q['queue']), events)}분 · 오늘 이따가 만기 "
               f"{len(q['later_today'])}개 · 순서: 기한 지남 → 지금 만기 → 새 단어")
    if q["repeat_wrong"]:
        st.caption("🔁 반복 오답(추가 연습 추천): " + ", ".join(w["word"] for w in q["repeat_wrong"][:8]))

    with st.expander("⚙️ 하루 목표량 (제안값 — 언제든 바꿀 수 있어요)"):
        c1, c2 = st.columns(2)
        new_limit = c1.slider("새 단어 / 일", 0, 50, g["new_limit"], key="goal_new")
        review_limit = c2.slider("복습 / 일", 5, 200, g["review_limit"], key="goal_review")
        if st.button("목표 저장", key="goal_save"):
            st.session_state.wl_goals = {"new_limit": new_limit, "review_limit": review_limit}
            account.save_with_status("목표량", store.save_settings,
                                     {**_safe_settings(store), "goals": st.session_state.wl_goals})
            st.rerun()

    st.divider()
    st.markdown("#### ⚡ 빠른 복습")
    st.caption("S펜으로 복습하려면 **✍️ 쓰기 연습** 탭 → '오늘 복습'을 고르세요. 같은 큐를 씁니다.")
    mode = st.radio("방식", ["플래시카드", "객관식", "타이핑"], horizontal=True, key="today_mode")
    skipped = st.session_state.setdefault("today_skipped", set())
    queue = [w for w in q["queue"] if w["id"] not in skipped]
    if not queue:
        st.success("오늘 할 복습을 모두 마쳤어요! 🎉 (건너뛴 카드는 새로고침하면 다시 나옵니다)")
        return
    word = queue[0]
    att = st.session_state.get("today_att")
    if not att or att["word_id"] != word["id"] or att["mode"] != mode:
        att = st.session_state.today_att = {"word_id": word["id"], "mode": mode, "attempt_id": str(uuid.uuid4()),
                                            "started": now, "correct": None, "shown": False}
    row = progress.get(word["id"])
    st.caption(f"남은 카드 {len(queue)}개 · {'복습' if row else '새 단어'} · No.{word['no']} · {word['category']}")
    st.markdown(f"<div class='card-front'>{html.escape(word['meaning'] if mode != '플래시카드' else word['word'])}</div>",
                unsafe_allow_html=True)

    if mode == "플래시카드":
        if not att["shown"] and st.button("👀 뜻 확인", key="today_show", type="primary", width="stretch"):
            att["shown"] = True
            st.rerun()
        if att["shown"]:
            st.markdown(f"<div class='card-back'>{html.escape(word['meaning'])}</div>", unsafe_allow_html=True)
    elif mode == "객관식":
        if "choices" not in att:
            att["choices"], _ = make_choices(word, "뜻 → 영어", words)
        if not att["shown"]:
            cols = st.columns(2)
            for i, choice in enumerate(att["choices"]):
                if cols[i % 2].button(choice, key=f"today_c_{i}", width="stretch"):
                    att.update(shown=True, answer=choice, correct=choice == word["word"])
                    st.rerun()
    else:
        if not att["shown"]:
            with st.form("today_type", clear_on_submit=True):
                typed = st.text_input("영어 단어를 입력하세요", key="today_typed")
                if st.form_submit_button("채점", type="primary", width="stretch"):
                    att.update(shown=True, answer=typed, correct=is_correct_spelling(typed, word["word"]))
                    st.rerun()

    if att["shown"]:
        if att["correct"] is True:
            st.success(f"정답! **{word['word']}** — {word['meaning']}")
        elif att["correct"] is False:
            st.error(f"오답 — 내 답: `{att.get('answer') or '(빈칸)'}` · 정답: **{word['word']}**")
        _rating_buttons(store, word, row, att, mode, on_legacy_result)
    if st.button("⏭️ 이 카드 건너뛰기", key="today_skip"):
        skipped.add(word["id"])
        st.session_state.pop("today_att", None)
        st.rerun()


def _safe_settings(store) -> dict:
    try:
        return store.get_settings()
    except StoreError:
        return {}


def _rating_buttons(store, word, row, att, mode, on_legacy_result):
    now = utcnow()
    previews = study.preview_due(row, now)
    suggested = study.suggested_rating(att["correct"])
    st.caption("기억한 정도를 고르면 저장되고 다음 복습 시점이 정해집니다.")
    cols = st.columns(4)
    for r, col in zip((1, 2, 3, 4), cols):
        delta = (previews[r] - now).total_seconds() / 60
        when = f"{round(delta)}분" if delta < 60 else (f"{round(delta / 60)}시간" if delta < 1440 else f"{round(delta / 1440)}일")
        if col.button(f"{study.RATING_LABELS[r]} · {when} 후", key=f"today_rate_{r}", width="stretch",
                      type="primary" if r == suggested else "secondary"):
            duration = int(min((now - att["started"]).total_seconds(), 3600) * 1000)
            try:
                res = account.save_with_status(
                    "오늘 복습", study.submit_review, store, word_id=word["id"], rating=r,
                    mode=f"today:{mode}", correct=att["correct"], attempt_id=att["attempt_id"], now=now,
                    duration_ms=duration, device_type=account.device_type(), queue=True)
            except study.ReviewConflict as exc:
                st.error(str(exc))
                return
            if res:
                st.toast(f"저장됨 · 다음 복습 {res['due_at'].astimezone(app_tz()).strftime('%m/%d %H:%M')}")
                if att["correct"] is not None:
                    on_legacy_result(word["no"], att["correct"])
            else:
                st.toast("동기화 실패 — 미전송 큐에 보관했습니다.")
                st.session_state.setdefault("today_skipped", set()).add(word["id"])  # 같은 카드 반복 방지
            st.session_state.pop("today_att", None)
            st.rerun()
