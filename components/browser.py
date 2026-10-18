"""브라우저 기능 (Streamlit Components v2): TTS 발음 버튼, localStorage 읽기/쓰기.

사용 중단 예고된 `st.components.v1.html`(iframe + 인라인 <script>)을 대체한다.
값은 data로만 넘기고 DOM에는 textContent로 넣는다(HTML/JS 주입 없음).
"""
import streamlit as st

_TTS_JS = """
export default function ({ data, parentElement }) {
  let btn = parentElement.querySelector('button');
  if (!btn) {
    btn = document.createElement('button');
    btn.type = 'button';
    btn.textContent = '🔊 발음 듣기';
    parentElement.appendChild(btn);
  }
  const ok = 'speechSynthesis' in window;
  btn.disabled = !ok;
  btn.title = ok ? `${data.word} 발음 듣기` : '이 브라우저는 음성 재생을 지원하지 않습니다';
  btn.onclick = () => {
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(data.word);
    u.lang = 'en-US';
    u.rate = 0.85;
    window.speechSynthesis.speak(u);
  };
}
"""

_TTS_CSS = """
button {
  display: flex; align-items: center; gap: 6px; margin: 4px auto;
  min-height: 48px; padding: 10px 20px; border: none; border-radius: 10px;
  background: #1565C0; color: #fff; font-size: 1.1rem; cursor: pointer; touch-action: manipulation;
}
button:disabled { opacity: 0.5; cursor: not-allowed; }
"""

# write: 문자열이면 저장(빈 문자열이면 삭제), null이면 읽기만.
# report: true면 현재 값을 Python으로 돌려준다(값이 바뀔 때만 → 불필요한 재실행 없음).
_STORAGE_JS = """
const reported = new WeakMap();
export default function ({ data, parentElement, setStateValue }) {
  let current = null;
  try {
    if (typeof data.write === 'string') {
      if (data.write === '') localStorage.removeItem(data.key);
      else if (localStorage.getItem(data.key) !== data.write) localStorage.setItem(data.key, data.write);
    }
    current = localStorage.getItem(data.key);
  } catch (e) {
    current = null; // 사생활 보호 모드 등: 저장소 사용 불가
  }
  if (!data.report) return;
  const value = current === null ? '' : current;
  if (reported.get(parentElement) !== data.key + '\\u0000' + value) {
    reported.set(parentElement, data.key + '\\u0000' + value);
    setStateValue('value', value);
  }
}
"""


def tts_button(word: str, key: str = "tts"):
    st.components.v2.component("wordloop_tts", js=_TTS_JS, css=_TTS_CSS)(key=key, data={"word": word})


def local_storage(storage_key: str, *, key: str, write: str | None = None, report: bool = True) -> str | None:
    """이 브라우저의 localStorage 값. 첫 실행에는 None(아직 모름), 값이 없으면 ''."""
    component = st.components.v2.component("wordloop_storage", js=_STORAGE_JS)
    result = component(key=key, data={"key": storage_key, "write": write, "report": report},
                       default={"value": None}, on_value_change=lambda: None, height=0)
    return getattr(result, "value", None) if report else None
