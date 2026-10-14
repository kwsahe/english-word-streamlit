"""AIService 생성(프로세스 공용 회로차단기·잠금) + 상태 표시."""
import streamlit as st

from services.ai import AIService, CircuitBreaker, GeminiProvider
from services.config import get_bool, get_int, get_setting

# 테스트에서 FakeProvider를 끼워 넣는 지점 (AppTest는 같은 프로세스에서 앱을 실행한다)
PROVIDER_OVERRIDE = None


@st.cache_resource
def _provider(api_key: str):
    return GeminiProvider(api_key)


@st.cache_resource
def _shared():
    # 같은 API 키를 쓰는 모든 세션이 공유: 연속 실패 시 다 같이 쉬고, 같은 요청 중복 실행을 막는다
    return CircuitBreaker(), {}


def get_ai(store) -> AIService:
    breaker, locks = _shared()
    provider = PROVIDER_OVERRIDE
    if provider is None and get_bool("ENABLE_AI") and get_setting("GEMINI_API_KEY"):
        try:
            provider = _provider(get_setting("GEMINI_API_KEY"))
        except Exception:
            provider = None
    return AIService(provider, store, model_main=get_setting("GEMINI_MODEL_MAIN"),
                     model_lite=get_setting("GEMINI_MODEL_LITE"), daily_budget=get_int("DAILY_AI_REQUEST_BUDGET"),
                     breaker=breaker, locks=locks,
                     fallback_model=get_setting("GEMINI_MODEL_LITE") if get_bool("GEMINI_ALLOW_FALLBACK") else None)


def status_text(ai: AIService) -> str:
    if not ai.enabled:
        return "🤖 AI 꺼짐 — 플래시카드·시험·복습·필기(직접 입력)는 그대로 동작합니다."
    try:
        left = ai.remaining_budget()
    except Exception:
        return "🤖 AI 켜짐 (사용량 확인 실패)"
    state = " · 일시 중지(연속 실패)" if ai.breaker.is_open else ""
    return (f"🤖 AI 켜짐 · 오늘 남은 요청 {left}/{ai.daily_budget}{state}\n\n"
            f"모델: {ai.model_main} / {ai.model_lite}"
            f"{' (MAIN 무응답 시 LITE로 1회 전환)' if ai.fallback_model else ''}. 실제 무료 한도는 AI Studio(aistudio.google.com/rate-limit)에서 확인하세요.")
