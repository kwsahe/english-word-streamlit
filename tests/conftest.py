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
