# 아키텍처

## 모드

| | 로컬 모드 (기본) | 로그인 모드 |
|---|---|---|
| 조건 | `SUPABASE_URL`/`SUPABASE_ANON_KEY` 없음 | 둘 다 설정 |
| 단어장 | `Word.xlsx` 읽기/쓰기 (기존과 동일) | Supabase `vocabulary` (첫 로그인 때 Word.xlsx 1회 가져오기) |
| 기존 진도(암기/정답/오답/시험 기록) | `progress.json` + localStorage (기존과 동일) | `profiles.legacy_state` |
| FSRS·필기·AI 기록 | `data/wordloop.db` (SQLite) | Supabase 테이블 (RLS) |
| 로그인 | 없음 | 이메일+비밀번호 |

두 저장소(`services/store.py`의 `LocalStore`, `SupabaseStore`)는 같은 메서드 계약을 따릅니다. 화면 코드는 저장소 종류를 모릅니다.

## 요청 흐름: S펜 철자 쓰기 1문항

```text
캔버스(JS)  pointerdown/move/up ─ pen만 수용(S펜 전용) ─ 벡터 획(논리 좌표 1000×450)
            └ 획 종료마다 IndexedDB 'wordloop/drafts'[wl:{user}:{word_id}:{mode}:v1]
            └ [AI 인식] → 획 영역 크롭 PNG(긴 변 ≤1024) → setTriggerValue('submit', {...})
Python      decode_submission: data URL·PNG 서명·Pillow 검증·픽셀/바이트 상한·빈 화면
            → AIService.ocr(png)   (정답 단어를 프롬프트에 넣지 않음, JSON 스키마 + Pydantic)
            → 확인 화면: 원본 미리보기 + 인식 문자열(수정 가능) + 후보/불확실 표시
            → 사용자가 확정 → is_correct_spelling(정규화 비교) 또는 수동 채점
            → Again/Hard/Good/Easy (오답이면 Again, 정답이면 Good 추천)
            → writing_attempts 1행 + study.submit_review → store.record_review (1 트랜잭션, 멱등)
            → 다음 문제: reset_token 증가로 캔버스 초기화, clear_keys로 완료 초안 삭제
```

확정 전에는 아무 것도 저장하지 않습니다. 같은 제출 이벤트(`submit_id`)는 한 번만 처리하고, 같은 시도(`attempt_id`)를 다시 저장하면 `duplicate`로 끝납니다.

## FSRS 저장 (CAS)

1. `get_progress_one(word)` → 카드 JSON과 `version` (없으면 새 카드, version 0)
2. py-fsrs `review_card(card, rating, now)` 로 새 카드 계산 (Python)
3. `record_review(attempt_id, expected_version, ...)`
   - 같은 `attempt_id` 이벤트가 있으면 `duplicate`
   - `version`이 다르면 `conflict` → 1번부터 다시(지터 대기, 최대 5회) → 그래도 실패하면 사용자에게 "저장 안 됨"
   - 성공 시 이벤트 추가 + 카드 갱신이 한 트랜잭션

Supabase에서는 `public.record_review`(plpgsql, `security invoker`)가, 로컬에서는 SQLite `BEGIN IMMEDIATE` 트랜잭션이 같은 의미를 구현합니다.

## AI 호출 경로 (`services/ai.py`)

```text
기능 메서드(ocr/example/toeic_questions/...) → AIService.call
  ├ 캐시 조회 (사용자별, 키 = feature + 정규화 입력 + prompt_version + model + schema_version + 옵션)
  ├ cached_only면 여기서 끝 (화면 로드 시 자동 호출 방지)
  ├ 같은 요청 동시 실행 잠금(busy)
  ├ 회로차단(연속 3회 실패 → 120초 휴지) · 최근 24시간 사용자 상한
  ├ provider.generate (JSON 스키마) → 실패 시: 보조 모델 1회 전환(설정 시) / 429·타임아웃·5xx 지수 백오프+지터, Retry-After 존중(30초 초과면 즉시 포기)
  ├ Pydantic 검증 + 기능별 검증(TOEIC: 빈칸 1개, 보기 4개 중복 없음, 정답 1개, 정답 누설 없음, 허용 오답)
  └ ai_usage 기록(모델·상태·토큰), 성공 시 캐시 저장
```

모든 실패는 `AIError(kind)`로 올라오고, 화면은 `user_message`를 보여준 뒤 무AI 경로(직접 입력, 로컬 문제, 일반 시험)로 계속합니다.

## 인증·세션

- `views/account.py`: supabase-py 클라이언트를 세션별로 만들고 자동 갱신을 끔. 만료 2분 전 직접 갱신하고, 회전된 refresh token을 이 기기 localStorage(`wl_rt`)에 다시 씀. access token은 저장하지 않음.
- 새로고침 시 `wl_rt`로 세션 복구. 실패하면 토큰 삭제 후 로그인 화면.
- 로그아웃: 세션 상태 전체 삭제, `wl_rt` 삭제, 이 기기 IndexedDB `wordloop` 삭제. 미전송 큐는 폐기(버튼 옆에 경고).
- service_role/secret 키는 앱 어디에도 쓰지 않음. 사용자 ID는 항상 Auth 세션(`auth.uid()`)에서 나옴.

## 파일 지도

| 경로 | 역할 |
|---|---|
| `app.py` | 기존 탭 코드 + 저장소/AI 주입. 탭: 🏠 오늘 · 📖 학습 · ✍️ 쓰기 · 📝 시험 · ♾️ 무한 · 📋 단어장 · ✏️ 관리 · 📊 통계 (`?tab=write` 등으로 시작 탭 지정) |
| `components/handwriting/` | 캔버스 JS(순수 로직은 named export → Node 테스트) + CSS |
| `services/` | 화면과 무관한 로직 (테스트 대상) |
| `views/` | Streamlit 화면 조각 |
| `supabase/` | 로컬 개발 설정(`config.toml`, 포트 553xx), 마이그레이션, 되돌리기 SQL |

권장 구조(CLAUDE_V2.md §9)와 다른 점: `repositories/`·`schemas/`를 따로 두지 않고 `services/store.py`, `services/ai.py` 안에 두었습니다(구현체가 각각 1~2개라 파일 분리 이득이 적음). 마이그레이션은 Supabase CLI 규약에 맞춰 `supabase/migrations/`에 있습니다.
