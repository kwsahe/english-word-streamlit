"""단어 가져오기 · 진도 병합 · 백업/복원 화면 (로그인 모드)."""
import io
import json
import os

import streamlit as st

from services import migrate
from services.config import utcnow
from services.store import StoreError


def _import_words(store, words) -> dict | None:
    try:
        return migrate.import_vocabulary(store, words)
    except StoreError:
        st.error("단어를 저장하지 못했습니다. 네트워크를 확인하고 다시 시도하세요. (원본 파일은 변경되지 않았습니다)")
        return None


def _show_report(rep):
    ok = rep["db_count"] == rep["source_count"] and rep["source_checksum"] == rep["db_checksum"]
    msg = (f"원본 {rep['source_count']}개 → DB {rep['db_count']}개 (신규 {rep['inserted']}, "
           f"기존 유지 {rep['skipped_existing']}) · 내용 체크섬 {'일치' if ok else '불일치'}")
    (st.success if ok else st.warning)(msg)


def first_run_import(store, excel_path: str, progress_path: str):
    st.subheader("👋 처음 오셨네요 — 단어장 가져오기")
    st.write("이 계정에는 아직 단어가 없습니다. 기존 `Word.xlsx` 단어를 이 계정으로 한 번 가져오면 "
             "PC와 갤럭시탭에서 같은 단어장·기록을 쓰게 됩니다. 원본 Excel 파일은 수정하지 않습니다.")
    if os.path.exists(excel_path):
        words = migrate.read_excel_words(excel_path)
        st.caption(f"Word.xlsx 단어 {len(words)}개 · 다의어(같은 철자)는 합치지 않고 그대로 가져옵니다.")
        if st.button(f"📥 {len(words)}개 단어 가져오기", type="primary", width="stretch"):
            rep = _import_words(store, words)
            if rep:
                _show_report(rep)
                st.session_state.pop("wl_vocab", None)
                st.rerun()
    uploaded = st.file_uploader("또는 백업한 단어장 Excel(.xlsx) 업로드", type=["xlsx"], key="wl_first_upload")
    if uploaded and st.button("업로드한 파일로 가져오기", width="stretch"):
        _restore_from_upload(store, uploaded)


def _restore_from_upload(store, uploaded):
    try:
        words = migrate.read_excel_words(io.BytesIO(uploaded.getvalue()))
    except Exception:
        st.error("엑셀을 읽지 못했습니다. '영어 단어장' 시트가 있는 원본 형식인지 확인하세요.")
        return
    rep = _import_words(store, words)
    if rep:
        _show_report(rep)
        st.session_state.pop("wl_vocab", None)


def legacy_panel(store, progress_path: str, ls_raw, valid_nos: set):
    """progress.json 1회 가져오기 + 이 기기 브라우저에 남은 이전 진도 미리보기/병합."""
    profile = store.get_profile() or {}
    server = profile.get("legacy_state") or {}
    if not profile.get("legacy_imported_at") and os.path.exists(progress_path):
        with open(progress_path, encoding="utf-8") as f:
            local = migrate.legacy_state(json.load(f), valid_nos)
        st.info(f"이 PC의 progress.json에 이전 진도가 있습니다: 암기 {len(local['memorized'])}, "
                f"오답 {len(local['wrong'])}, 정답 {len(local['correct'])}, 시험 {len(local['sessions'])}회")
        if st.button("📥 progress.json 진도 가져오기 (1회)", key="wl_import_progress"):
            try:
                with open(progress_path, encoding="utf-8") as f:
                    migrate.import_legacy_progress(store, json.load(f), valid_nos, utcnow())
                st.session_state.pop("initialized", None)
                st.rerun()
            except StoreError:
                st.error("가져오지 못했습니다(동기화 실패). 다시 시도하세요.")

    if ls_raw and ls_raw not in ("null", "undefined") and not st.session_state.get("wl_ls_dismissed"):
        try:
            browser = migrate.legacy_state(json.loads(ls_raw), valid_nos)
        except (ValueError, TypeError):
            return
        merged = migrate.merge_legacy(server, browser)
        if merged != migrate.merge_legacy(server, {}):
            st.info(f"이 브라우저에 이전 버전 진도가 남아 있습니다: 암기 {len(browser['memorized'])}, "
                    f"오답 {len(browser['wrong'])}, 정답 {len(browser['correct'])}, 시험 {len(browser['sessions'])}회. "
                    f"병합하면 계정 진도는 암기 {len(merged['memorized'])} · 오답 {len(merged['wrong'])} · "
                    f"정답 {len(merged['correct'])} · 시험 {len(merged['sessions'])}회가 됩니다.")
            c1, c2 = st.columns(2)
            if c1.button("병합하기", key="wl_ls_merge", width="stretch"):
                try:
                    store.save_legacy_state(merged)
                    st.session_state.pop("initialized", None)
                    st.session_state.wl_ls_dismissed = True
                    st.rerun()
                except StoreError:
                    st.error("병합하지 못했습니다(동기화 실패). 다시 시도하세요.")
            if c2.button("이번엔 무시", key="wl_ls_dismiss", width="stretch"):
                st.session_state.wl_ls_dismissed = True
                st.rerun()


def backup_panel(store, words, make_excel_bytes):
    st.markdown("#### 💾 백업 · 복원")
    stamp = utcnow().strftime("%Y%m%d")
    st.download_button(f"📥 전체 단어장 Excel 백업 ({len(words)}개)", data=make_excel_bytes(words),
                       file_name=f"wordloop_words_{stamp}.xlsx", width="stretch",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    if st.button("학습 기록 JSON 만들기", key="wl_make_json", width="stretch"):
        since = utcnow().replace(year=2000)
        try:
            payload = {
                "exported_at": utcnow().isoformat(),
                "word_progress": list(store.get_progress().values()),
                "review_events": store.list_events(since),
                "writing_attempts": store.list_writing_attempts(since),
                "test_sessions": store.list_test_sessions(since),
            }
            st.session_state.wl_backup_json = json.dumps(payload, ensure_ascii=False, default=str, indent=1)
        except StoreError:
            st.error("기록을 불러오지 못했습니다.")
    if st.session_state.get("wl_backup_json"):
        st.download_button("📥 학습 기록 JSON 다운로드", data=st.session_state.wl_backup_json,
                           file_name=f"wordloop_records_{stamp}.json", mime="application/json", width="stretch")
    if store.kind == "supabase":
        up = st.file_uploader("단어장 Excel로 복원(없는 단어만 추가, 기존 단어는 덮어쓰지 않음)", type=["xlsx"],
                              key="wl_restore_upload")
        if up and st.button("복원 실행", key="wl_restore_btn"):
            _restore_from_upload(store, up)
