-- 20261014000000_wordloop_init 되돌리기 (데이터가 삭제되므로 실행 전 백업 필수)
drop function if exists public.record_review;
drop table if exists public.ai_usage, public.ai_cache, public.writing_attempts, public.review_events,
    public.test_sessions, public.word_progress, public.vocabulary, public.profiles;
