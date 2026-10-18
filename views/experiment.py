"""🧪 FSRS vs 무작위 복습 실험 패널 (오늘 탭 아래)."""
import json
import random
from datetime import timedelta

import streamlit as st

from services import experiment
from services.config import app_tz, parse_dt, utcnow
from services.handwriting import is_correct_spelling
from services.store import StoreError
from views import account


def load(store) -> dict | None:
    try:
        return store.get_settings().get("experiment")
    except StoreError:
        return None


def save(store, exp: dict | None) -> bool:
    try:
        settings = store.get_settings()
    except StoreError:
        return False
    settings = {**settings, "experiment": exp}
    if exp is None:
        settings.pop("experiment")
    account.save_with_status("실험 기록", store.save_settings, settings)
    return st.session_state.wl_sync["state"] == "saved"


def render(*, store, words, progress, events):
    now = utcnow()
    exp = load(store)
    p = experiment.phase(exp, now)
    with st.expander("🧪 FSRS vs 무작위 복습 실험" + (f" — 진행 중({_label(p)})" if p in
                                                      ("learning", "waiting", "posttest") else ""),
                     expanded=p == "posttest"):
        if p is None:
            _start_form(store, words, progress, now)
        elif p == "learning":
            start = parse_dt(exp["started_at"])
            day = (now - start).days + 1
            res = experiment.analyze(exp, events)
            st.write(f"학습 기간 {day}/{exp['learn_days']}일째 · FSRS군 {len(exp['fsrs'])}개 / 무작위군 {len(exp['random'])}개")
            st.caption(f"누적 복습: FSRS군 {res['fsrs']['reviews']}회 · 무작위군 {res['random']['reviews']}회. "
                       "무작위군 단어는 위 '빠른 복습'에 FSRS군 복습 횟수만큼 섞여 나옵니다(🧪 표시).")
            _abort(store)
        elif p == "waiting":
            test_at = parse_dt(exp["started_at"]) + timedelta(days=exp["learn_days"] + exp["delay_days"])
            st.info(f"대기 기간: 두 군 모두 출제하지 않습니다. 재시험은 "
                    f"{test_at.astimezone(app_tz()).strftime('%m/%d %H:%M')}부터 할 수 있어요.")
            _abort(store)
        elif p == "posttest":
            _posttest(store, words, exp)
        else:
            _result(store, exp, events)


def _label(p):
    return {"learning": "학습", "waiting": "대기", "posttest": "재시험"}[p]


def _start_form(store, words, progress, now):
    fresh = sum(1 for w in words if w["id"] not in progress)
    st.write("아직 FSRS로 복습하지 않은 단어를 무작위로 두 군으로 나눠, **FSRS 일정**과 **무작위 복습**을 "
             "같은 복습 횟수로 비교합니다. 학습 기간이 끝나고 대기 기간 뒤에 두 군을 같은 방식으로 재시험합니다.")
    st.caption(f"실험에 쓸 수 있는 단어: {fresh}개. 1명 실험이라 결과를 일반화할 수 없고, 단어 수가 적으면 차이를 검출하기 어렵습니다. "
               "기존 학습 탭(플래시카드·시험)에서 실험 단어가 나오면 두 군에 똑같이 영향을 줍니다.")
    if fresh < 20:
        st.warning("실험하려면 FSRS 기록이 없는 단어가 20개 이상 필요합니다.")
        return
    c1, c2, c3 = st.columns(3)
    hi = min(200, fresh - fresh % 2)
    n = c1.slider("실험 단어 수", 20, hi, min(80, hi), step=2, key="exp_n") if hi > 20 else 20
    learn = c2.slider("학습 기간(일)", 7, 28, 14, key="exp_learn")
    delay = c3.slider("재시험까지 대기(일)", 3, 14, 7, key="exp_delay")
    if st.button("🧪 실험 시작", key="exp_start", type="primary"):
        exp = experiment.create(words, progress, n=n, seed=random.randrange(1, 10**9), now=now,
                                learn_days=learn, delay_days=delay)
        if save(store, exp):
            st.rerun()
        st.error("실험을 저장하지 못했습니다(동기화 실패).")


def _abort(store):
    if st.checkbox("실험 중단하기", key="exp_abort_check"):
        if st.button("중단 확인 (기록은 남고 분석에서 제외)", key="exp_abort"):
            exp = load(store)
            exp["status"] = "aborted"
            if save(store, exp):
                st.rerun()


def _posttest(store, words, exp):
    by_id = {w["id"]: w for w in words}
    total = len(exp["fsrs"]) + len(exp["random"])
    done = len(exp["posttest"])
    st.progress(done / total, text=f"재시험 {done} / {total}")
    wid = experiment.next_posttest(exp)
    while wid and wid not in by_id:  # 실험 중 삭제된 단어는 오답이 아니라 제외로 기록
        exp["posttest"][wid] = None
        wid = experiment.next_posttest(exp)
    if wid is None:
        exp["posttest"] = {k: v for k, v in exp["posttest"].items() if v is not None}
        exp["status"] = "done"
        if save(store, exp):
            st.rerun()
        return
    st.caption("뜻을 보고 영어 철자를 입력하세요. 결과는 실험 기록에만 저장되고 복습 일정에는 반영되지 않습니다.")
    st.markdown(f"### {by_id[wid]['meaning']}")
    with st.form("exp_post", clear_on_submit=True):
        typed = st.text_input("영어 철자", key="exp_post_typed")
        if st.form_submit_button("제출", type="primary"):
            exp["posttest"][wid] = is_correct_spelling(typed, by_id[wid]["word"])
            if save(store, exp):
                st.rerun()
            st.error("저장하지 못했습니다(동기화 실패). 다시 제출하세요.")


def _result(store, exp, events):
    if exp["status"] == "aborted":
        st.info("중단된 실험입니다. 분석하지 않습니다.")
    else:
        res = experiment.analyze(exp, events)
        st.markdown("#### 결과 (실측)")
        st.table([{"군": name, "단어": res[g]["n"], "재시험 응시": res[g]["tested"],
                   "재시험 정답률": _pct(res[g]["posttest_accuracy"]), "학습 중 복습": res[g]["reviews"],
                   "학습 중 정답률": _pct(res[g]["learning_accuracy"])}
                  for g, name in (("fsrs", "FSRS"), ("random", "무작위"))])
        if res["diff"] is not None:
            lo, hi = res["ci95"]
            st.write(f"정답률 차이(FSRS − 무작위): **{res['diff'] * 100:+.1f}%p**, "
                     f"부트스트랩 95% 신뢰구간 [{lo * 100:+.1f}, {hi * 100:+.1f}]%p")
            st.caption("신뢰구간이 0을 포함하면 이 표본으로는 차이를 말할 수 없습니다. 1명·소표본 결과이며 "
                       "단어 난이도는 무작위 배정으로만 통제했습니다. 인과 효과를 일반화하지 마세요.")
        st.download_button("📥 실험 결과 JSON", json.dumps({"experiment": exp, "analysis": res}, ensure_ascii=False,
                                                         default=str, indent=1),
                           file_name="wordloop_experiment.json", mime="application/json")
    if st.button("실험 기록 지우고 새로 시작", key="exp_reset"):
        if save(store, None):
            st.rerun()


def _pct(v):
    return "—" if v is None else f"{v * 100:.0f}%"
