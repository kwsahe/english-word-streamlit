"""FSRS vs 무작위 실험: 배정 · 단계 · 큐 제외 · 노출량 맞춤 · 재시험 · 분석."""
import random
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from services import experiment, study

T0 = datetime(2026, 10, 1, 3, 0, tzinfo=timezone.utc)
WORDS = [{"id": f"w{i}", "no": i} for i in range(1, 101)]


def test_create_is_seeded_disjoint_and_uses_only_fresh_words():
    progress = {"w1": {}, "w2": {}}
    a = experiment.create(WORDS, progress, n=40, seed=7, now=T0)
    b = experiment.create(WORDS, progress, n=40, seed=7, now=T0)
    assert a == b                                            # 같은 시드 → 같은 배정(재현 가능)
    assert len(a["fsrs"]) == len(a["random"]) == 20 and not set(a["fsrs"]) & set(a["random"])
    assert not {"w1", "w2"} & set(a["fsrs"] + a["random"])  # 이미 FSRS 기록이 있는 단어 제외
    with pytest.raises(ValueError):
        experiment.create(WORDS, progress, n=99, seed=1, now=T0)   # 홀수
    with pytest.raises(ValueError):
        experiment.create(WORDS[:10], {}, n=20, seed=1, now=T0)    # 단어 부족


def test_phases_and_queue_exclusion():
    exp = experiment.create(WORDS, {}, n=20, seed=3, now=T0, learn_days=14, delay_days=7)
    assert experiment.phase(None, T0) is None and experiment.excluded_ids(None, T0) == set()
    assert experiment.phase(exp, T0 + timedelta(days=13)) == "learning"
    assert experiment.excluded_ids(exp, T0) == set(exp["random"])
    assert experiment.priority_new(exp, T0) == set(exp["fsrs"])
    assert experiment.phase(exp, T0 + timedelta(days=15)) == "waiting"
    assert experiment.excluded_ids(exp, T0 + timedelta(days=15)) == set(exp["fsrs"]) | set(exp["random"])
    assert experiment.phase(exp, T0 + timedelta(days=21)) == "posttest"
    assert experiment.phase({**exp, "status": "aborted"}, T0) == "aborted"
    assert experiment.excluded_ids({**exp, "status": "aborted"}, T0) == set()


def test_fsrs_queue_respects_experiment():
    exp = experiment.create(WORDS, {}, n=20, seed=3, now=T0)
    q = study.build_today_queue(WORDS, {}, T0, ZoneInfo("Asia/Seoul"), new_limit=10,
                                exclude=experiment.excluded_ids(exp, T0),
                                priority_new=experiment.priority_new(exp, T0))
    ids = [w["id"] for w in q["queue"]]
    assert set(ids) == set(exp["fsrs"])                      # 새 단어 10개 = FSRS군 우선
    assert not set(ids) & set(exp["random"]) and q["new_total"] == 90


def test_random_quota_matches_fsrs_exposure():
    exp = experiment.create(WORDS, {}, n=20, seed=3, now=T0)
    ev = [{"word_id": exp["fsrs"][0]}, {"word_id": exp["fsrs"][1]}, {"word_id": exp["random"][0]}, {"word_id": "w99x"}]
    assert experiment.random_quota(exp, ev) == 1
    assert experiment.random_quota(exp, ev[:1] + ev[2:3]) == 0
    rng = random.Random(0)
    assert all(experiment.pick_random(exp, rng, last=exp["random"][0]) != exp["random"][0] for _ in range(20))


def test_posttest_order_and_analysis():
    exp = experiment.create(WORDS, {}, n=40, seed=5, now=T0)
    order = experiment.posttest_order(exp)
    assert sorted(order) == sorted(exp["fsrs"] + exp["random"]) and order == experiment.posttest_order(exp)
    for i, w in enumerate(exp["fsrs"]):
        exp["posttest"][w] = i < 16           # 80%
    for i, w in enumerate(exp["random"]):
        exp["posttest"][w] = i < 10           # 50%
    assert experiment.next_posttest(exp) is None
    events = [{"word_id": exp["fsrs"][0], "created_at": T0 + timedelta(days=1), "correct": True},
              {"word_id": exp["random"][0], "created_at": T0 + timedelta(days=1), "correct": False},
              {"word_id": exp["random"][0], "created_at": T0 - timedelta(days=1), "correct": True}]  # 실험 전
    res = experiment.analyze(exp, events)
    assert res["fsrs"]["posttest_accuracy"] == 0.8 and res["random"]["posttest_accuracy"] == 0.5
    assert res["diff"] == 0.3 and res["ci95"][0] < 0.3 < res["ci95"][1]
    assert res["random"]["reviews"] == 1 and res["random"]["learning_accuracy"] == 0.0


def test_analysis_without_posttest_has_no_numbers():
    exp = experiment.create(WORDS, {}, n=20, seed=5, now=T0)
    res = experiment.analyze(exp, [])
    assert res["diff"] is None and res["ci95"] is None and res["fsrs"]["posttest_accuracy"] is None
