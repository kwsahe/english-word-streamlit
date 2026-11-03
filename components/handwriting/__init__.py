"""S펜 필기 캔버스 (Streamlit Components v2, 양방향). iframe DOM 탐색 없이 제출 이벤트로 PNG를 받는다."""
from pathlib import Path

import streamlit as st

_DIR = Path(__file__).parent
_JS = (_DIR / "handwriting.js").read_text(encoding="utf-8")
_CSS = (_DIR / "handwriting.css").read_text(encoding="utf-8")


def handwriting_canvas(*, key: str, draft_key: str, user_scope: str, guide: str = "", show_guide: bool = True,
                       pen_only_default: bool = True, submit_label: str = "제출", busy: bool = False,
                       clear_keys: list[str] | None = None, reset_token: int = 0, aspect: float = 0.5):
    """반환값의 `.submit`은 제출 버튼을 누른 실행에서만 값이 있다:
    {png: data URL, submit_id, draft_key, strokes, points, pointer_types, ignored_touch}
    """
    # 등록은 실행마다: 런타임이 바뀌어도(재시작·테스트) 항상 등록돼 있게. 같은 정의 재등록은 경고 없음.
    component = st.components.v2.component("wordloop_handwriting", js=_JS, css=_CSS)
    return component(
        key=key,
        data={
            "draft_key": draft_key, "user_scope": user_scope, "guide": guide, "show_guide": show_guide,
            "pen_only_default": pen_only_default, "submit_label": submit_label, "busy": busy,
            "clear_keys": clear_keys or [], "reset_token": reset_token, "aspect": aspect,
        },
        on_submit_change=lambda: None,
    )
