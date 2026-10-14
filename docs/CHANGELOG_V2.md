# CHANGELOG — WordLoop v2 (`feature/wordloop-ai-v2`)

## Phase 0 — 기준선
- 기존 7개 탭 AppTest 회귀 테스트(임시 데이터 사본, 실제 API 키 로드 차단)
- 의존성 버전 고정(Streamlit 1.65.0 등), `requirements-dev.txt`
- `progress.json` Git 추적 중단(로컬 파일 유지), 원본 백업 + SHA-256

## Phase 1 — DB·인증·동기화
- Supabase 스키마 8개 테이블, 최소 권한 GRANT, 테이블별 RLS, `record_review` RPC(멱등 + CAS)
- `LocalStore`(SQLite) / `SupabaseStore` 동일 계약
- 이메일+비밀번호 로그인, refresh token 기반 새로고침 복구, 저장 상태 표시와 미전송 큐
- Word.xlsx·progress.json 1회 가져오기(재실행 무중복, 체크섬 비교), localStorage 진도 미리보기·병합, 백업/복원

## Phase 2 — 갤럭시탭 S펜 필기
- Components v2 필기 캔버스: pen/touch/mouse 구분, S펜 전용·터치 호환, 단일 활성 포인터, coalesced events, 필압, 벡터 획, Undo/Redo/지우개, IndexedDB 초안
- 필기 → OCR(정답 미제공) → 사용자 확인 → Python 채점 → FSRS 평가 → 1회 저장, AI 실패 시 직접 입력/수동 채점
- 서버측 PNG 검증, 철자 정규화 정책
- AIService(구조화 출력·캐시·상한·재시도·회로차단·보조 모델 전환), 기존 AI 기능 통합
- HTML/JS 주입 방지(동적 텍스트 이스케이프, TTS 버튼), 태블릿 40/60 레이아웃·세로 스택

## Phase 3 — FSRS
- 🏠 오늘 탭: 기한 지남/지금 만기/오늘 이따가/새 단어, 실측 정답률, 예상 시간, 반복 오답, 목표량 저장
- 빠른 복습(플래시카드·객관식·타이핑), Again/Good 추천 + 사용자 선택

## Phase 4 — AI 고도화
- AI 계약 테스트 24개, AI 토익 문항별 검증·대체·신고, 오답 복습 큐, 헷갈린 단어 비교, 하루 1회 코치(버튼 호출)
- 대량 예문 생성: 최대 20개 배치, 남은 한도 표시, 확인 체크, 한도·연속 실패 시 중단

## Phase 5 — 분석·문서·CI
- 학습 분석 대시보드(실측/추정 구분, 표본 수 표시), 합성 데모 데이터 스크립트
- `?tab=` 시작 탭 지정(태블릿 홈 화면 바로가기)
- README·ARCHITECTURE·DATA_MODEL·TABLET_QA·AI_EVALUATION·DEPLOYMENT, GitHub Actions(단위 + 로컬 Supabase 통합)

## 알려진 미완료
- 갤럭시탭 실기기 QA (docs/TABLET_QA.md §3)
- 사용자 Supabase 클라우드 프로젝트 연결·운영 배포 (사용자 승인 필요)
- FSRS vs 무작위 비교 실험의 무작위 출제 모드
- `st.components.v1.html`(TTS 버튼, localStorage 쓰기)은 Streamlit에서 사용 중단 예고 상태 — 버전 고정으로 동작 유지, 이후 v2로 교체 필요
