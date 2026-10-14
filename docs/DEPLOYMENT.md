# 배포 · 운영

> 운영 배포와 원격 `master` 머지는 사용자 승인 후에만 진행합니다. 아래는 사용자가 직접 하는 절차입니다.

## 순서

1. 로컬 동작 확인 → 2. mock 테스트(`pytest`) → 3. 로컬 Supabase 통합 테스트 → 4. 별도 Supabase **테스트** 프로젝트 → 5. 스테이징(별도 Streamlit 앱, feature 브랜치) → 6. 승인 후 운영(`master`)

## 1. 로컬 Supabase (테스트용)

```bash
npx supabase@2.120.0 start          # Docker 필요. 이 프로젝트 포트는 55321(API)/55322(DB)
npx supabase@2.120.0 status -o env  # API_URL, ANON_KEY 확인 (로컬 전용 값)
npx supabase@2.120.0 db reset       # 마이그레이션 다시 적용 (로컬 데이터 삭제)
npx supabase@2.120.0 stop
```

로컬 Auth는 이메일 확인 없이 가입됩니다(`config.toml`의 `enable_confirmations = false`). 운영 프로젝트 설정과 다릅니다.

## 2. Supabase 클라우드 프로젝트

1. <https://supabase.com> 에서 무료(Free) 플랜 프로젝트 생성 (지역: Northeast Asia (Seoul) 권장). 결제 수단은 등록하지 않아도 됩니다.
2. 스키마 적용 — 둘 중 하나:
   - SQL Editor에 `supabase/migrations/20261014000000_wordloop_init.sql` 내용을 붙여 넣고 실행
   - 또는 `npx supabase@2.120.0 link --project-ref <ref>` 후 `npx supabase@2.120.0 db push`
3. Authentication → Providers → Email 활성화(기본값). "Confirm email"은 켠 채로 두는 것을 권장합니다(가입 시 확인 메일 1회).
4. Authentication → URL Configuration의 Site URL을 앱 주소로 설정 (확인 메일 링크가 돌아올 곳).
5. Project Settings → API에서 **Project URL**과 **anon(또는 publishable) key**만 복사합니다. `service_role`/secret 키는 이 앱에 넣지 않습니다.
6. 확인: 다른 계정 2개로 로그인해 서로의 단어·기록이 보이지 않는지 확인 (자동 테스트는 로컬에서 이미 수행).

## 3. Streamlit Community Cloud

1. 앱 설정 → Secrets에 아래만 입력 (값은 Git에 올리지 않음):

```toml
GEMINI_API_KEY = "..."           # 선택
SUPABASE_URL = "https://<ref>.supabase.co"
SUPABASE_ANON_KEY = "..."
DAILY_AI_REQUEST_BUDGET = "40"
```

2. Python 3.12, `requirements.txt`(버전 고정) 사용.
3. 스테이징은 같은 저장소의 `feature/wordloop-ai-v2` 브랜치로 **별도 앱**을 만들어 확인합니다. 운영 앱(`honeyenglish`)은 승인 후 `master` 머지로 갱신합니다.
4. Supabase를 설정하지 않고 클라우드에 올리면 로컬 모드(SQLite)가 되는데, 이 파일은 모든 방문자가 공유하고 재시작 시 사라질 수 있습니다. 클라우드에서는 Supabase 설정을 권장합니다.

## 4. 갤럭시탭 사용

- Chrome 또는 삼성 인터넷으로 앱 주소 접속 → 로그인 → 메뉴 "홈 화면에 추가". 주소를 `.../?tab=write`로 하면 S펜 쓰기 연습이 바로 열립니다.
- 같은 Wi-Fi에서 PC 서버를 쓸 때는 `start_server.bat` 실행 후 `http://<PC IP>:8501`.

## 5. 무료 요금제 주의 (작성 시점 기준, 요금제 페이지에서 다시 확인)

- Supabase Free: 일정 기간 사용이 없으면 프로젝트가 일시 중지되고, DB 용량·Auth 메일 발송 수에 제한이 있습니다. 내장 메일 발송은 시간당 몇 통 수준이라 매 로그인 메일 인증 대신 비밀번호 로그인을 택했습니다. <https://supabase.com/pricing>
- Streamlit Community Cloud: 트래픽이 없으면 앱이 잠들고, 리소스 제한이 있습니다.
- Gemini API 무료 등급: 모델별 RPM/RPD 한도가 있고 바뀔 수 있습니다. 앱은 사용자당 최근 24시간 상한(`DAILY_AI_REQUEST_BUDGET`)과 회로차단으로 보수적으로 동작합니다. 무료 등급 입력은 서비스 개선에 쓰일 수 있으므로 개인정보를 쓰지 마세요.

가용성을 보장하지 않습니다. 정기 백업: 앱 ✏️ 단어 관리 → 💾 백업(단어장 Excel, 학습 기록 JSON).

## 6. 되돌리기

- 앱: 이전 커밋으로 되돌리면 로컬 모드 파일(`Word.xlsx`, `progress.json`)은 그대로 쓸 수 있습니다.
- DB: `supabase/rollback/20261014000000_wordloop_init_down.sql` (모든 학습 데이터 삭제 — 실행 전 Supabase 대시보드에서 백업).
- 원본 데이터 백업: 개발 PC의 `.backup/20261014/` (SHA-256 체크섬 포함, Git 제외).

## 7. 비밀값 점검

```bash
git ls-files | grep -iE "secrets\.toml$|\.env$|\.db$|progress\.json"   # 결과가 없어야 정상
git log --all -p | grep -cE "AIza[0-9A-Za-z_-]{20,}|service_role|sb_secret_"   # 0이어야 정상
```

`progress.json`은 v2부터 추적을 중단했습니다(로컬 파일은 유지). 과거 커밋 이력에는 2026-04 시점 학습 기록이 남아 있습니다. 이력 재작성(force push)은 하지 않았습니다.
