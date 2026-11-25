import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { runInNewContext } from 'node:vm';

const template = readFileSync(new URL('./atlas_viewer.html', import.meta.url), 'utf8');
const reasonerSource = readFileSync(new URL('../src/kg-reasoner.js', import.meta.url), 'utf8').replace(/^export\s+/gm, '');
const source = template.match(/<script>\s*([\s\S]*?)\s+boot\(\)\.catch/)[1];

function loadViewer() {
  const elements = new Map();
  const canvas = new Proxy({
    createRadialGradient: () => ({ addColorStop() {} }),
    measureText: text => ({ width: text.length * 12 }),
    arc(x, y, r) { assert.ok(Number.isFinite(x) && Number.isFinite(y) && r >= 0); },
  }, { get: (target, key) => target[key] ?? (() => {}) });
  const document = {
    documentElement: { getAttribute: () => 'dark' },
    createElement: () => ({ getContext: () => canvas }),
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, { style: {} });
      return elements.get(id);
    },
  };
  const viewer = runInNewContext(`${reasonerSource}\n${source}
    return { graph, state, rebuildGraphScene, resetGraphView, zoomGraph, projectPoint, graphViewport, hitTestGraph, drawGraph, shouldPaintView,
      graphFilterCategories, toggleGraphFilter, clearGraphFilters, getFilteredFocalItems,
      load: manifest => G = buildGraphModel(manifest) };
  })();`, { document, window: { innerWidth: 1600, innerHeight: 900 },
    Path2D: class { moveTo() {} lineTo() {} quadraticCurveTo() {} },
    getComputedStyle: () => ({ fontFamily: 'serif' }),
  });
  viewer.graph.ctx = canvas;
  viewer.graph.canvas = { classList: { toggle() {} } };
  return viewer;
}

function fixture(clusterCount) {
  const items = [], rows = [];
  for (let cluster = 0; cluster < clusterCount; cluster++) {
    const count = [43, 26, 25, 8, 3][cluster] ?? 1;
    for (let i = 0; i < count; i++) {
      const artifactId = `${cluster}/${i}`;
      items.push({ artifactId, artifact: artifactId, page: 1 });
      rows.push({ artifactId, predicate: 'period', object: '战国' },
        { artifactId, predicate: 'made_of', object: '陶' },
        { artifactId, predicate: 'decorated_with', object: `纹样 ${cluster}` });
    }
  }
  return { items, rows };
}

function settleCamera(graph) {
  Object.assign(graph, { zoom: graph.targetZoom, panX: graph.targetPanX, panY: graph.targetPanY,
    yaw: graph.targetYaw, pitch: graph.targetPitch });
}

for (const [focusKind, focusId, count, dim, w, h] of [
  ['era', '战国', 200, '2d', 1600, 900],
  ['material', '陶', 529, '3d', 1600, 900],
  ['material', '陶', 529, '2d', 390, 844],
]) {
  test(`${focusId}: ${count} motifs fit in ${dim} at ${w}x${h}`, () => {
    const viewer = loadViewer();
    const manifest = fixture(count);
    viewer.load(manifest);
    const { graph, state } = viewer;
    Object.assign(state, { focusKind, focusId, clusterBy: 'motif', dim });
    Object.assign(graph, { w, h });
    viewer.rebuildGraphScene();
    settleCamera(graph);
    assert.equal(graph.clusters.length, count);
    assert.equal(graph.nodes.length + graph.clusters.filter(c => c.singleton).length, manifest.items.length);
    assert.equal(graph.orbitRadius, 0);

    const { width, height, centerY } = viewer.graphViewport();
    const singletonDistances = [];
    for (const [i, cluster] of graph.clusters.entries()) {
      const { tx, ty, tz, haloR } = cluster;
      const p = viewer.projectPoint(tx, ty, tz);
      const radius = dim === '3d' ? cluster.collapsedR : haloR;
      assert.ok(Math.abs(p.x - w / 2) + radius * p.k <= width / 2 + 1e-6);
      assert.ok(Math.abs(p.y - centerY) + radius * p.k <= height / 2 + 1e-6);
      if (cluster.singleton) singletonDistances.push(Math.hypot(tx, ty, tz));
      for (let j = 0; j < i; j++) {
        const other = graph.clusters[j];
        assert.ok(Math.hypot(tx - other.tx, ty - other.ty, tz - other.tz) >= haloR + other.haloR);
      }
    }
    if (dim === '3d') {
      for (const { x, y, z, tx, ty, tz } of [...graph.clusters, ...graph.nodes]) {
        assert.ok(Math.abs(Math.hypot(tx, ty, tz) - graph.shellRadius) < 1e-6);
        assert.ok(Math.abs(Math.hypot(x, y, z) - graph.shellRadius) < 1e-6);
      }
      const spans = ['tx', 'ty', 'tz'].map(axis => {
        const coords = graph.clusters.map(c => c[axis]);
        return Math.max(...coords) - Math.min(...coords);
      });
      assert.ok(Math.min(...spans) > 0.6 * Math.max(...spans), `world spans: ${spans}`);
      graph.yaw = Math.PI / 2;
      const across = graph.clusters.map(c => viewer.projectPoint(c.tx, c.ty, c.tz).x);
      assert.ok(Math.max(...across) - Math.min(...across) > 0.6 * Math.min(width, height));
    } else {
      assert.ok(Math.max(...singletonDistances) > 1.5 * Math.min(...singletonDistances));
    }

    const initialZoom = graph.targetZoom;
    viewer.zoomGraph(0.82);
    assert.ok(graph.targetZoom <= initialZoom);
    viewer.zoomGraph(1.2);
    viewer.resetGraphView();
    assert.equal(graph.targetZoom, initialZoom);
  });
}

test('at compact overview scale the nearest specimen or hub receives the click', () => {
  const viewer = loadViewer();
  viewer.load({ items: [], rows: [] });
  const { graph } = viewer;
  const cluster = { sx: 4, sy: 0, sr: 3, sz: 0, visible: true, kind: 'motif', name: '纹样', items: [1] };
  const node = { sx: 0, sy: 0, sr: 3, sz: 0, visible: true, cluster,
    item: { title: '器物', periods: [], materials: [], motifs: [] } };
  Object.assign(graph, { compact: true, clusters: [cluster], nodes: [node] });
  viewer.hitTestGraph(4, 0);
  assert.equal(graph.hoveredCluster, cluster);
  assert.equal(graph.hoveredNode, null);
  viewer.hitTestGraph(0, 0);
  assert.equal(graph.hoveredNode, node);
});

test('overview draws only category spheres and expands specimens on hover or zoom', () => {
  const viewer = loadViewer();
  const { graph, state } = viewer;
  viewer.load(fixture(200));
  Object.assign(state, { focusKind: 'era', focusId: '战国', clusterBy: 'motif' });
  Object.assign(graph, { w: 1600, h: 900 });
  viewer.rebuildGraphScene();
  settleCamera(graph);
  for (const obj of [...graph.clusters, ...graph.nodes]) Object.assign(obj, { x: obj.tx, y: obj.ty, z: obj.tz });
  const category = graph.clusters[0];
  const singleton = graph.clusters.find(c => c.singleton);
  viewer.drawGraph(0);
  const overviewRadius = category.drawR;
  assert.ok(overviewRadius >= category.sr * 1.7);
  assert.ok(singleton.drawR >= singleton.sr * 1.4);
  assert.ok(graph.nodes.every(n => !n.visible));
  assert.ok(graph.clusters.every(c => c.visible && !c.expanded));
  assert.ok(graph.nodes.every(n => n.cluster !== singleton));
  viewer.hitTestGraph(singleton.sx, singleton.sy, true);
  assert.equal(graph.hoveredCluster, singleton);
  assert.equal(graph.hoveredNode, null);

  viewer.hitTestGraph(category.sx, category.sy);
  viewer.drawGraph(.04);
  assert.ok(category.surfaceR > overviewRadius);
  for (const frame of [.08, .12, .16]) viewer.drawGraph(frame);
  assert.equal(graph.hoveredCluster, category);
  assert.ok(Math.abs(category.surfaceR - category.haloSr) < 1e-6);
  assert.ok(category.drawR <= Math.min(8, overviewRadius / 2));
  assert.ok(graph.nodes.some(n => n.visible && n.cluster === category));
  assert.ok(graph.nodes.every(n => !n.visible || n.cluster === category));
  const specimen = graph.nodes.find(n => n.visible && n.cluster === category);
  viewer.hitTestGraph((category.sx + specimen.sx) / 2, (category.sy + specimen.sy) / 2);
  viewer.drawGraph(.20);
  viewer.hitTestGraph(specimen.sx, specimen.sy);
  assert.equal(graph.hoveredNode, specimen);

  graph.hoveredNode = graph.hoveredCluster = null;
  viewer.zoomGraph(2.6);
  settleCamera(graph);
  for (const frame of [.24, .28, .32, .36]) viewer.drawGraph(frame);
  assert.ok(graph.nodes.some(n => n.visible));
  assert.equal(singleton.expanded, false);
  viewer.resetGraphView();
  settleCamera(graph);
  for (const frame of [.40, .44, .48, .52]) viewer.drawGraph(frame);
  assert.ok(graph.nodes.every(n => !n.visible));
});

test('the 3D shell turns while idle and pauses during hover, dragging and reduced motion', () => {
  const viewer = loadViewer();
  const { graph, state } = viewer;
  viewer.load(fixture(28));
  Object.assign(state, { focusKind: 'era', focusId: '战国', clusterBy: 'motif', dim: '3d' });
  Object.assign(graph, { w: 1600, h: 900 });
  viewer.rebuildGraphScene();
  settleCamera(graph);
  const startingYaw = graph.yaw;
  for (let i = 0; i <= 60; i++) {
    const ms = i * 1000 / 60;
    if (viewer.shouldPaintView(graph, 'graph', ms)) viewer.drawGraph(ms / 1000);
  }
  assert.ok(graph.yaw - startingYaw > .1 && graph.yaw - startingYaw < .15);
  const horizon = graph.shellRadius ** 2 / graph.cameraDistance;
  assert.ok(graph.clusters.every(c => c.backFacing === (c.sz < horizon)));
  const category = graph.clusters.find(c => c.visible && !c.backFacing && !c.singleton);
  const backCategory = graph.clusters.find(c => c.visible && c.backFacing && !c.singleton);
  assert.ok(backCategory.drawR >= 8);

  const strokes = [], labels = [];
  let circle;
  graph.ctx.beginPath = () => { circle = null; };
  graph.ctx.arc = (x, y, radius) => { circle = { x, y, radius }; };
  graph.ctx.stroke = () => { if (circle) strokes.push({ ...circle, opacity: graph.ctx.globalAlpha }); };
  graph.ctx.fillText = (text, x, y) => labels.push({ text, x, y });
  viewer.drawGraph(1.01);
  const opacity = c => strokes.find(s => s.x === c.sx && s.y === c.sy && s.radius === c.drawR)?.opacity;
  assert.ok(opacity(backCategory) > 0 && opacity(backCategory) < opacity(category) / 2);
  assert.equal(backCategory._labelBox, null);
  assert.ok(labels.some(label => label.x === category.sx && label.y === category.sy + 0.5));
  assert.ok(labels.every(label => label.x !== backCategory.sx));
  const globeRadius = graph.zoom * graph.shellRadius / Math.sqrt(1 - (graph.shellRadius / graph.cameraDistance) ** 2);
  assert.ok(strokes.every(s => Math.abs(s.radius - globeRadius) > 1e-6));

  viewer.hitTestGraph(category.sx, category.sy);
  const rotationTarget = graph.targetYaw;
  for (const frame of [1.04, 1.08, 1.12, 1.16]) viewer.drawGraph(frame);
  assert.equal(graph.targetYaw, rotationTarget);
  assert.ok(graph.nodes.some(n => n.visible && n.cluster === category));
  assert.ok(graph.nodes.every(n => !n.visible || n.backFacing === (n.sz < horizon)));

  graph.hoveredCluster = null;
  graph.dragging = true;
  viewer.drawGraph(1.20);
  assert.equal(graph.targetYaw, rotationTarget);
  graph.dragging = false;
  graph.motionQuery = { matches: true };
  viewer.drawGraph(1.24);
  assert.equal(graph.targetYaw, rotationTarget);
  graph.motionQuery.matches = false;
  viewer.drawGraph(1.28);
  assert.ok(graph.targetYaw > rotationTarget);
});

test('cluster graph supports top-left tag category filtering in-place without history breadcrumb', () => {
  assert.equal(template.includes('id="graphTrail"'), false);
  assert.equal(template.includes('id="graphFilterTabs"'), true);
  assert.equal(template.includes('id="graphFilterSearch"'), true);

  const viewer = loadViewer();
  viewer.load({
    items: [
      { artifactId: 'a1', artifact: '汉铜镜', page: 1 },
      { artifactId: 'a2', artifact: '汉陶罐', page: 1 },
      { artifactId: 'a3', artifact: '汉漆盘', page: 2 },
      { artifactId: 'a4', artifact: '汉青铜壶', page: 2 },
    ],
    rows: [
      { artifactId: 'a1', predicate: 'period', object: '西汉' },
      { artifactId: 'a1', predicate: 'made_of', object: '青铜' },
      { artifactId: 'a1', predicate: 'decorated_with', object: '卷云纹' },
      { artifactId: 'a1', predicate: 'artifact_type', object: '镜' },
      { artifactId: 'a1', predicate: 'has_shape', object: '圆形' },
      { artifactId: 'a2', predicate: 'period', object: '东汉' },
      { artifactId: 'a2', predicate: 'made_of', object: '陶' },
      { artifactId: 'a2', predicate: 'decorated_with', object: '卷云纹' },
      { artifactId: 'a3', predicate: 'period', object: '西汉' },
      { artifactId: 'a3', predicate: 'made_of', object: '漆器' },
      { artifactId: 'a3', predicate: 'decorated_with', object: '龙纹' },
      { artifactId: 'a4', predicate: 'period', object: '东汉' },
      { artifactId: 'a4', predicate: 'made_of', object: '青铜' },
      { artifactId: 'a4', predicate: 'decorated_with', object: '龙纹' },
      { artifactId: 'a4', predicate: 'artifact_type', object: '壶' },
    ],
  });
  const { graph, state } = viewer;
  Object.assign(state, { focusKind: 'era', focusId: '汉代', clusterBy: 'material', dim: '2d' });
  Object.assign(graph, { w: 1600, h: 900 });
  viewer.rebuildGraphScene();
  assert.equal(viewer.getFilteredFocalItems('era', '汉代').length, 4);

  const cats = viewer.graphFilterCategories();
  assert.deepEqual(Array.from(cats, c => c.kind), ['material', 'motif', 'era', 'artifact_type', 'shape']);

  // Single tag filter: 青铜 → 2 items
  state.graphFilters.material = ['青铜'];
  viewer.rebuildGraphScene();
  assert.equal(viewer.getFilteredFocalItems('era', '汉代').length, 2);
  assert.equal(graph.clusters.length, 1);

  // Same-category multi-select (OR): 青铜 OR 陶 → 3 items
  state.graphFilters.material.push('陶');
  viewer.rebuildGraphScene();
  assert.equal(viewer.getFilteredFocalItems('era', '汉代').length, 3);

  // Cross-category filter (AND): (青铜 OR 陶) AND 卷云纹 → 2 items
  state.graphFilters.motif = ['卷云纹'];
  viewer.rebuildGraphScene();
  assert.equal(viewer.getFilteredFocalItems('era', '汉代').length, 2);

  // Sub-period filter (AND): 西汉 → 1 item (a1)
  state.graphFilters.era = ['西汉'];
  viewer.rebuildGraphScene();
  assert.equal(viewer.getFilteredFocalItems('era', '汉代').length, 1);
  assert.equal(viewer.getFilteredFocalItems('era', '汉代')[0].id, 'a1');

  // Clear restores all 4 items
  state.graphFilters = { era: [], material: [], motif: [], technique: [] };
  viewer.rebuildGraphScene();
  assert.equal(viewer.getFilteredFocalItems('era', '汉代').length, 4);
  state.graphFilters.artifact_type = ['镜', '壶'];
  state.graphFilters.shape = ['圆形'];
  assert.deepEqual(Array.from(viewer.getFilteredFocalItems('era', '汉代'), item => item.id), ['a1']);
});
