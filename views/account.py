"""계정·저장소·동기화 상태 (Streamlit UI 계층).

- Supabase 설정(SUPABASE_URL + SUPABASE_ANON_KEY)이 없으면: 로컬 모드(SQLite, 로그인 없음).
- 설정이 있으면: 이메일+비밀번호 로그인 필수, 모든 학습 기록은 로그인 세션(RLS)으로 Supabase에 저장.
- 새로고침 후 세션 복구: refresh token만 이 기기 localStorage('wl_rt')에 둔다(access token은 저장 안 함).
  로그아웃 시 토큰과 이 기기의 필기 초안(IndexedDB 'wordloop')을 함께 삭제한다.
"""
import hashlib
import json
import os
import time

import streamlit as st
from streamlit_js_eval import streamlit_js_eval

from services.config import get_setting, utcnow
from services.store import LocalStore, StoreError, SupabaseStore

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RT_KEY = "wl_rt"


def supabase_configured() -> bool:
    return bool(get_setting("SUPABASE_URL") and _anon_key())


def _anon_key():
    return get_setting("SUPABASE_ANON_KEY") or get_setting("SUPABASE_PUBLISHABLE_KEY")


@st.cache_resource
def _local_store(path: str) -> LocalStore:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return LocalStore(path)


def device_type() -> str:
    ua = (st.context.headers.get("user-agent") or "").lower()
    if "ipad" in ua or ("android" in ua and "mobile" not in ua) or "tablet" in ua:
        return "tablet"
    if "mobi" in ua or "iphone" in ua:
        return "mobile"
    return "desktop"


# ── 브라우저 localStorage 작업 (토큰 저장/삭제). 같은 실행에서 st.rerun()이 나도 다음 실행에 다시 시도 ──
def _queue_js(js: str):
    st.session_state.setdefault("wl_js_ops", {})[hashlib.sha1(js.encode()).hexdigest()[:12]] = js


def _flush_js():
    ops = st.session_state.get("wl_js_ops", {})
    for op_id, js in list(ops.items()):
        if streamlit_js_eval(js_expressions=f"(()=>{{{js}; return 'ok'}})()", key=f"wl_js_{op_id}") == "ok":
            ops.pop(op_id, None)


def _remember_session(session):
    st.session_state.wl_session_exp = session.expires_at or (time.time() + 3000)
    _queue_js(f"localStorage.setItem('{RT_KEY}', {json.dumps(session.refresh_token)})")


def _client():
    if "wl_sb_client" not in st.session_state:
        from supabase import ClientOptions, create_client
        # 자동 갱신을 끄고 직접 갱신: 회전된 refresh token을 항상 localStorage에 다시 써야 하기 때문
        st.session_state.wl_sb_client = create_client(
            get_setting("SUPABASE_URL"), _anon_key(),
            options=ClientOptions(auto_refresh_token=False, persist_session=False))
    return st.session_state.wl_sb_client


def _start_user(user):
    store = SupabaseStore(_client(), user.id)
    store.ensure_profile()
    st.session_state.wl_user = {"id": user.id, "email": user.email}
    st.session_state.wl_store = store
    # 다른 계정 데이터가 섞이지 않게 계정별 세션 상태 초기화
    for k in ("initialized", "wl_vocab", "wl_pending"):
        st.session_state.pop(k, None)


def _ensure_fresh_token():
    if time.time() < st.session_state.get("wl_session_exp", 0) - 120:
        return
    try:
        res = _client().auth.refresh_session()
        _remember_session(res.session)
    except Exception:
        st.session_state.pop("wl_store", None)
        st.session_state.pop("wl_user", None)


def logout():
    pending = len(st.session_state.get("wl_pending", []))
    try:
        _client().auth.sign_out()
    except Exception:
        pass  # 네트워크가 끊겨도 이 기기에서는 로그아웃 처리
    # 미전송 큐는 계정 혼동 방지를 위해 폐기(로그아웃 버튼에서 미리 경고)
    keep = {"wl_js_ops"}
    for k in list(st.session_state.keys()):
        if k not in keep:
            del st.session_state[k]
    _queue_js(f"localStorage.removeItem('{RT_KEY}'); indexedDB.deleteDatabase('wordloop')")
    st.session_state.wl_logged_out = True
    return pending


def _login_form():
    st.title("📚 WordLoop — 로그인")
    st.caption("PC와 갤럭시탭에서 같은 계정으로 로그인하면 학습 기록이 동기화됩니다.")
    login_tab, signup_tab = st.tabs(["로그인", "처음 사용 (가입)"])
    with login_tab, st.form("wl_login"):
        email = st.text_input("이메일", key="wl_login_email")
        pw = st.text_input("비밀번호", type="password", key="wl_login_pw")
        if st.form_submit_button("로그인", type="primary", width="stretch"):
            try:
                res = _client().auth.sign_in_with_password({"email": email.strip(), "password": pw})
                _remember_session(res.session)
                _start_user(res.user)
                st.rerun()
            except Exception:
                st.error("로그인하지 못했습니다. 이메일/비밀번호를 확인하세요. (가입 직후라면 메일의 확인 링크를 먼저 눌러야 합니다)")
    with signup_tab, st.form("wl_signup"):
        email = st.text_input("이메일", key="wl_signup_email")
        pw = st.text_input("비밀번호 (8자 이상)", type="password", key="wl_signup_pw")
        if st.form_submit_button("가입하기", width="stretch"):
            if len(pw) < 8:
                st.error("비밀번호는 8자 이상이어야 합니다.")
            else:
                try:
                    res = _client().auth.sign_up({"email": email.strip(), "password": pw})
                    if res.session:
                        _remember_session(res.session)
                        _start_user(res.user)
                        st.rerun()
                    st.success("가입 확인 메일을 보냈습니다. 메일의 링크를 누른 뒤 로그인하세요.")
                except Exception:
                    st.error("가입하지 못했습니다. 이미 가입한 이메일인지 확인하세요.")


def init():
    """앱 맨 위에서 호출. 저장소를 돌려주며, 로그인 전이면 로그인 화면을 그리고 실행을 멈춘다."""
    if not supabase_configured():
        path = os.environ.get("WORDLOOP_DB_PATH") or os.path.join(BASE_DIR, "data", "wordloop.db")
        return _local_store(path)

    _flush_js()
    if "wl_store" not in st.session_state and not st.session_state.get("wl_logged_out"):
        # 새로고침 후 이 기기에 저장된 refresh token으로 세션 복구 (첫 실행엔 None → 자동 재실행)
        rt = streamlit_js_eval(js_expressions=f"localStorage.getItem('{RT_KEY}') || ''", key="wl_rt_read")
        if rt and not st.session_state.get("wl_rt_tried"):
            st.session_state.wl_rt_tried = True
            try:
                res = _client().auth.refresh_session(rt)
                _remember_session(res.session)
                _start_user(res.user)
            except Exception:
                _queue_js(f"localStorage.removeItem('{RT_KEY}')")
        elif rt is None:
            st.caption("로그인 상태 확인 중…")
    if "wl_store" in st.session_state:
        _ensure_fresh_token()
    if "wl_store" not in st.session_state:
        _login_form()
        st.stop()
    return st.session_state.wl_store


# ── 동기화 상태 + 미전송 큐 ──
def save_with_status(label: str, fn, *args, queue: bool = False, **kwargs):
    """DB 저장 성공을 확인한 뒤에만 '저장됨'으로 표시. 실패 시 queue=True면 미전송 큐에 보관(멱등 작업만)."""
    try:
        result = fn(*args, **kwargs)
        st.session_state.wl_sync = {"state": "saved", "at": utcnow(), "label": label}
        return result
    except StoreError as exc:
        st.session_state.wl_sync = {"state": "failed", "at": utcnow(), "label": label, "error": str(exc)[:120]}
        if queue:
            st.session_state.setdefault("wl_pending", []).append((label, fn, args, kwargs))
        return None


def retry_pending():
    pending, st.session_state.wl_pending = st.session_state.get("wl_pending", []), []
    for label, fn, args, kwargs in pending:
        save_with_status(label, fn, *args, queue=True, **kwargs)


def sidebar(store, ai_status: str):
    with st.sidebar:
        st.markdown("### ☁️ 계정 · 동기화")
        if store.kind == "supabase":
            st.caption(f"로그인: {st.session_state.wl_user['email']}")
        else:
            st.caption("로컬 모드 (이 PC에만 저장). PC↔태블릿 동기화는 Supabase 설정 후 로그인하세요.")
        sync = st.session_state.get("wl_sync")
        pending = st.session_state.get("wl_pending", [])
        if pending:
            st.error(f"동기화 실패 — 미전송 {len(pending)}건 (이 화면을 닫으면 사라집니다)")
            if st.button("🔁 재전송", key="wl_retry", width="stretch"):
                retry_pending()
                st.rerun()
        elif sync and sync["state"] == "failed":
            st.error(f"저장 실패: {sync['label']} — 네트워크 확인 후 다시 시도하세요.")
        elif sync:
            st.success(f"저장됨 · {sync['label']}")
        else:
            st.caption("아직 이번 접속에서 저장한 기록이 없습니다.")
        st.caption(ai_status)
        if store.kind == "supabase":
            if pending:
                st.warning("로그아웃하면 미전송 기록은 이 기기에서 삭제됩니다.")
            if st.button("로그아웃", key="wl_logout", width="stretch"):
                logout()
                st.rerun()
