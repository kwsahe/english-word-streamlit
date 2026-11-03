-- WordLoop AI v2 초기 스키마 (Supabase PostgreSQL)
-- 원칙: 모든 시간은 UTC(timestamptz), 개인 데이터는 RLS로 본인만 접근, anon 역할은 접근 불가.
-- 되돌리기: supabase/rollback/20261014000000_wordloop_init_down.sql

-- ───────────────────────── 테이블 ─────────────────────────
create table public.profiles (
    user_id            uuid primary key default auth.uid() references auth.users (id) on delete cascade,
    display_name       text check (char_length(display_name) <= 80),
    -- 기존 앱의 memorized/wrong/correct/sessions 표시 상태(legacy UI 호환용)
    legacy_state       jsonb not null default '{}'::jsonb,
    -- progress.json 1회 가져오기 표시 (중복 가져오기 방지)
    legacy_imported_at timestamptz,
    settings           jsonb not null default '{}'::jsonb,
    created_at         timestamptz not null default now(),
    updated_at         timestamptz not null default now()
);

create table public.vocabulary (
    word_id       uuid primary key default gen_random_uuid(),
    -- NULL = 공용 단어(조회만 가능), 값 = 개인 단어(작성자만 CRUD)
    owner_user_id uuid references auth.users (id) on delete cascade,
    source_no     integer check (source_no > 0),
    word          text not null check (char_length(word) between 1 and 200),
    meaning       text not null default '' check (char_length(meaning) <= 1000),
    example       text not null default '' check (char_length(example) <= 2000),
    ai_example    text not null default '' check (char_length(ai_example) <= 2000),
    category      text not null default '기타' check (char_length(category) <= 100),
    -- Excel E/F열(암기 체크, 입력 날짜) 등 원본 부가값 보존
    extra         jsonb not null default '{}'::jsonb,
    created_at    timestamptz not null default now(),
    updated_at    timestamptz not null default now(),
    -- 같은 철자/다의어는 병합하지 않는다. 원본 번호만 소유자별로 유일.
    constraint vocabulary_owner_source_no unique nulls not distinct (owner_user_id, source_no)
);

create table public.word_progress (
    user_id        uuid not null default auth.uid() references auth.users (id) on delete cascade,
    word_id        uuid not null references public.vocabulary (word_id) on delete cascade,
    fsrs_card      jsonb not null,
    due_at         timestamptz not null,
    last_review_at timestamptz,
    review_count   integer not null default 0 check (review_count >= 0),
    lapse_count    integer not null default 0 check (lapse_count >= 0),
    version        integer not null default 1 check (version >= 1),
    updated_at     timestamptz not null default now(),
    primary key (user_id, word_id)
);

create table public.test_sessions (
    session_id  uuid primary key default gen_random_uuid(),
    user_id     uuid not null default auth.uid() references auth.users (id) on delete cascade,
    mode        text not null check (char_length(mode) <= 60),
    total       integer not null check (total >= 0),
    correct     integer not null check (correct >= 0 and correct <= total),
    started_at  timestamptz,
    finished_at timestamptz not null default now()
);

create table public.review_events (
    event_id    uuid primary key default gen_random_uuid(),
    attempt_id  uuid not null unique,               -- 멱등 키 (중복 제출 1회 반영)
    user_id     uuid not null default auth.uid() references auth.users (id) on delete cascade,
    word_id     uuid not null references public.vocabulary (word_id) on delete cascade,
    session_id  uuid,
    mode        text not null check (char_length(mode) <= 60),
    correct     boolean,
    rating      smallint not null check (rating between 1 and 4),
    duration_ms integer check (duration_ms between 0 and 86400000),
    device_type text check (char_length(device_type) <= 20),
    due_before  timestamptz,
    due_after   timestamptz not null,
    created_at  timestamptz not null default now()
);

create table public.writing_attempts (
    attempt_id     uuid primary key,
    user_id        uuid not null default auth.uid() references auth.users (id) on delete cascade,
    word_id        uuid not null references public.vocabulary (word_id) on delete cascade,
    mode           text not null check (char_length(mode) <= 60),
    ocr_text       text check (char_length(ocr_text) <= 2000),
    confirmed_text text check (char_length(confirmed_text) <= 2000),
    feedback       jsonb not null default '{}'::jsonb,
    -- ocr: AI 판독 후 확인, manual: AI 없이 직접 입력/수동 채점, self: 따라쓰기 자기평가
    status         text not null check (status in ('ocr', 'manual', 'self')),
    correct        boolean,
    created_at     timestamptz not null default now()
);

create table public.ai_cache (
    user_id        uuid not null default auth.uid() references auth.users (id) on delete cascade,
    cache_key      text not null check (char_length(cache_key) <= 128),
    feature        text not null,
    model_id       text not null,
    prompt_version text not null,
    result         jsonb not null,
    expires_at     timestamptz,
    valid          boolean not null default true,
    created_at     timestamptz not null default now(),
    -- 캐시는 사용자별(타인이 넣은 결과를 재사용하는 캐시 오염 방지)
    primary key (user_id, cache_key)
);

create table public.ai_usage (
    request_id uuid primary key default gen_random_uuid(),
    user_id    uuid not null default auth.uid() references auth.users (id) on delete cascade,
    feature    text not null,
    model_id   text not null,
    tokens_in  integer,
    tokens_out integer,
    -- ok | cache_hit | invalid | rate_limited | error | timeout | blocked
    status     text not null check (char_length(status) <= 30),
    created_at timestamptz not null default now()
);

-- ───────────────────────── 인덱스 ─────────────────────────
create index vocabulary_owner_idx on public.vocabulary (owner_user_id);
create index word_progress_due_idx on public.word_progress (user_id, due_at);
create index review_events_user_time_idx on public.review_events (user_id, created_at);
create index review_events_word_idx on public.review_events (user_id, word_id);
create index writing_attempts_user_time_idx on public.writing_attempts (user_id, created_at);
create index test_sessions_user_time_idx on public.test_sessions (user_id, finished_at);
create index ai_usage_user_time_idx on public.ai_usage (user_id, created_at);

-- ───────────────────────── 권한 (최소 권한) ─────────────────────────
-- Supabase 기본 설정은 새 테이블에 anon/authenticated 전체 권한을 주므로 먼저 모두 회수한다.
revoke all on public.profiles, public.vocabulary, public.word_progress, public.test_sessions,
    public.review_events, public.writing_attempts, public.ai_cache, public.ai_usage
    from anon, authenticated, public;

grant select, insert, update on public.profiles to authenticated;
grant select, insert, update, delete on public.vocabulary to authenticated;
grant select, insert, update on public.word_progress to authenticated;
grant select, insert on public.test_sessions to authenticated;
grant select, insert on public.review_events to authenticated;          -- 불변 이력: update/delete 없음
grant select, insert on public.writing_attempts to authenticated;
grant select, insert, update, delete on public.ai_cache to authenticated;
grant select, insert on public.ai_usage to authenticated;

-- ───────────────────────── RLS ─────────────────────────
alter table public.profiles enable row level security;
alter table public.vocabulary enable row level security;
alter table public.word_progress enable row level security;
alter table public.test_sessions enable row level security;
alter table public.review_events enable row level security;
alter table public.writing_attempts enable row level security;
alter table public.ai_cache enable row level security;
alter table public.ai_usage enable row level security;

create policy profiles_own on public.profiles for all to authenticated
    using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));

-- 공용 단어는 로그인 사용자 누구나 조회, 개인 단어는 소유자만 조회/변경
create policy vocabulary_read on public.vocabulary for select to authenticated
    using (owner_user_id is null or owner_user_id = (select auth.uid()));
create policy vocabulary_insert_own on public.vocabulary for insert to authenticated
    with check (owner_user_id = (select auth.uid()));
create policy vocabulary_update_own on public.vocabulary for update to authenticated
    using (owner_user_id = (select auth.uid())) with check (owner_user_id = (select auth.uid()));
create policy vocabulary_delete_own on public.vocabulary for delete to authenticated
    using (owner_user_id = (select auth.uid()));

create policy word_progress_own on public.word_progress for all to authenticated
    using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));
create policy test_sessions_select_own on public.test_sessions for select to authenticated
    using (user_id = (select auth.uid()));
create policy test_sessions_insert_own on public.test_sessions for insert to authenticated
    with check (user_id = (select auth.uid()));
create policy review_events_select_own on public.review_events for select to authenticated
    using (user_id = (select auth.uid()));
create policy review_events_insert_own on public.review_events for insert to authenticated
    with check (user_id = (select auth.uid()));
create policy writing_attempts_select_own on public.writing_attempts for select to authenticated
    using (user_id = (select auth.uid()));
create policy writing_attempts_insert_own on public.writing_attempts for insert to authenticated
    with check (user_id = (select auth.uid()));
create policy ai_cache_own on public.ai_cache for all to authenticated
    using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));
create policy ai_usage_select_own on public.ai_usage for select to authenticated
    using (user_id = (select auth.uid()));
create policy ai_usage_insert_own on public.ai_usage for insert to authenticated
    with check (user_id = (select auth.uid()));

-- ───────────────────────── 복습 기록 RPC (원자적 + 멱등 + CAS) ─────────────────────────
-- FSRS 계산은 앱(Python)에서 하고, DB는 "이벤트 추가 + 카드 갱신"을 한 트랜잭션으로 처리한다.
-- p_expected_version: 읽었을 때의 version (새 카드면 0). 다르면 'conflict' → 앱이 다시 읽고 재계산.
create or replace function public.record_review(
    p_attempt_id       uuid,
    p_word_id          uuid,
    p_expected_version integer,
    p_fsrs_card        jsonb,
    p_due_at           timestamptz,
    p_reviewed_at      timestamptz,
    p_rating           integer,
    p_correct          boolean,
    p_mode             text,
    p_duration_ms      integer default null,
    p_device_type      text default null,
    p_session_id       uuid default null,
    p_due_before       timestamptz default null
) returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_uid  uuid := auth.uid();
    v_rows integer;
begin
    if v_uid is null then
        raise exception 'not authenticated' using errcode = '28000';
    end if;
    if exists (select 1 from public.review_events where attempt_id = p_attempt_id) then
        return jsonb_build_object('status', 'duplicate');
    end if;
    -- RLS가 적용된 조회: 볼 수 없는 단어에는 기록 불가
    if not exists (select 1 from public.vocabulary where word_id = p_word_id) then
        raise exception 'word not found' using errcode = 'P0002';
    end if;

    if p_expected_version = 0 then
        insert into public.word_progress
            (user_id, word_id, fsrs_card, due_at, last_review_at, review_count, lapse_count, version)
        values
            (v_uid, p_word_id, p_fsrs_card, p_due_at, p_reviewed_at, 1, (p_rating = 1)::integer, 1)
        on conflict (user_id, word_id) do nothing;
    else
        update public.word_progress
           set fsrs_card = p_fsrs_card,
               due_at = p_due_at,
               last_review_at = p_reviewed_at,
               review_count = review_count + 1,
               lapse_count = lapse_count + (p_rating = 1)::integer,
               version = version + 1,
               updated_at = now()
         where user_id = v_uid and word_id = p_word_id and version = p_expected_version;
    end if;
    get diagnostics v_rows = row_count;
    if v_rows = 0 then
        return jsonb_build_object('status', 'conflict');
    end if;

    insert into public.review_events
        (attempt_id, user_id, word_id, session_id, mode, correct, rating, duration_ms,
         device_type, due_before, due_after, created_at)
    values
        (p_attempt_id, v_uid, p_word_id, p_session_id, p_mode, p_correct, p_rating, p_duration_ms,
         p_device_type, p_due_before, p_due_at, p_reviewed_at);

    return jsonb_build_object('status', 'ok', 'version', p_expected_version + 1);
exception
    when unique_violation then
        -- 같은 attempt_id가 동시에 들어온 경우: 블록 전체가 롤백되고 1회만 반영된다.
        return jsonb_build_object('status', 'duplicate');
end;
$$;

revoke all on function public.record_review from public, anon;
grant execute on function public.record_review to authenticated;
