// 필기 컴포넌트 순수 로직 테스트 — 실행: node --test tests/js/
// DOM 연결부(포인터 이벤트 → 캔버스)는 브라우저에서 합성 PointerEvent로 따로 검증한다(docs/TABLET_QA.md).
import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  InkModel, LOGICAL_W, acceptsPointer, cropBox, toLogical, widthFor,
} from '../../components/handwriting/handwriting.js';

test('S펜 전용: pen만 획 허용, touch/mouse 거부 · 호환 모드는 모두 허용', () => {
  assert.equal(acceptsPointer('pen', true), true);
  assert.equal(acceptsPointer('touch', true), false);
  assert.equal(acceptsPointer('mouse', true), false);
  for (const t of ['pen', 'touch', 'mouse']) assert.equal(acceptsPointer(t, false), true);
  assert.equal(acceptsPointer('', false), false); // 알 수 없는 포인터는 무시
});

test('좌표 변환: 리사이즈·회전·확대 후에도 같은 논리 좌표', () => {
  const H = 450;
  const a = toLogical(110, 70, { left: 10, top: 20, width: 500, height: 225 }, H);
  // 가로→세로 회전으로 캔버스가 2배 커지고 위치도 바뀐 경우
  const b = toLogical(1210, 120, { left: 1010, top: 20, width: 1000, height: 450 }, H);
  assert.deepEqual(a.map(Math.round), [200, 100]);
  assert.deepEqual(b.map(Math.round), [200, 100]);
  assert.deepEqual(toLogical(10 + 500, 20 + 225, { left: 10, top: 20, width: 500, height: 225 }, H), [LOGICAL_W, H]);
});

test('필압: 펜에서만 제한된 범위로 반영, 미지원이면 고정 굵기', () => {
  assert.equal(widthFor(6, 0.5, 'mouse'), 6);
  assert.equal(widthFor(6, 1, 'touch'), 6);
  assert.equal(widthFor(6, 0, 'pen'), 6);
  assert.ok(widthFor(6, 0.05, 'pen') >= 6 * 0.55);
  assert.ok(widthFor(6, 1, 'pen') <= 6 * 1.45);
  assert.ok(widthFor(6, 0.9, 'pen') > widthFor(6, 0.2, 'pen'));
});

test('손바닥+펜 동시 접촉: 두 번째 포인터는 획을 만들거나 이어 그릴 수 없음', () => {
  const m = new InkModel();
  assert.equal(m.begin(1, [10, 10, 6]), true);
  assert.equal(m.begin(2, [500, 400, 6]), false); // 손바닥(touch 호환 모드라도) 무시
  assert.equal(m.extend(2, [[501, 401, 6]]), false);
  assert.equal(m.extend(1, [[12, 12, 6], [14, 15, 6]]), true); // coalesced 여러 점
  assert.equal(m.end(2), null);
  assert.ok(m.end(1));
  assert.equal(m.strokes.length, 1);
  assert.equal(m.strokes[0].pts.length, 3);
});

test('pointercancel: 진행 중 획은 버리고 이전 획은 유지', () => {
  const m = new InkModel();
  m.begin(1, [1, 1, 6]); m.end(1);
  m.begin(1, [5, 5, 6]); m.extend(1, [[6, 6, 6]]);
  assert.equal(m.cancel(1), true);
  assert.equal(m.active, null);
  assert.equal(m.strokes.length, 1);
  assert.equal(m.undoStack.length, 1);
});

test('Undo / Redo / 전체 지우기 / 획 지우개', () => {
  const m = new InkModel();
  for (const [i, x] of [[1, 100], [2, 300], [3, 500]].entries()) { m.begin(i, [x[1], 100, 6]); m.end(i); }
  assert.equal(m.strokes.length, 3);
  assert.ok(m.undo()); assert.equal(m.strokes.length, 2);
  assert.ok(m.redo()); assert.equal(m.strokes.length, 3);
  assert.ok(m.eraseAt(300, 102, 5)); assert.deepEqual(m.strokes.map((s) => s.pts[0][0]), [100, 500]);
  assert.equal(m.eraseAt(900, 400, 5), false);
  assert.ok(m.undo()); assert.deepEqual(m.strokes.map((s) => s.pts[0][0]), [100, 300, 500]); // 원래 순서로 복원
  assert.ok(m.clear()); assert.equal(m.isEmpty(), true);
  assert.ok(m.undo()); assert.equal(m.strokes.length, 3); // 전체 지우기도 되돌리기 가능
  m.begin(9, [1, 1, 6]); m.end(9);
  assert.equal(m.redo(), false); // 새 획을 그리면 redo 기록은 사라짐
  assert.equal(new InkModel().undo(), false);
});

test('재렌더/새로고침 복원: JSON 왕복 + 손상된 초안 방어', () => {
  const m = new InkModel();
  m.begin(1, [10.123, 20.456, 6.04]); m.extend(1, [[30, 40, 7]]); m.end(1);
  const restored = InkModel.fromJSON(JSON.parse(JSON.stringify(m.toJSON())));
  assert.deepEqual(restored.strokes, [{ pts: [[10.1, 20.5, 6], [30, 40, 7]] }]);
  assert.equal(InkModel.fromJSON({ v: 999, strokes: [] }).isEmpty(), true);
  assert.equal(InkModel.fromJSON(null).isEmpty(), true);
  const partial = InkModel.fromJSON({ v: 1, strokes: [{ pts: [[1, 2, 3]] }, { pts: [[1, 'x', 3]] }, { pts: [] }] });
  assert.equal(partial.strokes.length, 1);
});

test('제출 PNG 범위: 빈 캔버스는 null, 여백 포함·경계 안으로 제한', () => {
  assert.equal(cropBox([], 500), null);
  const box = cropBox([{ pts: [[100, 100, 6], [200, 150, 6]] }], 500, 24);
  assert.deepEqual(box, [70, 70, 230, 180]);
  assert.deepEqual(cropBox([{ pts: [[2, 2, 6]] }], 500, 24), [0, 0, 32, 32]);
});

test('긴 문장 고속 필기: 많은 점도 손실 없이 저장', () => {
  const m = new InkModel();
  m.begin(1, [0, 0, 6]);
  const pts = Array.from({ length: 5000 }, (_, i) => [i / 5, Math.sin(i / 10) * 50 + 200, 6]);
  m.extend(1, pts);
  m.end(1);
  assert.equal(m.pointCount(), 5001);
  assert.ok(JSON.stringify(m.toJSON()).length < 200_000); // 초안 크기 합리적
});
