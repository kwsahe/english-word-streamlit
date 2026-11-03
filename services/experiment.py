"""FSRS vs 무작위 복습 비교 실험 (학습자 1명 안에서 단어를 무작위로 두 군으로 나눔).

설계 (docs/AI_EVALUATION.md §4)
- 아직 FSRS 기록이 없는 단어 N개를 시드 고정 무작위로 반반 배정: fsrs 군 / random 군.
- 학습 기간: fsrs 군은 평소 FSRS 큐(새 단어 우선 출제), random 군은 FSRS 큐에서 빼고
  '오늘 fsrs 군을 복습한 횟수'만큼 무작위로 출제(노출량 맞춤).
- 대기 기간: 두 군 모두 출제하지 않음.
- 재시험: 두 군 전체를 같은 형식(뜻 → 철자 입력)으로 1회씩. 결과는 실험 기록에만 저장(FSRS에 반영 안 함).
- 분석: 군별 정답률, 차이, 부트스트랩 95% 신뢰구간. 표본 수와 해석 주의를 함께 표시.
"""
import random
from datetime import timedelta

from services.config import parse_dt, to_utc_iso


def create(words: list[dict], progress: dict, *, n: int, seed: int, now, learn_days: int = 14,
           delay_days: int = 7) -> dict:
    fresh = sorted(w["id"] for w in words if w["id"] not in progress)
    if n < 2 or n % 2 or len(fresh) < n:
        raise ValueError(f"실험에는 FSRS 기록이 없는 단어가 짝수로 {n}개 필요합니다(현재 {len(fresh)}개).")
    chosen = random.Random(seed).sample(fresh, n)
    return {"version": 1, "seed": seed, "started_at": to_utc_iso(now), "learn_days": learn_days,
            "delay_days": delay_days, "fsrs": sorted(chosen[: n // 2]), "random": sorted(chosen[n // 2:]),
            "posttest": {}, "status": "running"}


def phase(exp: dict | None, now) -> str | None:
    """None | learning | waiting | posttest | done | aborted"""
    if not exp:
        return None
    if exp["status"] in ("done", "aborted"):
        return exp["status"]
    start = parse_dt(exp["started_at"])
    if now < start + timedelta(days=exp["learn_days"]):
        return "learning"
    if now < start + timedelta(days=exp["learn_days"] + exp["delay_days"]):
        return "waiting"
    return "posttest"


def excluded_ids(exp: dict | None, now) -> set:
    """일반 FSRS 큐(오늘 탭·쓰기 연습)에서 뺄 단어."""
    p = phase(exp, now)
    if p == "learning":
        return set(exp["random"])
    if p in ("waiting", "posttest"):
        return set(exp["fsrs"]) | set(exp["random"])
    return set()


def priority_new(exp: dict | None, now) -> set:
    """학습 기간에는 fsrs 군 단어를 새 단어 중 먼저 출제해 실제로 학습되게 한다."""
    return set(exp["fsrs"]) if phase(exp, now) == "learning" else set()


def random_quota(exp: dict, events_today: list[dict]) -> int:
    """오늘 fsrs 군 복습 횟수 - 오늘 random 군 복습 횟수 (노출량 맞춤)."""
    a, b = set(exp["fsrs"]), set(exp["random"])
    return max(0, sum(str(e["word_id"]) in a for e in events_today) - sum(str(e["word_id"]) in b for e in events_today))


def pick_random(exp: dict, rng: random.Random, last: str | None = None) -> str:
    pool = [w for w in exp["random"] if w != last] or exp["random"]
    return rng.choice(pool)


def posttest_order(exp: dict) -> list[str]:
    ids = sorted(exp["fsrs"] + exp["random"])
    random.Random(exp["seed"] + 1).shuffle(ids)
    return ids


def next_posttest(exp: dict) -> str | None:
    return next((w for w in posttest_order(exp) if w not in exp["posttest"]), None)


def _bootstrap_diff(a: list[bool], b: list[bool], iters: int = 2000, seed: int = 0) -> tuple[float, float]:
    rng = random.Random(seed)
    diffs = sorted(
        sum(rng.choice(a) for _ in a) / len(a) - sum(rng.choice(b) for _ in b) / len(b) for _ in range(iters))
    return diffs[int(0.025 * iters)], diffs[int(0.975 * iters) - 1]


def analyze(exp: dict, events: list[dict]) -> dict:
    groups = {"fsrs": set(exp["fsrs"]), "random": set(exp["random"])}
    start = parse_dt(exp["started_at"])
    out = {}
    for g, ids in groups.items():
        post = [bool(exp["posttest"][w]) for w in sorted(ids) if w in exp["posttest"]]
        learn = [e for e in events if str(e["word_id"]) in ids and e["created_at"] >= start]
        graded = [e for e in learn if e.get("correct") is not None]
        out[g] = {
            "n": len(ids), "tested": len(post),
            "posttest_accuracy": round(sum(post) / len(post), 3) if post else None,
            "reviews": len(learn),
            "learning_accuracy": round(sum(bool(e["correct"]) for e in graded) / len(graded), 3) if graded else None,
        }
    a = [bool(exp["posttest"][w]) for w in sorted(groups["fsrs"]) if w in exp["posttest"]]
    b = [bool(exp["posttest"][w]) for w in sorted(groups["random"]) if w in exp["posttest"]]
    if a and b:
        out["diff"] = round(sum(a) / len(a) - sum(b) / len(b), 3)
        lo, hi = _bootstrap_diff(a, b)
        out["ci95"] = (round(lo, 3), round(hi, 3))
    else:
        out["diff"], out["ci95"] = None, None
    return out
