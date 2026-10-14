# 데이터 모델

정의: [`supabase/migrations/20261014000000_wordloop_init.sql`](../supabase/migrations/20261014000000_wordloop_init.sql) · 로컬 SQLite 대응: `services/store.py`의 `LOCAL_SCHEMA`

모든 시각은 `timestamptz`(UTC). 화면에서만 `APP_TIMEZONE`(기본 Asia/Seoul)로 바꿉니다.

| 테이블 | 키 | 내용 | 접근 |
|---|---|---|---|
| `profiles` | `user_id` → `auth.users` | 표시 이름, `legacy_state`(기존 암기/정답/오답/시험 기록), `legacy_imported_at`, `settings`(하루 목표량) | 본인 select/insert/update |
| `vocabulary` | `word_id` | 단어·뜻·예문·AI 예문·카테고리·`extra`(Excel E/F열), `source_no`, `owner_user_id`(NULL=공용) | 공용+본인 select, 본인 insert/update/delete |
| `word_progress` | `(user_id, word_id)` | `fsrs_card` JSON, `due_at`, `last_review_at`, `review_count`, `lapse_count`, `version` | 본인 select/insert/update |
| `review_events` | `event_id`, `attempt_id` UNIQUE | 불변 복습 이력: mode, correct, rating 1~4, duration, device, due_before/after | 본인 select/insert (update/delete 권한 없음) |
| `test_sessions` | `session_id` | 기존 시험 결과(총/정답) | 본인 select/insert |
| `writing_attempts` | `attempt_id` | `ocr_text`(AI 인식) / `confirmed_text`(사용자 확정), status(ocr/manual/self), correct, feedback | 본인 select/insert |
| `ai_cache` | `(user_id, cache_key)` | 구조화 결과 JSON, model, prompt_version, `valid`(신고 시 false), 만료 | 본인 전체 |
| `ai_usage` | `request_id` | 기능, 모델, 상태(ok/cache_hit/invalid/rate_limited/timeout/error/reported), 토큰 | 본인 select/insert |

## 권한

- 먼저 `anon`, `authenticated`, `public`에서 모든 권한을 회수한 뒤 필요한 권한만 `authenticated`에 다시 부여합니다. Supabase 기본 설정은 새 테이블에 전체 권한을 주기 때문입니다(통합 테스트에서 실제로 발견).
- 8개 테이블 모두 RLS 활성. 정책은 `(select auth.uid())` 비교로 본인 행만 허용합니다.
- `record_review` RPC: `security invoker`(RLS 그대로 적용), `search_path = ''`, `anon` 실행 권한 없음. 볼 수 없는 단어에는 기록할 수 없습니다.
- 검증: `tests/test_auth_rls.py` — A 계정 기록이 B에게 보이지 않음(8개 테이블), B가 A 단어를 수정·삭제·위조 insert 불가, 본인도 이력 수정·삭제 불가, anon 전면 차단, 로그아웃 후 차단.

## 설계 메모

- **다의어**: 같은 철자를 합치지 않습니다. 원본 번호(`source_no`) 단위로 이전하고 `unique nulls not distinct (owner_user_id, source_no)`.
- **word_id**: `uuid5(네임스페이스, "{소유자}:{원본 번호}")`. 마이그레이션을 다시 돌려도 같은 행이 되고, 이미 있는 행은 덮어쓰지 않습니다(앱에서 고친 내용 보호).
- **legacy**: `progress.json`에는 복습 시각·난이도가 없으므로 FSRS 리뷰 로그를 만들지 않습니다. 기존 표시는 `legacy_state`로만 보존하고, FSRS는 첫 새 복습부터 시작합니다. 예전에 틀린 단어는 새 단어 큐에서 먼저 나옵니다.
- **필기 이미지**: DB에 저장하지 않습니다. 확인 화면 미리보기와 재인식에만 서버 세션 메모리에서 씁니다.
- **ai_cache 사용자별 분리**: 공용 캐시는 다른 사용자가 넣은 결과를 그대로 쓰게 되므로(캐시 오염) 사용자별로 둡니다.

## 마이그레이션 절차

1. 앱 첫 로그인 화면에서 "Word.xlsx에서 N개 단어 가져오기" → 원본 개수·DB 개수·내용 체크섬(SHA-256) 비교 결과 표시
2. 이 PC에 `progress.json`이 있으면 "progress.json 진도 가져오기(1회)" → `legacy_imported_at` 기록, 다시 눌러도 중복 없음
3. 브라우저 localStorage에 이전 진도가 남아 있으면 미리보기(병합 후 개수) → 병합 / 이번엔 무시
4. 매핑 파일이 필요하면 `services.migrate.write_mapping()`으로 `source_no,word_id` CSV를 Git 제외 경로에 저장

되돌리기: 원본 Excel/JSON은 수정하지 않습니다. DB는 `supabase/rollback/20261014000000_wordloop_init_down.sql`(데이터 삭제 — 실행 전 백업).
