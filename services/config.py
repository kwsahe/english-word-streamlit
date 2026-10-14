"""설정값 읽기: st.secrets → 환경변수 → 기본값 순서. 비밀값 자체는 로그/화면에 출력하지 않는다."""
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

DEFAULTS = {
    "GEMINI_MODEL_MAIN": "gemini-3.6-flash",       # 필기 OCR, 문장 교정, TOEIC 문제
    "GEMINI_MODEL_LITE": "gemini-3.5-flash-lite",  # 예문, 자동완성, 비교표 등 저비용 텍스트
    "ENABLE_AI": "true",
    "DAILY_AI_REQUEST_BUDGET": "40",               # 사용자당 최근 24시간 실제 API 호출 상한(보수적 기본값)
    "APP_TIMEZONE": "Asia/Seoul",
    "HANDWRITING_MAX_BYTES": "1500000",
    "HANDWRITING_MAX_SIDE": "2048",
}


def get_setting(name: str, default: str | None = None) -> str | None:
    try:
        import streamlit as st
        value = st.secrets.get(name)
    except Exception:  # secrets.toml 없음 / Streamlit 밖에서 실행
        value = None
    if value in (None, ""):
        value = os.environ.get(name)
    if value in (None, ""):
        value = DEFAULTS.get(name, default)
    return value


def get_bool(name: str) -> bool:
    return str(get_setting(name, "false")).strip().lower() in ("1", "true", "yes", "on")


def get_int(name: str) -> int:
    return int(get_setting(name, "0"))


def app_tz() -> ZoneInfo:
    return ZoneInfo(get_setting("APP_TIMEZONE"))


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_utc_iso(dt: datetime) -> str:
    """DB 저장 형식: 항상 UTC ISO 문자열(+00:00). 문자열 비교로 시간 순서가 유지된다."""
    if dt.tzinfo is None:
        raise ValueError("naive datetime은 저장하지 않습니다 (UTC 필요)")
    return dt.astimezone(timezone.utc).isoformat()


def parse_dt(value) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
