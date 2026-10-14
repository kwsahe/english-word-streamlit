"""✍️ 쓰기 연습 — 갤럭시탭 S펜 필기 → AI 판독 → 사용자 확인 → Python 채점 → FSRS 평가 → 1회 저장."""
import html
import random
import uuid
from datetime import datetime

import streamlit as st

from components.handwriting import handwriting_canvas
from services import study
from services.ai import AIError
from services.config import app_tz, get_int, utcnow
from services.handwriting import HandwritingError, contains_target, decode_submission, is_correct_spelling
from views import account

MODES = {
    "철자 쓰기": "spell",       # 한글 뜻 → 영단어 (OCR → 확인 → Python 비교)
    "따라쓰기": "trace",        # 흐린 가이드 위에 쓰기 (자기평가)
    "받아쓰기": "dictation",    # 발음 듣고 쓰기 (OCR → 확인 → Python 비교)
    "AI 작문": "compose",       # 단어로 1~3문장 (OCR → 확인 → Gemini 교정, 평가는 사용자)
}


# 태블릿 가로: 문제 40% | 캔버스 60%. 세로(또는 좁은 화면): 문제 → 캔버스 세로 스택.
LAYOUT_CSS = """<style>
@media (orientation: portrait), (max-width: 900px) {
  .st-key-hw_layout [data-testid="stHorizontalBlock"] { flex-direction: column; }
  .st-key-hw_layout [data-testid="stColumn"] { width: 100% !important; flex: 1 1 auto !important; }
}
</style>"""


def _humanize(delta_s: float) -> str:
    m = delta_s / 60
    if m < 60:
        return f"{max(1, round(m))}분 후"
    if m < 60 * 24:
        return f"{round(m / 60)}시간 후"
    return f"{round(m / 60 / 24)}일 후"


def _reset_attempt(word_id: str | None = None):
    st.session_state.hw_phase = "write"
    st.session_state.hw_att = {"attempt_id": str(uuid.uuid4()), "word_id": word_id,
                               "started": utcnow().isoformat(), "revealed": False}


def _next(step: int, length: int):
    att = st.session_state.get("hw_att") or {}
    if att.get("draft_key") and st.session_state.get("hw_phase") == "saved":
        st.session_state.hw_clear_keys = (st.session_state.get("hw_clear_keys", []) + [att["draft_key"]])[-20:]
    st.session_state.hw_idx = (st.session_state.hw_idx + step) % max(1, length)
    st.session_state.hw_reset = st.session_state.get("hw_reset", 0) + 1
    _reset_attempt()


def render(*, store, ai, words, all_categories, filter_words, tts_button, on_legacy_result, legacy_wrong: set):
    st.subheader("✍️ 쓰기 연습 · S펜")
    tz = app_tz()
    user_scope = f"wl:{getattr(store, 'user_id', 'local')}:"

    c1, c2 = st.columns([3, 2])
    with c1:
        mode_label = st.radio("모드", list(MODES), horizontal=True, key="hw_mode")
    with c2:
        source = st.radio("문제", ["오늘 복습", "카테고리·범위"], horizontal=True, key="hw_source")
    mode = MODES[mode_label]

    if source == "카테고리·범위":
        f1, f2 = st.columns([3, 2])
        with f1:
            cats = st.multiselect("카테고리", all_categories, default=all_categories, key="hw_cats")
        with f2:
            scope = st.radio("범위", ["전체", "미암기만", "오답만", "정답 맞춘"], horizontal=True, key="hw_scope")
        pool = filter_words(words, cats, scope)
        sig = ("filter", tuple(sorted(cats)), scope)
    else:
        try:
            progress = store.get_progress()
        except Exception:
            st.error("복습 일정을 불러오지 못했습니다(동기화 실패). '카테고리·범위'로 계속 연습할 수 있어요.")
            return
        q = study.build_today_queue(words, progress, utcnow(), tz, new_limit=get_int_setting("hw_new_limit", 10),
                                    review_limit=get_int_setting("hw_review_limit", 30), legacy_wrong=legacy_wrong)
        pool = q["queue"]
        sig = ("today", tuple(w["id"] for w in pool))
        st.caption(f"기한 지남 {len(q['overdue'])} · 지금 복습 {len(q['due_today'])} · 오늘 이따가 {len(q['later_today'])}"
                   f" · 새 단어 {len(q['new'])}/{q['new_total']} (목표량은 🏠 오늘 탭에서 조절)")

    if not pool:
        st.info("지금 쓸 단어가 없어요. 범위를 바꾸거나 '카테고리·범위'를 선택하세요.")
        return
    if st.session_state.get("hw_sig") != sig:
        ids = [w["id"] for w in pool]
        if sig[0] == "filter":
            random.shuffle(ids)
        st.session_state.update(hw_sig=sig, hw_list=ids, hw_idx=0)
        _reset_attempt()
    by_id = {w["id"]: w for w in words}
    ids = [i for i in st.session_state.hw_list if i in by_id]
    if not ids:
        st.session_state.pop("hw_sig", None)
        st.rerun()
    idx = st.session_state.hw_idx % len(ids)
    word = by_id[ids[idx]]
    att = st.session_state.hw_att
    if att.get("word_id") != word["id"] or att.get("mode") != mode:
        _reset_attempt(word["id"])
        att = st.session_state.hw_att
        att["mode"] = mode
    att["draft_key"] = f"{user_scope}{word['id']}:{mode}:v1"
    phase = st.session_state.hw_phase

    st.progress((idx + 1) / len(ids), text=f"{idx + 1} / {len(ids)}")
    st.markdown(LAYOUT_CSS, unsafe_allow_html=True)
    layout = st.container(key="hw_layout")
    left, right = layout.columns([2, 3], gap="medium")
    with left:
        _question_card(word, mode, att, tts_button)
    with right:
        result = handwriting_canvas(
            key="hw_canvas", draft_key=att["draft_key"], user_scope=user_scope,
            guide=word["word"] if mode == "trace" else "", show_guide=mode == "trace",
            pen_only_default=account.device_type() == "tablet",
            submit_label="완료 · 자기평가" if mode == "trace" else ("AI 인식" if ai.enabled else "제출 · 직접 입력"),
            busy=phase != "write", clear_keys=st.session_state.get("hw_clear_keys", []),
            reset_token=st.session_state.get("hw_reset", 0), aspect=0.62 if mode == "compose" else 0.45,
        )
        if phase != "write":
            st.caption("채점이 끝나면 다음 문제로 넘어갑니다. 고쳐 쓰려면 아래 '다시 쓰기'를 누르세요.")
    _handle_submit(result, ai, word, mode, att)
    phase = st.session_state.hw_phase

    if phase == "confirm":
        _confirm_step(ai, word, mode, att)
    if st.session_state.hw_phase == "rate":
        _rate_step(store, ai, word, mode, att, on_legacy_result)

    n1, n2, n3, n4 = st.columns(4)
    if n1.button("⬅️ 이전", key="hw_prev", width="stretch"):
        _next(-1, len(ids)); st.rerun()
    if n2.button("🔍 정답 보기", key="hw_reveal", width="stretch", disabled=att.get("revealed", False)):
        att["revealed"] = True; st.rerun()
    if n3.button("⏭️ 건너뛰기", key="hw_skip", width="stretch"):
        _next(1, len(ids)); st.rerun()
    if n4.button("🔀 섞기", key="hw_shuffle", width="stretch"):
        random.shuffle(st.session_state.hw_list)
        st.session_state.hw_idx = 0
        _reset_attempt(); st.rerun()


def get_int_setting(key: str, default: int) -> int:
    return int(st.session_state.get(key, default))


def _question_card(word, mode, att, tts_button):
    w, m = html.escape(word["word"]), html.escape(word["meaning"])
    if mode == "trace":
        st.markdown(f"<div class='card-front'>{w}</div>", unsafe_allow_html=True)
        st.caption(f"뜻: {word['meaning']} — 흐린 글자를 따라 써 보세요.")
    elif mode == "spell":
        st.markdown(f"<div class='card-front'>{m}</div>", unsafe_allow_html=True)
        st.caption("뜻에 맞는 영어 단어를 S펜으로 쓰세요.")
        if st.toggle("힌트 (첫 글자·길이)", key=f"hw_hint_{word['id']}"):
            st.caption(f"{word['word'][0]} " + " ".join("_" if c != " " else "/" for c in word["word"][1:])
                       + f"  ({len(word['word'].replace(' ', ''))}글자)")
    elif mode == "dictation":
        st.markdown("<div class='card-front'>🎧 듣고 쓰기</div>", unsafe_allow_html=True)
        st.caption("발음을 듣고 들은 단어를 쓰세요. (기기 브라우저 음성 사용)")
    else:
        st.markdown(f"<div class='card-front'>{w}</div>", unsafe_allow_html=True)
        st.caption(f"뜻: {word['meaning']} — 이 단어를 넣어 영어 문장 1~3개를 쓰세요.")
    if mode != "spell" or att.get("revealed"):
        tts_button(word["word"], key=f"tts_hw_{word['id']}")
    if att.get("revealed"):
        st.markdown(f"<div class='card-back'>{w}<br><small>{m}</small></div>", unsafe_allow_html=True)
    st.caption(f"카테고리: {word['category']} · No.{word['no']}")


def _handle_submit(result, ai, word, mode, att):
    sub = getattr(result, "submit", None)
    processed = st.session_state.setdefault("hw_processed", set())
    if not sub or sub.get("submit_id") in processed or st.session_state.hw_phase != "write":
        return
    processed.add(sub.get("submit_id"))
    try:
        png, _size = decode_submission(sub.get("png", ""), max_bytes=get_int("HANDWRITING_MAX_BYTES"),
                                       max_side=get_int("HANDWRITING_MAX_SIDE"))
    except HandwritingError as exc:
        st.warning(str(exc))
        return
    att.update(png=png, input={k: sub.get(k) for k in ("strokes", "points", "pointer_types", "ignored_touch")})
    if mode == "trace":
        att.update(text="", status="self", correct=None)
        st.session_state.hw_phase = "rate"
        return
    st.session_state.hw_phase = "confirm"
    _run_ocr(ai, att)


def _run_ocr(ai, att):
    att.pop("ocr", None)
    att.pop("ocr_error", None)
    if not ai.enabled:
        att["ocr_error"] = "AI가 꺼져 있어 직접 입력해야 합니다."
        return
    try:
        with st.spinner("AI가 필기를 읽는 중…"):
            ocr = ai.ocr(att["png"])
        att["ocr"] = ocr.model_dump()
        att["ocr"]["model"] = ai.last_model
        att["text_seed"] = ocr.recognized_text
    except AIError as exc:
        att["ocr_error"] = exc.user_message


def _confirm_step(ai, word, mode, att):
    st.markdown("#### 인식 결과 확인")
    c_img, c_txt = st.columns([2, 3])
    with c_img:
        st.image(att["png"], caption="제출한 필기 (이 기기 화면에서만 사용, DB에 저장 안 함)", width="stretch")
    with c_txt:
        ocr = att.get("ocr")
        if ocr:
            msg = "AI가 읽은 글자입니다. 실제로 쓴 글자와 다르면 고친 뒤 확정하세요."
            if ocr.get("uncertain"):
                msg += " ⚠️ 불확실한 글자가 있어요."
            st.info(msg)
            if ocr.get("candidates"):
                st.caption("다른 후보: " + ", ".join(ocr["candidates"]))
            if ocr.get("notes"):
                st.caption(f"메모: {ocr['notes']}")
            if ocr.get("model") and ocr["model"] != ai.model_main:
                st.caption(f"※ 기본 모델이 응답하지 않아 보조 모델({ocr['model']})로 인식했습니다.")
        elif att.get("ocr_error"):
            st.warning(f"{att['ocr_error']} 필기는 그대로 남아 있어요. 직접 입력하거나 수동 채점하세요.")
        key = f"hw_text_{att['attempt_id']}"
        if key not in st.session_state:
            st.session_state[key] = att.get("text_seed", "")
        label = "내가 쓴 문장 (확인·수정)" if mode == "compose" else "내가 쓴 철자 (확인·수정)"
        text = st.text_area(label, key=key, height=90) if mode == "compose" else st.text_input(label, key=key)

        b1, b2, b3 = st.columns(3)
        # 비활성화하지 않는다: 태블릿에서 입력 직후 바로 누르면 값 반영 전 상태로 계산되기 때문
        if b1.button("✅ 이 답으로 확정", key="hw_confirm", type="primary", width="stretch"):
            if not text.strip():
                st.warning("확정할 답을 입력하세요. AI 없이 채점하려면 아래 버튼을 쓰세요.")
                return
            if mode == "compose":
                correct = contains_target(text, word["word"])
            else:
                correct = is_correct_spelling(text, word["word"])
            edited = bool(ocr) and text.strip() != (ocr.get("recognized_text") or "").strip()
            att.update(text=text.strip(), correct=correct, status="ocr" if ocr else "manual", edited=edited)
            st.session_state.hw_phase = "rate"
            st.rerun()
        if b2.button("🔄 다시 인식", key="hw_reocr", width="stretch", disabled=not ai.enabled):
            _run_ocr(ai, att)
            st.session_state.pop(key, None)
            st.rerun()
        if b3.button("✍️ 다시 쓰기", key="hw_rewrite", width="stretch"):
            st.session_state.hw_phase = "write"  # 캔버스 획은 그대로 남아 있다
            st.rerun()
        if mode != "compose":
            st.caption("AI 없이 채점하기:")
            m1, m2 = st.columns(2)
            if m1.button("⭕ 맞게 썼어요", key="hw_manual_ok", width="stretch"):
                att.update(text=text.strip(), correct=True, status="manual", edited=False)
                st.session_state.hw_phase = "rate"; st.rerun()
            if m2.button("❌ 틀렸어요", key="hw_manual_ng", width="stretch"):
                att.update(text=text.strip(), correct=False, status="manual", edited=False)
                st.session_state.hw_phase = "rate"; st.rerun()


def _rate_step(store, ai, word, mode, att, on_legacy_result):
    st.markdown("#### 결과 · 학습 평가")
    correct = att.get("correct")
    if mode == "trace":
        st.info("따라쓰기는 자기평가입니다. 얼마나 쉽게 썼는지 골라 주세요.")
    elif correct:
        st.success(f"정답! **{word['word']}** — {word['meaning']}")
    elif mode == "compose":
        st.warning(f"문장에 목표 단어 **{word['word']}**(또는 기본 변화형)가 보이지 않아요.")
    else:
        st.error(f"오답 — 내 답: `{att.get('text') or '(빈칸)'}` · 정답: **{word['word']}** ({word['meaning']})")
    if mode == "compose" and att.get("text"):
        _compose_feedback(ai, word, att)
    if word.get("example"):
        with st.expander("📖 예문"):
            st.write(word["example"])

    now = utcnow()
    try:
        row = store.get_progress_one(word["id"])
    except Exception:
        row = None
    previews = study.preview_due(row, now)
    suggested = 1 if att.get("revealed") and mode != "trace" else study.suggested_rating(correct)
    st.caption("기억한 정도를 고르면 저장되고 다음 복습 시점이 정해집니다. (추천: 강조된 버튼)")
    cols = st.columns(4)
    for r, col in zip((1, 2, 3, 4), cols):
        label = f"{study.RATING_LABELS[r]} · {_humanize((previews[r] - now).total_seconds())}"
        if col.button(label, key=f"hw_rate_{r}", width="stretch", type="primary" if r == suggested else "secondary"):
            _save(store, word, mode, att, r, now, on_legacy_result)


def _compose_feedback(ai, word, att):
    fb = att.get("feedback")
    if fb is None and ai.enabled:
        if st.button("✨ AI 문장 교정 받기", key="hw_fb"):
            try:
                with st.spinner("AI가 문장을 살펴보는 중…"):
                    att["feedback"] = ai.writing_feedback(att["text"], word["word"], word["meaning"]).model_dump()
                st.rerun()
            except AIError as exc:
                st.warning(exc.user_message)
    if fb:
        st.markdown(f"**교정 문장:** {html.escape(fb['corrected'])}", unsafe_allow_html=True)
        for issue in fb.get("issues", []):
            st.caption(f"• [{issue['kind']}] {issue['original']} → {issue['suggestion']}: {issue['explanation_ko']}")
        if fb.get("natural_alternative"):
            st.caption(f"더 자연스러운 표현: {fb['natural_alternative']}")
        st.caption(f"AI 요약: {fb['summary_ko']} (AI 피드백은 참고용이며 정답을 보증하지 않습니다)")


def _save(store, word, mode, att, rating, now, on_legacy_result):
    started = datetime.fromisoformat(att["started"])
    duration = int(min((now - started).total_seconds(), 3600) * 1000)
    feedback = {k: att[k] for k in ("input", "edited", "revealed") if k in att}
    if att.get("feedback"):
        feedback["ai"] = att["feedback"]
    if att.get("ocr"):
        feedback["ocr_uncertain"] = att["ocr"].get("uncertain")
    writing_row = {"attempt_id": att["attempt_id"], "word_id": word["id"], "mode": mode,
                   "ocr_text": (att.get("ocr") or {}).get("recognized_text"), "confirmed_text": att.get("text"),
                   "feedback": feedback, "status": att.get("status", "manual"), "correct": att.get("correct"),
                   "created_at": now}

    def write():
        store.add_writing_attempt(writing_row)
        return study.submit_review(store, word_id=word["id"], rating=rating, mode=f"handwriting:{mode}",
                                   correct=att.get("correct"), attempt_id=att["attempt_id"], now=now,
                                   duration_ms=duration, device_type=account.device_type(),
                                   session_id=st.session_state.setdefault("hw_session_id", str(uuid.uuid4())))
    try:
        res = account.save_with_status("필기 복습", write, queue=True)
    except study.ReviewConflict as exc:
        st.error(str(exc))
        return
    if res:
        due = res["due_at"].astimezone(app_tz()).strftime("%m/%d %H:%M")
        st.toast(f"저장됨 · 다음 복습 {due}" + (" (이미 저장된 기록)" if res["status"] == "duplicate" else ""))
        if att.get("correct") is not None:
            on_legacy_result(word["no"], att["correct"])
    else:
        st.toast("동기화 실패 — 미전송 큐에 보관했습니다. 사이드바에서 재전송하세요.")
    st.session_state.hw_phase = "saved"
    _next(1, len(st.session_state.hw_list))
    st.rerun()
