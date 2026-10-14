// WordLoop 필기 캔버스 — Streamlit Components v2 (양방향).
// 정본은 벡터 획(논리 좌표)이고, <canvas>는 렌더 결과일 뿐이다 → 회전·리사이즈·DPR 변경 후에도 획이 유지된다.
// 순수 로직(InkModel, acceptsPointer, toLogical, widthFor, cropBox)은 Node 테스트에서 그대로 import 한다.

export const LOGICAL_W = 1000;
export const DRAFT_VERSION = 1;
const DB_NAME = 'wordloop';
const DRAFT_TTL_MS = 14 * 24 * 3600 * 1000;

// ───────────────────────── 순수 로직 ─────────────────────────
/** S펜 전용이면 pen만, 아니면 pen/touch/mouse 모두 획으로 받는다. */
export function acceptsPointer(pointerType, penOnly) {
  if (pointerType === 'pen') return true;
  if (penOnly) return false;
  return pointerType === 'touch' || pointerType === 'mouse';
}

/** 화면 좌표 → 논리 좌표 (확대/축소·리사이즈와 무관하게 같은 위치). */
export function toLogical(clientX, clientY, rect, logicalH) {
  return [
    ((clientX - rect.left) * LOGICAL_W) / rect.width,
    ((clientY - rect.top) * logicalH) / rect.height,
  ];
}

/** 필압은 펜에서만, 제한된 범위(0.55~1.45배)로 반영. 미지원이면 고정 굵기. */
export function widthFor(base, pressure, pointerType) {
  if (pointerType !== 'pen' || !(pressure > 0)) return base;
  return base * Math.min(1.45, Math.max(0.55, 0.55 + 0.9 * pressure));
}

const r1 = (v) => Math.round(v * 10) / 10;

export class InkModel {
  constructor(strokes = []) {
    this.strokes = strokes; // [{pts: [[x, y, w], ...]}]
    this.undoStack = [];
    this.redoStack = [];
    this.active = null; // {id, pts}
  }

  isEmpty() {
    return this.strokes.length === 0;
  }

  /** 한 번에 한 포인터만 획을 그린다(손바닥+펜 동시 접촉 시 두 번째 포인터 무시). */
  begin(pointerId, pt) {
    if (this.active) return false;
    this.active = { id: pointerId, pts: [pt.map(r1)] };
    return true;
  }

  extend(pointerId, pts) {
    if (!this.active || this.active.id !== pointerId) return false;
    for (const p of pts) this.active.pts.push(p.map(r1));
    return true;
  }

  end(pointerId) {
    if (!this.active || this.active.id !== pointerId) return null;
    const stroke = { pts: this.active.pts };
    this.active = null;
    this.strokes.push(stroke);
    this._push({ type: 'add', stroke });
    return stroke;
  }

  /** pointercancel: 브라우저가 제스처/손바닥으로 판단해 취소한 획은 버린다. */
  cancel(pointerId) {
    if (!this.active || this.active.id !== pointerId) return false;
    this.active = null;
    return true;
  }

  eraseAt(x, y, radius) {
    for (let i = this.strokes.length - 1; i >= 0; i--) {
      if (this.strokes[i].pts.some(([px, py, w]) => Math.hypot(px - x, py - y) <= radius + w / 2)) {
        const [stroke] = this.strokes.splice(i, 1);
        this._push({ type: 'erase', stroke, index: i });
        return true;
      }
    }
    return false;
  }

  clear() {
    if (this.isEmpty()) return false;
    this._push({ type: 'clear', strokes: this.strokes });
    this.strokes = [];
    return true;
  }

  undo() {
    const op = this.undoStack.pop();
    if (!op) return false;
    if (op.type === 'add') this.strokes.pop();
    else if (op.type === 'erase') this.strokes.splice(op.index, 0, op.stroke);
    else this.strokes = op.strokes;
    this.redoStack.push(op);
    return true;
  }

  redo() {
    const op = this.redoStack.pop();
    if (!op) return false;
    if (op.type === 'add') this.strokes.push(op.stroke);
    else if (op.type === 'erase') this.strokes.splice(op.index, 1);
    else this.strokes = [];
    this.undoStack.push(op);
    return true;
  }

  _push(op) {
    this.undoStack.push(op);
    this.redoStack = [];
  }

  pointCount() {
    return this.strokes.reduce((n, s) => n + s.pts.length, 0);
  }

  toJSON() {
    return { v: DRAFT_VERSION, strokes: this.strokes };
  }

  static fromJSON(obj) {
    if (!obj || obj.v !== DRAFT_VERSION || !Array.isArray(obj.strokes)) return new InkModel();
    const ok = obj.strokes.filter(
      (s) => Array.isArray(s.pts) && s.pts.length && s.pts.every((p) => p.length === 3 && p.every(Number.isFinite)),
    );
    return new InkModel(ok);
  }
}

/** 제출용 PNG 범위: 획 영역 + 여백 (논리 좌표). 빈 캔버스면 null. */
export function cropBox(strokes, logicalH, pad = 24) {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const s of strokes) {
    for (const [x, y, w] of s.pts) {
      x0 = Math.min(x0, x - w); y0 = Math.min(y0, y - w);
      x1 = Math.max(x1, x + w); y1 = Math.max(y1, y + w);
    }
  }
  if (x0 === Infinity) return null;
  return [Math.max(0, x0 - pad), Math.max(0, y0 - pad), Math.min(LOGICAL_W, x1 + pad), Math.min(logicalH, y1 + pad)];
}

export function drawStrokes(ctx, strokes, scale, offsetX = 0, offsetY = 0, color = '#111') {
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  ctx.strokeStyle = color;
  ctx.fillStyle = color;
  for (const s of strokes) drawStroke(ctx, s.pts, scale, offsetX, offsetY);
}

function drawStroke(ctx, pts, scale, ox, oy) {
  const X = (p) => (p[0] - ox) * scale;
  const Y = (p) => (p[1] - oy) * scale;
  if (pts.length === 1) {
    ctx.beginPath();
    ctx.arc(X(pts[0]), Y(pts[0]), (pts[0][2] * scale) / 2, 0, Math.PI * 2);
    ctx.fill();
    return;
  }
  for (let i = 1; i < pts.length; i++) {
    ctx.beginPath();
    ctx.lineWidth = ((pts[i - 1][2] + pts[i][2]) / 2) * scale;
    ctx.moveTo(X(pts[i - 1]), Y(pts[i - 1]));
    ctx.lineTo(X(pts[i]), Y(pts[i]));
    ctx.stroke();
  }
}

// ───────────────────────── 초안 저장 (IndexedDB) ─────────────────────────
function openDB() {
  return new Promise((resolve, reject) => {
    if (!('indexedDB' in globalThis)) return reject(new Error('no indexedDB'));
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => req.result.createObjectStore('drafts');
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function idb(db, mode, fn) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction('drafts', mode);
    const out = fn(tx.objectStore('drafts'));
    tx.oncomplete = () => resolve(out && 'result' in out ? out.result : undefined);
    tx.onerror = () => reject(tx.error);
  });
}

// ───────────────────────── Streamlit 컴포넌트 ─────────────────────────
const INSTANCES = new WeakMap();

const TOOLBAR = `
  <div class="wl-toolbar" role="toolbar" aria-label="필기 도구">
    <button type="button" data-act="pen" class="wl-tool on" aria-pressed="true" title="펜">✏️<span>펜</span></button>
    <button type="button" data-act="eraser" class="wl-tool" aria-pressed="false" title="획 지우개">🧽<span>지우개</span></button>
    <button type="button" data-act="undo" title="되돌리기">↶<span>Undo</span></button>
    <button type="button" data-act="redo" title="다시 실행">↷<span>Redo</span></button>
    <button type="button" data-act="clear" title="전체 지우기">🗑<span>전체</span></button>
    <label class="wl-width" title="펜 굵기">굵기<input type="range" min="3" max="14" step="1" value="6" data-act="width"></label>
    <button type="button" data-act="guide" class="wl-toggle" aria-pressed="true">가이드</button>
    <button type="button" data-act="penonly" class="wl-toggle" aria-pressed="true" title="켜면 S펜 입력만 획으로 인식">S펜 전용</button>
  </div>
  <div class="wl-pad">
    <canvas class="wl-canvas" aria-label="필기 영역"></canvas>
    <div class="wl-guide" aria-hidden="true"></div>
    <div class="wl-hint" aria-live="polite"></div>
  </div>
  <div class="wl-footer">
    <span class="wl-status" aria-live="polite"></span>
    <button type="button" data-act="submit" class="wl-submit">제출</button>
  </div>`;

function createInstance(parentElement) {
  const root = document.createElement('div');
  root.className = 'wl-root';
  root.innerHTML = TOOLBAR;
  parentElement.appendChild(root);

  const $ = (sel) => root.querySelector(sel);
  const canvas = $('.wl-canvas');
  const ctx = canvas.getContext('2d');
  const inst = {
    root, model: new InkModel(), data: {}, setTriggerValue: () => {}, draftKey: null, resetToken: null,
    tool: 'pen', baseWidth: 6, penOnly: null, showGuide: true, logicalH: 500, scale: 1,
    seen: new Set(), ignoredTouch: 0, db: null, dbFailed: false, saveTimer: null, cooldownUntil: 0,
  };

  // 사용자 선호(S펜 전용/굵기)는 기기별 localStorage에 기억 — 학습 데이터 아님
  try {
    const pref = JSON.parse(localStorage.getItem('wl_hw_pref') || '{}');
    if (typeof pref.penOnly === 'boolean') inst.penOnly = pref.penOnly;
    if (pref.width >= 3 && pref.width <= 14) inst.baseWidth = pref.width;
  } catch (e) { /* 사용 불가 시 기본값 */ }
  const savePref = () => {
    try { localStorage.setItem('wl_hw_pref', JSON.stringify({ penOnly: inst.penOnly, width: inst.baseWidth })); } catch (e) {}
  };

  const setStatus = (t) => { $('.wl-status').textContent = t; };
  const hint = (t) => { $('.wl-hint').textContent = t; };

  function redraw() {
    refreshButtons(); // 탭이 숨겨져 있어도 버튼·상태는 최신으로
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    if (!rect.width) return; // 보이게 되면 ResizeObserver가 다시 그린다
    canvas.width = Math.round(rect.width * dpr);
    canvas.height = Math.round(rect.height * dpr);
    inst.scale = (rect.width * dpr) / LOGICAL_W;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    drawStrokes(ctx, inst.model.strokes, inst.scale);
    if (inst.model.active) drawStrokes(ctx, [inst.model.active], inst.scale);
  }

  function refreshButtons() {
    root.dataset.strokes = String(inst.model.strokes.length); // QA·자동화 점검용(내용 아님, 개수만)
    root.querySelector('[data-act=undo]').disabled = !inst.model.undoStack.length;
    root.querySelector('[data-act=redo]').disabled = !inst.model.redoStack.length;
    root.querySelector('[data-act=clear]').disabled = inst.model.isEmpty();
    const sub = root.querySelector('[data-act=submit]');
    sub.disabled = inst.model.isEmpty() || !!inst.data.busy || Date.now() < inst.cooldownUntil;
    sub.textContent = inst.data.busy ? '처리 중…' : (inst.data.submit_label || '제출');
    hint(inst.model.isEmpty() ? (inst.penOnly ? 'S펜으로 써 주세요 (손가락·손바닥 터치는 무시)' : '펜·손가락·마우스로 써 주세요') : '');
    root.querySelector('[data-act=guide]').setAttribute('aria-pressed', String(inst.showGuide));
    root.querySelector('[data-act=penonly]').setAttribute('aria-pressed', String(inst.penOnly));
    $('.wl-guide').style.display = inst.showGuide && inst.data.guide ? 'flex' : 'none';
  }

  // ── 초안 ──
  async function db() {
    if (inst.db || inst.dbFailed) return inst.db;
    try { inst.db = await openDB(); } catch (e) { inst.dbFailed = true; setStatus('이 브라우저에서는 초안이 저장되지 않습니다'); }
    return inst.db;
  }
  function scheduleSave() {
    clearTimeout(inst.saveTimer);
    const key = inst.draftKey;
    const payload = { ...inst.model.toJSON(), saved_at: Date.now() };
    inst.saveTimer = setTimeout(async () => {
      const d = await db();
      if (!d || !key) return;
      try {
        await idb(d, 'readwrite', (s) => (inst.model.isEmpty() ? s.delete(key) : s.put(payload, key)));
        if (key === inst.draftKey) setStatus(inst.model.isEmpty() ? '' : '초안 저장됨(이 기기)');
      } catch (e) { setStatus('초안 저장 실패'); }
    }, 250);
  }
  async function loadDraft(key) {
    const d = await db();
    if (!d || !key) return;
    try {
      const saved = await idb(d, 'readonly', (s) => s.get(key));
      if (key !== inst.draftKey || !saved || !inst.model.isEmpty()) return;
      inst.model = InkModel.fromJSON(saved);
      if (!inst.model.isEmpty()) setStatus('저장된 초안을 불러왔습니다');
      redraw();
    } catch (e) { /* 초안 없음 */ }
  }
  async function purge(scope, clearKeys) {
    const d = await db();
    if (!d) return;
    try {
      const keys = await idb(d, 'readonly', (s) => s.getAllKeys());
      const now = Date.now();
      await idb(d, 'readwrite', (s) => {
        for (const k of keys || []) {
          // 다른 계정의 초안 / 완료된 문제 초안은 이 기기에서 삭제
          if ((scope && !String(k).startsWith(scope)) || (clearKeys || []).includes(k)) s.delete(k);
        }
      });
      for (const k of keys || []) {
        const v = await idb(d, 'readonly', (s) => s.get(k));
        if (v && now - (v.saved_at || 0) > DRAFT_TTL_MS) await idb(d, 'readwrite', (s) => s.delete(k));
      }
    } catch (e) { /* 정리 실패는 무시 */ }
  }

  // ── 포인터 처리 ──
  const capture = (id) => { try { canvas.setPointerCapture(id); } catch (err) { /* 합성 이벤트 등 */ } };
  const isEraser = (e) => inst.tool === 'eraser' || e.button === 5 || (e.buttons & 32) === 32;
  function onDown(e) {
    inst.seen.add(e.pointerType);
    if (!acceptsPointer(e.pointerType, inst.penOnly)) {
      if (e.pointerType === 'touch') {
        inst.ignoredTouch++;
        hint("손가락·손바닥 터치는 무시했어요. S펜이 인식되지 않으면 'S펜 전용'을 꺼 주세요.");
      }
      return; // S펜 전용: 터치는 획을 만들지 않음
    }
    e.preventDefault();
    const rect = canvas.getBoundingClientRect();
    const [x, y] = toLogical(e.clientX, e.clientY, rect, inst.logicalH);
    if (isEraser(e)) {
      inst.erasing = e.pointerId;
      if (inst.model.eraseAt(x, y, 12)) { redraw(); scheduleSave(); }
      capture(e.pointerId);
      return;
    }
    if (inst.model.begin(e.pointerId, [x, y, widthFor(inst.baseWidth, e.pressure, e.pointerType)])) {
      capture(e.pointerId);
      drawStrokes(ctx, [inst.model.active], inst.scale);
    }
  }
  function onMove(e) {
    const rect = canvas.getBoundingClientRect();
    if (inst.erasing === e.pointerId) {
      const [x, y] = toLogical(e.clientX, e.clientY, rect, inst.logicalH);
      if (inst.model.eraseAt(x, y, 12)) { redraw(); scheduleSave(); }
      return;
    }
    if (!inst.model.active || inst.model.active.id !== e.pointerId) return;
    e.preventDefault();
    const events = typeof e.getCoalescedEvents === 'function' ? e.getCoalescedEvents() : [];
    const pts = (events.length ? events : [e]).map((ev) => [
      ...toLogical(ev.clientX, ev.clientY, rect, inst.logicalH),
      widthFor(inst.baseWidth, ev.pressure, e.pointerType),
    ]);
    const before = inst.model.active.pts.length;
    inst.model.extend(e.pointerId, pts);
    // 새 구간만 그려 지연을 줄인다
    drawStrokes(ctx, [{ pts: inst.model.active.pts.slice(Math.max(0, before - 1)) }], inst.scale);
  }
  function onUp(e) {
    if (inst.erasing === e.pointerId) { inst.erasing = null; return; }
    if (inst.model.end(e.pointerId)) { refreshButtons(); scheduleSave(); }
  }
  function onCancel(e) {
    if (inst.erasing === e.pointerId) { inst.erasing = null; return; }
    if (inst.model.cancel(e.pointerId)) redraw();
  }
  canvas.addEventListener('pointerdown', onDown);
  canvas.addEventListener('pointermove', onMove);
  canvas.addEventListener('pointerup', onUp);
  canvas.addEventListener('pointercancel', onCancel);
  canvas.addEventListener('lostpointercapture', onUp);
  canvas.addEventListener('contextmenu', (e) => e.preventDefault()); // S펜 버튼 길게 누름 메뉴 방지

  // ── 도구 ──
  root.querySelector('.wl-toolbar').addEventListener('click', (e) => {
    const btn = e.target.closest('button');
    if (!btn) return;
    const act = btn.dataset.act;
    if (act === 'pen' || act === 'eraser') {
      inst.tool = act;
      root.querySelectorAll('.wl-tool').forEach((b) => {
        b.classList.toggle('on', b.dataset.act === act);
        b.setAttribute('aria-pressed', String(b.dataset.act === act));
      });
    } else if (act === 'undo' || act === 'redo' || act === 'clear') {
      if (inst.model[act]()) { redraw(); scheduleSave(); }
    } else if (act === 'guide') {
      inst.showGuide = !inst.showGuide; refreshButtons();
    } else if (act === 'penonly') {
      inst.penOnly = !inst.penOnly; savePref(); refreshButtons();
    }
  });
  root.querySelector('[data-act=width]').value = String(inst.baseWidth);
  root.querySelector('[data-act=width]').addEventListener('input', (e) => {
    inst.baseWidth = Number(e.target.value); savePref();
  });
  root.querySelector('[data-act=submit]').addEventListener('click', () => {
    if (inst.model.isEmpty() || inst.data.busy || Date.now() < inst.cooldownUntil) return;
    inst.cooldownUntil = Date.now() + 2500; // 연속 클릭 방지
    const png = exportPNG(inst.model.strokes, inst.logicalH);
    inst.setTriggerValue('submit', {
      png,
      submit_id: (crypto.randomUUID && crypto.randomUUID()) || String(Date.now()) + Math.random(),
      draft_key: inst.draftKey,
      strokes: inst.model.strokes.length,
      points: inst.model.pointCount(),
      pointer_types: [...inst.seen],
      ignored_touch: inst.ignoredTouch,
    });
    refreshButtons();
    setTimeout(refreshButtons, 2600);
  });

  const ro = new ResizeObserver(() => redraw());
  ro.observe(canvas);
  inst.destroy = () => ro.disconnect();
  inst.redraw = redraw;
  inst.refreshButtons = refreshButtons;
  inst.loadDraft = loadDraft;
  inst.purge = purge;
  inst.setStatus = setStatus;
  return inst;
}

/** 제출 시에만 PNG 생성: 흰 배경 + 획, 여백 크롭, 긴 변 최대 1024px. */
export function exportPNG(strokes, logicalH, maxSide = 1024) {
  const box = cropBox(strokes, logicalH);
  if (!box) return '';
  const [x0, y0, x1, y1] = box;
  const scale = Math.min(1.2, maxSide / Math.max(x1 - x0, y1 - y0));
  const out = document.createElement('canvas');
  out.width = Math.max(16, Math.round((x1 - x0) * scale));
  out.height = Math.max(16, Math.round((y1 - y0) * scale));
  const c = out.getContext('2d');
  c.fillStyle = '#fff';
  c.fillRect(0, 0, out.width, out.height);
  drawStrokes(c, strokes, scale, x0, y0, '#000');
  return out.toDataURL('image/png');
}

export default function mount(component) {
  const { data = {}, parentElement, setTriggerValue } = component;
  let inst = INSTANCES.get(parentElement);
  if (!inst) {
    inst = createInstance(parentElement);
    INSTANCES.set(parentElement, inst);
    inst.purge(data.user_scope, data.clear_keys);
  } else if (!parentElement.contains(inst.root)) {
    parentElement.appendChild(inst.root); // 런타임이 내용을 비웠다면 기존 획을 유지한 채 다시 붙인다
  }
  const prev = inst.data;
  inst.data = data;
  if (inst.penOnly === null) inst.penOnly = data.pen_only_default !== false; // 저장된 선호가 없을 때만
  inst.setTriggerValue = setTriggerValue;
  inst.logicalH = Math.round(LOGICAL_W * (data.aspect || 0.5));
  inst.root.style.setProperty('--wl-aspect', String(1 / (data.aspect || 0.5)));
  const guide = inst.root.querySelector('.wl-guide');
  guide.textContent = data.guide || '';
  if (prev.show_guide !== data.show_guide && typeof data.show_guide === 'boolean') inst.showGuide = data.show_guide;
  if ((data.clear_keys || []).length && JSON.stringify(prev.clear_keys) !== JSON.stringify(data.clear_keys)) {
    inst.purge(data.user_scope, data.clear_keys);
  }

  const keyChanged = inst.draftKey !== data.draft_key;
  const reset = inst.resetToken !== null && inst.resetToken !== data.reset_token;
  inst.resetToken = data.reset_token ?? 0;
  if (keyChanged || reset) {
    inst.draftKey = data.draft_key;
    inst.model = new InkModel();
    inst.cooldownUntil = 0;
    inst.setStatus('');
    if (!reset) inst.loadDraft(data.draft_key);
  }
  inst.redraw();
  return () => {
    // 데이터 갱신 때도 호출되므로 인스턴스는 유지하고, 실제로 DOM에서 빠졌을 때만 정리
    setTimeout(() => {
      if (!inst.root.isConnected) { inst.destroy(); INSTANCES.delete(parentElement); }
    }, 0);
  };
}
