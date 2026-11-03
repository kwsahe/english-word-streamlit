# CLAUDE_V2.md — WordLoop AI 개발 실행 지침 (Claude Code)

> 문서 버전: v2.0 / 작성 기준: 2026-10-14 (Asia/Seoul)
>
> 대상 저장소: https://github.com/kwsahe/english-word-streamlit
>
> 기존 배포: https://honeyenglish.streamlit.app/
>
> 개발 목표: 기존 Streamlit 영단어장을 **개인용 무료 AI 맞춤형 영어 학습 플랫폼**으로 개선하고, **갤럭시탭 S펜 직접 필기·AI 판독·PC/태블릿 동기화·FSRS 복습**을 구현하여 실제 학습 도구이자 AI 엔지니어링 포트폴리오로 완성함.
>
> **중요:** 이 문서는 Claude Code에게 전달하는 **구현 지시서**임. 작성 시점에 신규 기능이 구현 또는 배포되었다는 의미가 아님.

---

## 0. Claude Code에 대한 최상위 지시 (반드시 준수)

너는 이 저장소의 **시니어 Python/AI/풀스택 엔지니어 겸 QA 담당자**로 행동함. 본 문서를 단순 요약하지 말고, 저장소를 실제로 검사하여 **작업 가능한 코드·마이그레이션·테스트·문서**를 단계적으로 구현함.

1. 먼저 Git 상태, 실제 브랜치, 전체 파일 트리, 현재 기능·의존성·API 연동·배포 방식을 조사하고 아래의 **현행 코드 관찰값을 실제 소스와 다시 대조**함. 문서와 실제 코드가 다르면 실제 코드가 우선함.
2. **기존 서비스를 새로 만들거나 무리하게 갈아엎지 않음.** Python + Streamlit, 기존 `Word.xlsx` 영단어, 7개 기존 기능을 최대한 보존하여 점진적으로 리팩터링함. 별도 Next.js/FastAPI 서버는 1차 범위에 도입하지 않음.
3. `master`에 직접 개발하지 않음. 작업 전 `git status` 확인 후, 안전한 신규 브랜치 `feature/wordloop-ai-v2`에서 작업함. 이미 존재하면 내용을 확인하고 충돌 없는 새 이름을 선택함. 사용자 미커밋 변경은 무단 삭제·덮어쓰기 금지함.
4. 원본 `Word.xlsx`와 `progress.json`을 **개발 환경의 비공개 위치**에 백업하고, 데이터 수량/해시와 기존 학습 진행 상태를 확인한 후 변경함. 기존 진도·단어·예문·카테고리를 잃지 않음.
5. 무료 사용을 전제로 설계함. **유료 결제·API 유료 전환·외부 인프라 생성·실서버 데이터 삭제·프로덕션 배포는 사용자 명시적 승인 없이 수행하지 않음.** 서비스가 필요한 단계에서 비밀키나 프로젝트 정보가 없으면 `.env.example`/설정 가이드와 로컬 mock·테스트까지 구현하여 진행 가능한 작업을 끝냄.
6. 작업 순서는 **Phase 0 → 1 → 2 → 3 → 4 → 5**이며, 각 단계별 테스트 통과 후 다음 단계로 진행함. 시간이 부족하면 동작 검증된 범위까지만 안전하게 완성하고 남은 사항은 체크리스트로 보고함. 테스트 결과를 만들어내거나 실행하지 않은 기능을 완료라고 표시하지 않음.
7. **최우선 사용자 경험은 갤럭시탭 S펜 필기**임. 단순 브라우저 접속을 태블릿 연동으로 간주하지 않음. 직접 쓰기 → OCR → 사용자 확인 → 정오답/FSRS 반영 → 기기간 DB 동기화까지 연결함.
8. 오류/무료 한도 초과/네트워크 실패가 발생하더라도 기존 플래시카드·일반 시험·복습은 동작하도록 **AI 없는 대체 경로**를 반드시 보유함.
9. 한국어 UI 및 문서가 기본임. 개발 결과 보고 문장 끝은 가능하면 `~함`, `~됨`, `~필요함` 형식을 사용함.
10. **코드 수정 완료와 실제 갤럭시탭 실기기 검증 완료를 구분**함. 장치 미접속 상태에서는 펜 이벤트를 에뮬레이션으로 테스트하고 실기기 QA를 `검증 대기`로 정확히 표시함.

### 작업할 저장소의 기존 구조(초기 조사 기준)

- `app.py`: Streamlit 단일 앱. 현재 플래시카드, 쓰기, 일반 시험, 무한 시험, 단어장, 단어 관리, 통계의 **7개 탭**을 포함함.
- `Word.xlsx`: 약 724개 단어(기존 README 기준)와 `번호`, `단어`, `뜻`, `예문`, `카테고리`, `AI 예문` 등의 데이터를 보유함. **실제 행 개수는 코드 실행 시 재확인**함.
- `progress.json`: `memorized`, `wrong`, `correct`, `sessions`를 보존함. 현재 공개 Git 저장소에 추적되었으므로 민감 정보/개인 기록의 Git 노출 여부를 점검함.
- `requirements.txt`: `streamlit`, `openpyxl`, `pandas`, `streamlit-js-eval`, `google-genai`가 포함되어 있음.
- 기존 Gemini: `GEMINI_MODEL = "gemini-3.6-flash"`; `st.secrets.get("GEMINI_API_KEY")` 사용. AI 예문, 토익형 문제 생성, 손글씨 이미지 채점, AI 학습 조언이 일부 구현됨.
- 기존 쓰기: `writing_canvas()`는 `components.html()`의 iframe 안에 HTML Canvas/Pointer Events를 표시하고, 별도 JavaScript가 iframe 내부 이미지를 탐색하여 읽는 방식임. **취약한 결합을 교체**해야 함.
- 기존 진도: `progress.json` + 브라우저 `localStorage` 병용. 기기간 공통 계정 동기화와 서버 정본이 없음.

**보호해야 하는 회귀 기능**: 플래시카드 앞/뒤 전환, 카테고리/범위 필터, TTS 발음, 암기 체크, 일반 4지선다/주관식/토익 빈칸, 무한 시험, 정오답 표시/내보내기, 단어 CRUD, AI 예문 저장, 학습 통계 및 현재 학습 기록.

---

## 1. 제품 범위 및 비기능 요구사항

### 1.1 주 사용자

- 주 사용자 1명: PC(단어 관리·학습 통계)와 **삼성 갤럭시탭 + S펜**(직접 필기·복습)을 번갈아 사용함.
- 추후 포트폴리오 체험자: 별도 데모 계정/샘플 데이터. 실제 사용자 개인 진도가 타인에게 노출되면 안 됨.
- 새 기기 로그인 시 단어·오답·복습·학습 기록이 Supabase에서 복구되어야 함.

### 1.2 반드시 구현할 학습 흐름

```text
[PC/태블릿 동일 계정 로그인]
  → [오늘 복습할 단어 자동 제시]
  → [플래시카드 / 객관식 / 타이핑 / S펜 필기 선택]
  → [필기: S펜 입력 → 이미지 생성 → AI 문자 판독 → 사용자 결과 확인]
  → [정답 검증: 단어는 Python, 문장 교정은 Gemini]
  → [FSRS 난이도 평가 Again/Hard/Good/Easy]
  → [학습 이벤트 + 다음 복습 시점 DB에 원자적 저장]
  → [PC·갤럭시탭에서 동일 결과 확인]
  → [대시보드·취약점 분석]
```

### 1.3 합격 기준

- 기존 7개 학습 기능 회귀 테스트 통과.
- PC와 갤럭시탭의 같은 계정 데이터가 재로그인·새로고침 후 일치함.
- S펜 전용 모드에서 터치로 인한 잘못된 필기 획이 생성되지 않음(표준 Pointer Events 지원 조건 하). 실제 S펜/브라우저 장비별 동작은 실기기 QA로 따로 확인함.
- 필기 원본은 OCR 실패에도 사라지지 않고 재제출/수동 채점이 가능함.
- OCR 인식 결과를 수정·확정하기 전에는 FSRS·정답률에 반영하지 않음.
- API 키/서비스 권한 키/실제 학습 기록이 Git에 노출되지 않음.
- Gemini 호출 제한에 도달해도 로컬 문제·FSRS 복습·일반 학습은 계속 가능함.

---

## 2. 우선순위 및 개발 단계

| 단계 | 범위 | 우선순위 | 완료 조건 |
|---|---|---|---|
| Phase 0 | 기존 코드 조사, 백업, 테스트 기준선, API 무료 티어 검증 | 필수 | 현재 기능·데이터·환경 점검 및 회귀 테스트 기반 구축 |
| Phase 1 | Supabase Auth/DB, 사용자별 데이터, 마이그레이션·동기화 | 필수 | 서로 다른 기기에서 진도 일치, 계정 간 데이터 격리 |
| Phase 2 | 갤럭시탭 S펜 필기 MVP + AI OCR + 수동 확인 | **최우선 신규 기능** | 필기·Undo·초안 보존·OCR 결과 수정·저장 동작 |
| Phase 3 | FSRS 적응형 복습 및 오답 집중 학습 | 필수 | 정확한 다음 복습 일정, 중복 제출 방지 |
| Phase 4 | AI 개인화 문제·문장 작문·받아쓰기·호출 비용 제어 | 중요 | 유효 문제 생성, 캐시, API 오류 대체 경로 |
| Phase 5 | 학습 분석 대시보드, 문서/CI/포트폴리오 | 중요 | 메트릭 검증·테스트·데모 자산 및 README 완성 |

**구현 원칙:** 모든 단계를 한 번에 재작성하지 말고 작고 검증 가능한 단위로 완료함. Phase 1의 서버 데이터 모델과 Phase 2의 손글씨 계약은 초기부터 함께 설계함.

---

## 3. Phase 0 — 기존 자산 보호 및 개발 기준선

### 상세 작업

1. `git status`, 기본 브랜치, 커밋, Python/Streamlit 버전, 배포환경을 확인함.
2. 기존 `app.py` 함수·상태·탭별 의존성을 목록화하고 입출력 계약을 문서화함.
3. Excel의 실제 시트명, 헤더 위치, 열 구조, 단어 수, 중복 단어, 다의어, 빈 값, 수식, 기존 AI 예문 등을 검사함.
4. `Word.xlsx`, `progress.json`의 백업 사본과 SHA-256 체크섬을 안전한 로컬 백업 폴더에 생성함. **원본 콘텐츠를 공개 Git 문서에 그대로 노출하지 않음.**
5. existing smoke tests와 신규 `pytest` 테스트 환경을 마련함. DB/API 없이 실행 가능한 mock 계층을 만듦.
6. `GEMINI_API_KEY`가 없거나 API 호출이 막힌 상태에서 기존 일반 학습이 완전히 동작하는지 확인함.
7. 현재 Git에 `progress.json`이 추적되어 있으면 추적 중단 방안을 마련하고 **실제 학습 데이터 보존 후** `.gitignore`와 `git rm --cached`를 적용함. 과거 Git 이력의 공개 기록이 별도로 남을 수 있다는 점을 문서화하고 **이력 전체 재작성·force push는 하지 않음**.
8. `Word.xlsx`는 초기 마이그레이션 소스로 유지함. 기존 수식·표 참조를 임의로 삭제하지 않음.
9. Streamlit custom component v2 및 최신 호환 버전을 실제 설치환경에서 시험하고 버전을 고정함.
10. 기능별 UI 스크린샷/실행 로그를 수집하되 개인 데이터/키를 마스킹함.

**완료 보고:** 발견된 기존 코드 위험, 원본 데이터 건수, 회귀 테스트 결과, 변경 예정 파일 목록, 잔여 의존성을 보고함.

---

## 4. Phase 1 — 데이터베이스·인증·PC/갤럭시탭 동기화

### 4.1 원칙

- 학습 데이터 **서버 정본(source of truth)**: Supabase PostgreSQL.
- 사용자 인증: Supabase Auth(이메일 OTP/매직링크 또는 이메일 로그인 중 안정적인 1가지를 구현하고 선택 근거 문서화).
- `Word.xlsx`는 기존 전체 단어의 일회성 가져오기·백업·내보내기 기능으로 보존함. 실서비스에서 공유 엑셀 파일을 직접 덮어써서 저장하지 않음.
- 서버에 인증된 사용자 토큰으로 접근하고 Supabase RLS를 적용함. Streamlit 서버에 별도 관리 비밀키가 필요하다면 최소 권한을 검토하고, **service_role 키가 브라우저로 전달되거나 사용자 권한 확인 없이 대리 호출되지 않도록** 제한함. 일반 사용자 데이터 조회/변경에는 RLS 적용된 사용자 세션을 우선함.
- 개인 포트폴리오 앱이지만 다중 사용자 계정 데이터 격리 원칙을 지킴.

### 4.2 제안 테이블 (migration SQL 작성)

| 테이블 | 필수 필드 및 제약 | 목적 |
|---|---|---|
| `profiles` | `user_id UUID PK`→`auth.users`, `display_name`, `created_at` | 사용자 프로필 |
| `vocabulary` | `word_id UUID PK`, `owner_user_id UUID NULL`, `source_no`, `word`, `meaning`, `example`, `ai_example`, `category`, `created_at`, `updated_at` | 공용·개인 단어 |
| `word_progress` | `(user_id, word_id) PK`, `fsrs_card JSONB`, `due_at TIMESTAMPTZ`, `last_review_at`, `updated_at`, `version INT` | 단어별 복습 상태 |
| `review_events` | `event_id UUID PK`, `attempt_id UUID UNIQUE`, `user_id`, `word_id`, `session_id`, `mode`, `correct`, `rating`, `duration_ms`, `created_at`, `device_type` | 불변 학습 이력 |
| `test_sessions` | `session_id UUID PK`, `user_id`, `mode`, `total`, `correct`, `started_at`, `finished_at` | 시험 세션 |
| `writing_attempts` | `attempt_id UUID PK`, `user_id`, `word_id`, `mode`, `ocr_text`, `confirmed_text`, `feedback JSONB`, `status`, `created_at` | 필기 판독·확인 |
| `ai_cache` | `cache_key TEXT PK`, `feature`, `model_id`, `prompt_version`, `result JSONB`, `expires_at`, `valid` | 중복 생성 감소 |
| `ai_usage` | `request_id UUID PK`, `user_id`, `feature`, `model_id`, `tokens_in`, `tokens_out`, `status`, `created_at` | 호출량/실패율 측정 |

추가 고려사항:

- `vocabulary`의 복합 중복 기준은 **단어 문자열만이 아니라 뜻·품사·카테고리 등 의미 단위**로 평가함. 기존 동일 철자·다의어를 임의 병합하지 않음.
- 공용 단어(`owner_user_id IS NULL`)는 모든 로그인 사용자가 조회 가능하나 변경은 관리자/배포 절차로 제한함. 개인 단어는 작성자만 CRUD 가능함.
- 개인 데이터 `word_progress`, `review_events`, `writing_attempts`, `test_sessions`, `ai_usage`는 기본적으로 본인 계정만 접근 가능함.
- 노출되는 `public` 스키마 테이블에는 필요한 GRANT와 RLS 정책을 모두 검토·작성함. `anon` 역할은 개인 기록에 접근 불가함.
- 자주 조회하는 `review_events(user_id, created_at)`, `word_progress(user_id, due_at)` 등에 인덱스 구성함.
- `word_progress`와 `review_events`의 업데이트·이벤트 추가는 **단일 DB 트랜잭션/RPC** 또는 안전한 CAS(version) 재시도 방식으로 처리함.
- 동시 PC/태블릿 제출 시 `attempt_id` 멱등 키로 중복 업데이트 방지함. 충돌 발생 시 최신 서버 카드를 불러와 순서를 정한 후 재시도함.
- 시간은 DB/FSRS 모두 UTC, UI만 `Asia/Seoul`로 변환함.

### 4.3 마이그레이션

1. `Word.xlsx`의 행 번호 `no`와 새 `word_id`의 매핑파일을 생성함(임시 비공개 파일).
2. 모든 원본 단어·뜻·예문·카테고리·AI 예문 데이터를 누락 없이 DB로 이동함.
3. `progress.json`의 `memorized`, `wrong`, `correct`, `sessions`를 기존 사용자 계정에 **한 번만** 가져올 수 있도록 구현함.
4. 브라우저 `localStorage`에 구 진도가 남아있을 경우, 자동 덮어쓰기 대신 **가져올 데이터 미리보기/동의/병합** 제공함.
5. 과거 데이터에는 복습 시각이나 난이도 정보가 없음. **가짜 FSRS 리뷰 로그를 만들지 않음.** 기존 표시 상태를 `legacy`로 보존하고 첫 신규 복습부터 FSRS 일정을 적용함.
6. 이전 전후 단어 개수·단어 내용 체크섬·세션 수를 비교하고 실패 시 원본으로 복원 가능하도록 함.
7. 마이그레이션 스크립트는 반복 실행해도 동일 데이터를 중복 입력하지 않는 idempotent 방식으로 작성함.

### 4.4 UX 및 실패 처리

- PC/태블릿 동일 계정 로그인을 지원하고 새로고침 이후에도 인증 세션을 복구함. 토큰은 안전하게 관리하고 만료 시 재인증함.
- `저장됨`, `저장 중`, `동기화 실패`, `재시도`를 화면에 구분 표시함.
- DB 저장 성공을 확인하기 전에는 저장됐다고 표시하지 않음.
- 네트워크 오류로 서버 기록이 저장되지 않았을 때는 **로컬 미전송 큐**로 보호하며 복구 후 명시적 재전송을 지원함. 큐의 민감 정보·토큰 저장 방식을 최소화하고 로그아웃 시 처리 정책을 정의함.
- 기본 오프라인 기능은 필기 초안 보호 수준임. 완전한 오프라인 동기화/PWA는 MVP 범위 밖임.

**Phase 1 합격 테스트:** A계정의 기록을 B계정에서 볼 수 없음(RLS 확인), PC 저장→태블릿 재조회 시 동일한 결과, 중복 이벤트 제출해도 기록 1회 반영, 마이그레이션 재실행에 중복 없음.

---

## 5. Phase 2 — 갤럭시탭 S펜 필기 학습 (최우선 MVP)

### 5.1 필기 화면과 학습 모드

화면 IA:

- **홈**: 오늘 복습 예정 수, 최근 정답률, 추천 취약 단어, 빠른 필기 시작.
- **필기 학습**: 문제/힌트, 넓은 필기 캔버스, 발음 버튼, 펜 도구, AI 인식, 결과 확인, 다음 문제.
- **오답 복습**: 다시 쓸 단어 큐, AI 교정 기록.
- **시험/단어장/관리/통계**: 기존 기능 유지 후 점진적으로 통합.

필기 모드:

| 모드 | 문제 제시 | 답안 입력 | 채점 | 단계 |
|---|---|---|---|---|
| 따라쓰기 | 흐린 영단어 가이드 | S펜으로 위에 쓰기 | 기초 연습/사용자 자기평가(실제 글씨체 모양 점수는 필수 아님) | 필수 |
| 철자 기억해서 쓰기 | 한글 뜻 | S펜으로 영단어 | OCR → 사용자 확인 → Python 문자열 비교 | **필수** |
| 받아쓰기 | 기존 브라우저 TTS | 들은 단어/문장을 S펜으로 작성 | OCR + 철자/공백 비교 | 후속 |
| AI 작문 | 특정 단어와 조건 | 영문 1~3문장 S펜 필기 | OCR + Gemini 문법/의미/표현 교정 | 후속 |

태블릿 가로모드: 좌측 약 40% 문제/뜻/설명, 우측 약 60% 최대한 넓은 캔버스; 하단 펜 도구 및 제출. 세로모드: 문제 → 캔버스 → 제출/결과 세로 스택. 모바일·PC에서도 터치/마우스/키보드 대체 입력이 가능해야 함.

### 5.2 S펜 입력 컴포넌트

**기존 `components.html()` iframe 탐색 + `streamlit_js_eval`로 이미지 스크랩하는 구조를 필기 제출 경로에서 제거**하고, 가능하면 **Streamlit Custom Components v2**의 양방향 API로 교체함. Streamlit 현재 설치 버전에서 API를 실제 확인하고 호환되지 않으면 공식 v1 custom component 양방향 대체 구현을 검토하되 iframe 직접 DOM 탐색 방식으로 되돌리지 않음.

권장 파일: `components/handwriting/` (HTML/CSS/JS 또는 TypeScript). 다음 조건을 충족함.

- `PointerEvent.pointerType` 값으로 `pen`/`touch`/`mouse` 식별함. **S펜 전용 ON에서는 `pen` 포인터만 획 입력 수용**하고, `touch`는 획 생성에 사용하지 않음.
- 펜 이벤트를 탐지하지 못하는 갤럭시탭/브라우저가 존재할 수 있으므로 **터치 호환 모드 토글**, 마우스 입력 대체 제공함. 완벽한 OS 차원 palm rejection을 보장한다고 주장하지 않음.
- 캔버스 안에 한정해 `touch-action: none`을 적용하고 일반 페이지 스크롤은 정상 유지함.
- `pointerdown`/`pointermove`/`pointerup`/`pointercancel`/`lostpointercapture` 처리; `pointerId`, `setPointerCapture()`를 사용하여 단일 활성 획 추적함.
- 지원 시 `getCoalescedEvents()` 사용, `pressure` 값에 따른 제한된 굵기 변화, 미지원 시 고정 굵기로 대체함.
- 화면 회전·리사이즈·기기 DPR 조정 후 획 소실이 없도록 **벡터 획 데이터가 정본**이고 Canvas는 렌더 출력으로 취급함.
- 확대/축소 또는 필기 공간 크기 조정 후 좌표 오차를 방지함.
- `Undo`, `Redo`, 획 지우개, 전체 지우기, 펜 굵기 조정, 가이드 표시/숨김을 제공함.
- 입력 버튼은 최소 44px 터치 영역 확보. 제출·뒤로가기 오동작/중복 제출 방지.
- 필기 초안은 입력 종료시 브라우저 **IndexedDB**(또는 검증된 안전 대체)에 저장함. 키는 `user_id + word_id + mode + draft_version` 등으로 분리하고 로그아웃 후 타 계정에 노출되지 않도록 보호/삭제 정책을 구현함.
- Streamlit rerun, 재접속, 화면 회전 중에도 현재 문제의 초안을 되살릴 수 있어야 함.
- 고속 필기·영문 대소문자·긴 단어·문장 필기를 시험함.
- 삼성 전용 하드웨어 버튼/OS 지우개 제스처는 브라우저에서 보장되지 않으므로 필수 요구사항으로 오해하지 않음.

### 5.3 필기 제출 및 AI 채점 계약

```text
Canvas vector strokes
  → [빈 획인지 확인]
  → [서버로 제출할 때만 PNG 변환, 여백 크롭/용량 제한]
  → [Gemini 이미지→문자 인식]
  → [Pydantic 구조 검증]
  → [사용자에게 인식 문자열 및 원본 미리보기 제시]
  → [사용자가 인식 결과를 수정·확정]
  → [정답 여부 Python 비교 / 문장 평가 Gemini]
  → [최종 사용자가 학습 평가 확인]
  → [review_events·word_progress 1회 저장]
```

- 이미지 업로드 시 서버에서 실제 MIME·픽셀 크기·바이트 크기·빈 화면 여부 확인. 최대 크기는 작은 기본값으로 설정하고 사용자 설정으로 조절 가능하게 함.
- **원본 필기 이미지는 기본 DB에 영구 보존하지 않음**. 사용자에게 미리보기 및 초안 재시도는 제공하되 장기 저장은 동의를 받은 경우에만 별도 설계함.
- Gemini가 인식한 문자열과 검증된 답을 혼동하지 않음. OCR 모델이 추정한 `confidence`를 실제 확률처럼 단정하지 않음.
- 예시 구조화 응답(필드 추가 가능):

```json
{
  "recognized_text": "implement",
  "candidates": ["implement"],
  "uncertain": false,
  "notes": "",
  "schema_version": 1
}
```

- 철자 채점은 **AI의 is_correct 판단을 그대로 신뢰하지 않고** `unicodedata`/Unicode 정규화·공백·대소문자 규칙을 명확하게 적용한 Python 비교로 판정함. 다의어·구문·대시/띄어쓰기 허용 여부는 유형별 정책으로 구분함.
- 학습자 수정 후 채점해야 하며, OCR 오류로 인한 오답/정답이 학습 데이터에 자동 누적되면 안 됨.
- AI 요청 실패(429/5xx/타임아웃/파싱 불가) 시 **캔버스 초안을 유지한 채** 텍스트 입력 또는 수동 정오답 버튼 제공함.
- AI OCR 이미지는 개인정보 없이 영단어 필기 위주로 전송함. 오류 로그에 이미지 base64를 남기지 않음.

### 5.4 반드시 검증할 태블릿 시나리오

1. S펜만 입력되는 상황과 펜+손바닥 동시 접촉 상황(브라우저 지원 범위 안에서) 확인.
2. 삼성 인터넷 브라우저와 Chrome 각각에서 펜 입력, 화면 확대·축소, 화면 회전·멀티윈도우 확인.
3. `Undo`/`Redo`/`Clear`, 앱 rerun 후 획 복원, AI 응답 직전 새로고침 후 초안 복원.
4. AI OCR 오인식 → 사용자 수정 → 정답 판정 → FSRS 이벤트 1회 기록.
5. 네트워크 끊김/429 → 필기 이미지 유지 + 수동 채점.
6. 실제 갤럭시탭 모델·One UI 버전·S펜 모델은 테스트 기록에 적되 미확인 상태에서는 실기기 호환성 완료라고 표시하지 않음.

**Phase 2 필수 종료 조건:** 실제 태블릿을 연결할 수 없더라도 터치·펜 모의 이벤트 및 컴포넌트 테스트는 자동화함. 실기기 QA는 `docs/TABLET_QA.md`에 체크리스트로 남김.

---

## 6. Phase 3 — FSRS 적응형 복습 엔진

- 라이브러리: 검증된 버전의 `fsrs`(Py-FSRS), `Scheduler`, `Card`, `Rating`. 버전을 잠그고 직렬화 스키마를 검증함.
- 학습 평가는 **Again(기억 못함) / Hard(어렵게 기억) / Good(보통) / Easy(쉽게 기억)** 4가지로 구현함.
- 정오답 결과가 확정된 후 오답은 Again 기본 추천, 정답은 난이도 자기평가 또는 안전한 기본값을 제안함. AI가 임의로 FSRS 학습 평가를 결정하지 않음.
- 각 `word_progress.fsrs_card`에 카드 상태 JSON을 저장하고 `due_at`을 UTC로 갱신함. 새 카드는 초기 due 즉시 상태로 시작할 수 있음.
- 과거 단순 `memorized/wrong/correct` 상태는 보존하되 실제 복습 날짜가 없으므로 **신규 복습으로 FSRS를 초기화**함.
- 홈에 `오늘 만기 복습`, `새 단어`, `최근 반복 오답`, `예상 소요량`을 구분 표시함.
- 목표 학습량은 사용자 설정(예: 신규 5~10개, 복습 10~30개/일)으로 제공. 제안값일 뿐 강제 사용량은 아님.
- 출제 우선순위: `기한 지난 카드` → `오늘 만기` → `반복 오답` → `새 단어`를 기본으로 하되 알고리즘의 일정과 학습량 제한을 훼손하지 않도록 함.
- 응답 시간·문제 유형·오답 횟수 등은 분석용 이벤트로 보존하고, FSRS의 수학적 파라미터를 임의 수정하지 않음.
- 같은 `attempt_id` 재제출, 화면 새로고침, 두 기기 동시 채점에도 복습 카운트/일정이 잘못 누적되지 않도록 함.

**기본 단위 테스트 예:**

- Again/Good/Easy에 따른 `due_at` 변화 및 JSON 직렬화 왕복.
- UTC·Asia/Seoul 날짜 경계, 새벽/월말 복습 일정.
- 레거시 기록에서 가짜 날짜 생성이 없음.
- 중복 요청 2회 → 이벤트 1개 + 카드 업데이트 1회.
- DB 동시성 충돌에서 데이터 손실 없음.

---

## 7. Phase 4 — Gemini 무료 AI 기반 학습 고도화

### 7.1 **무료 API 사용 전제 — 반드시 동적으로 검증**

2026-10-14 공식 문서 기준으로 **`gemini-3.6-flash`와 `gemini-3.5-flash-lite`의 공식 모델 ID 및 무료 등급이 확인됨**. 다만 `gemini-3.6-flash`가 최신 Flash 모델인 것은 아니며, 실제 계정의 모델 접근권한·프로젝트 요금제·RPM/TPM/RPD 제한은 변동 가능하므로 런타임 및 AI Studio에서 확인함.

- **기본 구성 후보:**
  - `GEMINI_MODEL_MAIN=gemini-3.6-flash` — 손글씨 이미지 OCR, 문장 교정, 고난도 TOEIC 문제.
  - `GEMINI_MODEL_LITE=gemini-3.5-flash-lite` — 기본 설명, 예문, 저비용 텍스트 생성.
- 구체적 모델 ID를 환경설정으로 분리하고 API 요청 성공 여부를 smoke test 함. AI Studio에서 모델이 제공되지 않거나 할당량이 0이면 다른 **현재 제공되는 무료 모델**로 자동/관리자 선택 가능하게 구현함. 모델 존재나 무료 제한량을 임의 숫자로 하드코딩하지 않음.
- 실제 무료 할당량은 https://aistudio.google.com/rate-limit 에서 확인하도록 가이드함. **Free 프로젝트가 아닌 경우 무과금이라고 단정하지 않음.** 결제 등록이나 유료 모델 자동 대체는 금지함.
- 소규모 1인 사용을 기준으로 최적화: 일반 문제 채점은 Python, TTS는 브라우저, FSRS는 로컬 알고리즘, 고비용 생성은 캐시된 결과를 재활용함.
- 모델 사용·토큰 사용량은 API 응답이 제공하는 메타데이터 범위에서 기록. 제공되지 않으면 추정값과 실제 값을 구분함.
- Free API에 전송하는 데이터는 공급자 데이터 처리 약관을 고려해 최소화함. 실제 이메일/학습 이력 전체/인증 데이터/민감 정보 전송 금지함.

### 7.2 AI 기능

| AI 기능 | 입력 | 출력 | API 최소화 방식 |
|---|---|---|---|
| 단어 의미·예문 | 단어, 뜻, 수준 | 영문 예문 + 한국어 해석 | 기존 원장/캐시 우선 |
| AI TOEIC 문제 | 취약 단어 목록·카테고리 | 빈칸 문장·보기 4개·정답·해설 | 문제 여러 개 일괄 생성 |
| 혼동 단어 비교 | 자주 헷갈린 2~3개 | 비교표·문맥 문제 | 기록으로 대상만 선정 |
| S펜 OCR | 필기 이미지 1장 | 인식 문자열 및 불확실성 | 제출 때만 이미지 1회 전송 |
| AI 작문 피드백 | 사용자가 확인한 영문 | 문법·어휘·자연스러운 대안 | 수정이 있을 때만 호출 |
| 학습 코치 | 집계된 약점·최근 점수 | 오늘 학습 전략과 이유 | 1일 1회 생성·캐시 |

기존의 `generate_ai_toeic_questions`, `generate_ai_example`, AI 단어 자동완성, 기존 쓰기 AI 채점 기능은 가능하면 새 `AIService`를 통해 통합하고 기존 UX를 손상시키지 않음.

### 7.3 호출·캐시·검증

- `AIProvider` 인터페이스를 두고 Gemini 구현과 `FakeAIProvider` 테스트 대체를 분리함.
- JSON 구조화 출력 기능과 **Pydantic**을 활용하여 모델 응답 스키마 검증. Markdown 코드 블록 제거만으로 유효성을 보장한다고 보지 않음.
- TOEIC 문제 검증: 공백 위치 정확히 1개, 정답 1개·오답 3개, 4개 보기 중복 없음, 문제에 정답 누설 없음, 목표 단어 일치, 허용된 선택지·문법/문맥 품질 검사.
- AI 결과가 잘못되면 재사용 불가로 표시하고 사용자에게 오류 신고 및 재생성 기능 제공함. 정확성을 입증하지 못한 창작 문장은 정답으로 확정하지 않음.
- 캐시 키는 `feature + normalized_input + prompt_version + model_id + output_schema_version + relevant_options` 조합으로 만듦.
- 오류 429/5xx는 제한된 지수 백오프와 jitter로 재시도하되 서버의 `Retry-After`를 존중함. 반복 실패 시 **회로차단** 및 무AI 대체 경로로 전환함.
- 앱은 **사용자 요청당/일일 하드 상한**을 운영자 설정으로 제공하고 Free 프로젝트의 실제 한도를 초과하지 않도록 보수적으로 동작함. 기본적으로 자동으로 724개 전체 예문을 한 번에 생성하는 버튼은 경고·최대 배치 크기·중단/재개·호출량 예상 표시 없이 실행되지 않도록 수정함.
- 같은 버튼을 연속 클릭해 중복 청구/중복 이벤트가 발생하지 않도록 idempotency, 진행상태 UI, 백엔드 잠금 구현함.
- Gemini 응답이 AI 정답임을 명시하고 사실 오류/애매한 문장은 사용자 신고 후 새 문제로 교체 가능하게 함.

**Phase 4 합격:** API 키 없는 모드, 정상 응답, 비정형 JSON, 429, 타임아웃, 잘못된 문제, 이미지 판독 불확실성, 캐시 적중을 모두 테스트함.

---

## 8. Phase 5 — 학습 분석·AI 포트폴리오 완성

### 8.1 대시보드

- 총 단어 수, 오늘 복습 예정 수, 실제 복습 완료 수, 신규 학습 수.
- 지난 7/30일 학습 횟수·정답률 추이·오답 회복률·복습 이행률.
- `틀렸던 단어를 다시 맞힌 비율`과 `한 번 정답을 맞힌 단어 비율`을 구분함.
- S펜 필기 시도 수, OCR 자동 인식 후 **사용자 수정률**, 수동 채점 전환 횟수.
- AI 생성 문항 스키마 통과율, 생성 품질 신고율, 캐시 적중률, 일일 Gemini 요청량·오류율.
- 예상 기억 유지율(FSRS 기반 추정)은 **모델의 추정치**로 표시하고 실측 정답률과 혼동하지 않음.

### 8.2 분석 실험

- 단순 무작위 복습 vs FSRS 학습을 동일 기간·조건에서 비교할 수 있는 평가 설계를 문서화함.
- 핵심 메트릭: 7일 뒤 재시험 정답률, 오답 회복률, 사용자 세션 완료율, OCR 수정률, AI 문항 유효율.
- 학습 결과가 충분히 누적되기 전에는 숫자를 만들어내지 않음. 표본수·평가 시점을 표시하고 인과효과를 과장하지 않음.

### 8.3 GitHub 포트폴리오

- `README.md`: 이전 문제→개선 아키텍처→기능 시연→기술적 선택→측정 방법→한계→실행법 순서로 정리함.
- `docs/ARCHITECTURE.md`, `docs/DATA_MODEL.md`, `docs/TABLET_QA.md`, `docs/AI_EVALUATION.md`, `docs/DEPLOYMENT.md`, `docs/CHANGELOG_V2.md` 제공함.
- 아키텍처 다이어그램, 마이그레이션 구조, 검증 테스트 목록, 실제 UI 스크린샷을 포함함. 태블릿 실기기 영상은 사용자가 제공/촬영한 경우만 사용함.
- 공개 데모는 개인 계정이 아니라 **격리된 샘플 계정·합성 학습 기록**으로 운영함.

---

## 9. 권장 코드 구조 (필요에 따라 간소화 가능)

```text
english-word-streamlit/
├── CLAUDE_V2.md
├── app.py                        # 기존 진입점 유지, 탭/페이지 라우팅 점진 분리
├── pages/                        # 기존 학습/시험/관리/통계 + 오늘학습/필기/복습
├── components/
│   └── handwriting/             # Streamlit custom component v2, JS/TS + Canvas
├── services/
│   ├── ai_provider.py           # Gemini 무료 모델·응답 처리/대체 제공자
│   ├── ai_service.py            # 라우팅·캐시·쿼터·검증
│   ├── handwriting_service.py   # OCR·확인·문자열 판정
│   ├── scheduler_service.py     # FSRS Card/Rating/UTC
│   ├── study_service.py         # 이벤트·카드 상태 원자적 기록
│   ├── content_validator.py     # TOEIC·예문 구조 검증
│   └── analytics_service.py     # 정답률/복습률/AI 메트릭
├── repositories/                # Supabase Auth/DB 및 테스트용 인터페이스
├── schemas/                     # Pydantic 요청/응답/도메인 모델
├── migrations/                  # SQL schema + RLS + 단어/진도 이전 스크립트
├── tests/                       # 단위/통합/E2E(UI)/AI mock 테스트
├── docs/
│   ├── ARCHITECTURE.md
│   ├── DATA_MODEL.md
│   ├── TABLET_QA.md
│   ├── AI_EVALUATION.md
│   ├── DEPLOYMENT.md
│   └── CHANGELOG_V2.md
├── .streamlit/secrets.toml.example
├── .env.example                 # 비밀값 없이 환경변수 이름만
├── requirements.txt
├── requirements-dev.txt
├── Word.xlsx                    # 원본 참조용, 훼손 금지
└── README.md
```

- 실제 프로젝트 구조가 달라지면 유지보수성을 위해 수정 가능하나 구조 변경 근거를 보고함.
- Python 의존성은 호환 버전으로 고정하고 GitHub Actions에서 재현 가능하게 함.
- 기존 `app.py`를 단계별로 분해하며 1차에 모든 화면을 재작성하지 않음.
- 환경설정 예시: `SUPABASE_URL`, `SUPABASE_ANON_KEY` 또는 publishable key, `GEMINI_API_KEY`, `GEMINI_MODEL_MAIN`, `GEMINI_MODEL_LITE`, `ENABLE_AI`, `DAILY_AI_REQUEST_BUDGET`, `APP_TIMEZONE`. 실제 비밀값은 Git에 올리지 않음.
- Supabase 키 이름/권한과 최신 SDK는 공식 문서를 확인하고 맞춤 구현함.

---

## 10. 보안·개인정보·운영 제약

1. `.streamlit/secrets.toml`, `.env`, API 키, 인증 세션, 실제 사용자 기록, 필기 원본 이미지는 Git에 커밋하지 않음. `.gitignore` 정비 및 비밀키 노출 검사.
2. Supabase RLS를 **테이블마다** 검증하고 GRANT도 최소 권한으로 제한함. 관리자 편의를 이유로 전체 학습 기록을 공개하지 않음.
3. 프런트엔드에 service_role/관리 권한 키 전달 금지. 사용자 ID를 프런트 요청값만으로 믿지 않고 Auth에서 유도함.
4. 단어 입력·AI 출력·학습자 입력은 전부 미신뢰 데이터로 취급하고 렌더링 시 HTML/JS 삽입 공격을 방지함. 기존 `unsafe_allow_html=True` 사용 부분의 동적 텍스트 escaping 여부 검토.
5. AI 생성 문구 및 필기 이미지 입력에 크기 제한·타임아웃·쿼터를 적용함.
6. 무료 API 입력/출력은 공급자 약관상 서비스 개선에 이용될 수 있으므로 전송 정보를 최소화하고 개인정보 업로드를 금지하는 사용자 안내를 포함함.
7. 본인 1인 사용을 위해서도 인증과 데이터 백업/복원 경로를 구현함.
8. API 비활성화/쿼터 초과/DB 실패 시 사용자에게 정확한 상태를 노출하고 **저장되지 않았는데 저장되었다고 표현하지 않음**.
9. 운영 환경에서 유료 자동 전환, 장기 반복 백그라운드 대량 호출, 숨겨진 API 모델 자동 변경을 허용하지 않음.
10. Streamlit Community Cloud 및 Supabase 무료 요금제의 프로젝트 일시 중지·스토리지·호출 제한을 문서화하고 가용성을 보장한다고 주장하지 않음.

---

## 11. 테스트 및 배포 체크리스트

### 11.1 테스트 파일(최소)

- `test_legacy_app_smoke.py`: 기존 기능의 주요 흐름 회귀.
- `test_migration.py`: Excel 수량·값 보존, `no`→UUID, 중복/재실행 처리.
- `test_auth_rls.py`: 로그인/로그아웃, 타 사용자 데이터 접근 거부.
- `test_fsrs.py`: Again/Hard/Good/Easy, UTC, 상태 직렬화.
- `test_review_idempotency.py`: 중복 attempt, 두 기기 동시 요청, 저장 오류.
- `test_handwriting.py`: PNG 검증, 빈 필기, OCR 수정, 정답 문자열 비교.
- `test_ai_contracts.py`: 구조화 JSON, 틀린 선택지, 모델 오류/429, 캐시.
- `test_tablet_component`(JS/TS): pen/touch/mouse, resize, Undo/Redo, pointercancel, re-render.

### 11.2 검증 환경

- 로컬 PC: Windows + Python/Streamlit.
- 태블릿: Android 갤럭시탭 + S펜, Chrome 및 Samsung Internet, 가로/세로, 화면 회전 및 멀티윈도우.
- API 정상/키 없음/무료 한도 초과/일시적 네트워크 단절.
- DB 접근 정상/RLS 실패/중복 제출/서버 일시 장애.

### 11.3 배포 원칙

- 로컬 동작 → mock 테스트 → 별도 테스트 DB 검증 → 스테이징 배포 → 사용자 승인 후 운영 배포 순으로 진행함.
- Supabase SQL migration은 코드로 남기고 되돌리기/백업 절차를 문서화함.
- 사용자가 제공하지 않은 키를 추측하거나 실서비스 결제/외부 서비스를 대신 생성하지 않음.
- Git commit/PR은 구현 단계별로 작게 구성함. 운영 배포와 원격 `master` 머지는 별도 사용자 승인 대상으로 취급함.

---

## 12. 단계별 결과 보고 포맷 (Claude가 매 단계 종료 시 출력)

```text
[WordLoop AI — Phase N 결과]
1. 구현 완료: (실제로 변경한 기능만)
2. 주요 변경 파일: (경로 + 변경 요지)
3. 실행/테스트: (명령, 통과/실패 개수, 실제 실행 여부)
4. 데이터 보호: (백업·마이그레이션·원본 유지 확인)
5. 보안/비용: (API 무료 티어/키·RLS·호출량 상태)
6. 미검증·미완료: (실기기 테스트, 사용자 API 키 등)
7. 다음 단계: (바로 이어서 진행 가능한 작업)
```

**절대 금지:** 실제 실행하지 않고 테스트 통과를 주장하는 것, 스크린샷/실기기 결과를 만들어내는 것, 무료 사용량을 무제한으로 홍보하는 것, Gemini OCR 오판을 자동으로 확정된 정답에 반영하는 것, 사용자의 원본 파일/공개 배포를 무단으로 변경하는 것.

---

## 13. Claude Code 첫 실행 지시 (이 파일을 읽은 즉시 실행)

1. 이 저장소가 `kwsahe/english-word-streamlit`인지 확인하고 **현재 코드와 이 문서의 차이를 보고**함.
2. `feature/wordloop-ai-v2` 브랜치 준비, 원본 학습 데이터 백업 및 최초 회귀 테스트 작성 후 테스트 실행.
3. 구현 가능한 범위의 **Phase 1(DB 스키마·RLS·Auth·마이그레이션)** 과 **Phase 2(갤럭시탭 S펜 필기 MVP)** 를 가장 먼저 구체화하고, 단계별로 실제 구현함.
4. Supabase/Gemini 자격 증명이 없으면 mock을 이용해 개발을 계속하면서, 사용자가 직접 입력해야 하는 환경변수·설정 단계를 README 및 `.env.example`에 정확히 기재함.
5. 이후 FSRS/AI 고도화/대시보드를 차례로 개발하고 회귀 테스트 통과 여부를 확인함.
6. 모든 과정에서 **기존 단어장 사용 경험을 살리고 무료 개인용 운영을 기본값으로 유지**함.
7. 최종적으로 변경 파일 목록, 작동하는 기능, 남은 계정 연결·갤럭시탭 실기기 테스트, 실행 명령을 간결하게 보고함.

---

## 14. 공식 참고 링크 (구현 중 버전·정책 재확인)

- Gemini 3.6 Flash 모델: https://ai.google.dev/gemini-api/docs/models/gemini-3.6-flash
- Gemini API 가격·무료 티어: https://ai.google.dev/gemini-api/docs/pricing
- Gemini API 요청 한도: https://ai.google.dev/gemini-api/docs/rate-limits
- 실제 AI Studio 할당량: https://aistudio.google.com/rate-limit
- Streamlit Custom Components v2: https://docs.streamlit.io/develop/concepts/custom-components/components-v2
- Streamlit 컴포넌트 개요: https://docs.streamlit.io/develop/concepts/custom-components/overview
- MDN Pointer Events: https://developer.mozilla.org/en-US/docs/Web/API/Pointer_events
- MDN `touch-action`: https://developer.mozilla.org/en-US/docs/Web/CSS/touch-action
- Py-FSRS: https://github.com/open-spaced-repetition/py-fsrs
- Supabase Row Level Security: https://supabase.com/docs/guides/database/postgres/row-level-security
- Supabase Auth: https://supabase.com/docs/guides/auth
- Supabase 요금제: https://supabase.com/pricing

**이 파일을 프로젝트 실행 지침서로 취급하고, 단계를 실행하며 기능을 구현·검증함. 단순 문서 재작성으로 작업을 종료하지 않음.**
