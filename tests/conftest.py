import os
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture
def data_copy(tmp_path, monkeypatch):
    """원본 Word.xlsx/progress.json 대신 임시 사본을 앱에 연결한다."""
    excel = tmp_path / "Word.xlsx"
    progress = tmp_path / "progress.json"
    shutil.copy(ROOT / "Word.xlsx", excel)
    if (ROOT / "progress.json").exists():
        shutil.copy(ROOT / "progress.json", progress)
    else:
        progress.write_text('{"memorized":[],"wrong":[],"correct":[],"sessions":[]}', encoding="utf-8")
    monkeypatch.setenv("WORDLOOP_EXCEL_PATH", str(excel))
    monkeypatch.setenv("WORDLOOP_PROGRESS_PATH", str(progress))
    monkeypatch.setenv("WORDLOOP_DB_PATH", str(tmp_path / "wordloop.db"))
    # 실제 키·Supabase 설정이 테스트로 새어 들어오지 않게 한다.
    for name in ("GEMINI_API_KEY", "SUPABASE_URL", "SUPABASE_ANON_KEY"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


@pytest.fixture
def app_test(data_copy):
    from streamlit.testing.v1 import AppTest

    def make():
        at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=90)
        # 비어 있지 않은 secrets를 넘겨야 실제 .streamlit/secrets.toml(실 API 키)이 로드되지 않는다.
        at.secrets["WORDLOOP_TEST"] = True
        at.run()
        assert not at.exception, at.exception
        return at

    return make


# ── Supabase 통합 테스트 (로컬 `supabase start` 또는 별도 테스트 프로젝트) ──
# WORDLOOP_TEST_SUPABASE_URL / WORDLOOP_TEST_SUPABASE_ANON_KEY 가 없으면 건너뛴다.
# 운영 프로젝트 키를 넣지 말 것: 테스트가 임의 계정을 만든다.
def _supabase_env():
    url = os.environ.get("WORDLOOP_TEST_SUPABASE_URL")
    key = os.environ.get("WORDLOOP_TEST_SUPABASE_ANON_KEY")
    if not (url and key):
        pytest.skip("Supabase 테스트 DB 미설정")
    return url, key


def _client(url, key):
    from supabase import ClientOptions, create_client
    return create_client(url, key, options=ClientOptions(auto_refresh_token=False, persist_session=False))


@pytest.fixture
def supabase_user():
    url, key = _supabase_env()
    import uuid

    from services.store import SupabaseStore

    def make():
        client = _client(url, key)
        email = f"wl-test-{uuid.uuid4().hex[:10]}@example.com"
        res = client.auth.sign_up({"email": email, "password": "test-password-123"})
        assert res.session is not None, "로컬 Supabase는 이메일 확인 없이 가입되어야 함"
        return client, SupabaseStore(client, res.user.id)

    return make


@pytest.fixture
def anon_client():
    return _client(*_supabase_env())
