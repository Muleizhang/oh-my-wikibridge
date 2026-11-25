import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import test from 'node:test';
import { runInNewContext } from 'node:vm';

const template = readFileSync(new URL('./atlas_viewer.html', import.meta.url), 'utf8');
const reasonerSource = readFileSync(new URL('../src/kg-reasoner.js', import.meta.url), 'utf8').replace(/^export\s+/gm, '');
const source = template.match(/<script>\s*([\s\S]*?)\s+boot\(\)\.catch/)[1];

function loadViewer() {
  const elements = new Map();
  const element = tag => ({
    tag, attributes: {}, children: [], style: {}, hidden: false,
    classList: { toggle() {}, add() {}, remove() {} },
    setAttribute(name, value) { this.attributes[name] = String(value); },
    replaceChildren(...children) { this.children = children; },
    closest: () => ({ getBoundingClientRect: () => ({ height: 66 }) }),
    querySelectorAll: () => [],
  });
  const document = {
    documentElement: { getAttribute: () => 'dark' },
    createElementNS: (_ns, tag) => element(tag),
    createElement: tag => element(tag),
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, element(id));
      return elements.get(id);
    },
    querySelectorAll: () => [],
  };
  return runInNewContext(`${reasonerSource}\n${source}
    const graphCalls = [];
    const drawerCalls = [];
    const realOpenGraph = openGraph;
    openGraph = (kind, id, opts) => { graphCalls.push({ kind, id, opts }); };
    openDrawer = (itemId) => { drawerCalls.push(itemId); };
    return {
      river, state, graphCalls, drawerCalls,
      drawRiverWaterway, drawRiverMotifLinks, riverRelatedGroups, riverToScreen,
      riverEraColor, openRiverTarget, placeRiverLabels, $,
      getG: () => G,
      load(manifest, w = 1440, h = 900) {
        G = buildGraphModel(manifest);
        Object.assign(river, makeRiverGroups(G.eras), { w, h, zoom: 1, targetZoom: 1, panX: 0, panY: 0, targetPanX: 0, targetPanY: 0 });
        buildRiverCurve();
        layoutRiverGroups();
        placeRiverLabels();
      }
    };
  })();`, { document, window: { innerWidth: 1440, innerHeight: 900 } });
}

const records = [
  ['a', '西周', '云纹', '鸟纹'], ['b', '西周后期', '云纹'],
  ['c', '商代', '云纹'], ['d', '汉代', '鸟纹'], ['e', '汉代', '卷云纹'],
  ['f', '西周'], ['g', '西周'], ['h', null, '云纹'],
];
const fixture = {
  items: records.map(([artifactId]) => ({ artifactId, page: 1 })),
  rows: records.flatMap(([artifactId, period, ...motifs]) => [
    ...(period ? [{ artifactId, predicate: 'period', object: period }] : []),
    ...motifs.map(object => ({ artifactId, predicate: 'decorated_with', object })),
  ]),
};

test('the river groups by era and motif and links only the hovered motif across eras', () => {
  const viewer = loadViewer();
  viewer.load(fixture);
  const { river, riverRelatedGroups } = viewer;
  const find = (era, motif) => river.groups.find(group => group.era === era && group.motif === motif);
  const ids = group => Array.from(group.members, ({ item }) => item.id);
  assert.deepEqual(ids(find('西周', '云纹')), ['a', 'b']);
  assert.deepEqual(ids(find('西周', '鸟纹')), ['a']);
  const unknown = river.groups.filter(group => group.motif === null);
  assert.deepEqual(Array.from(unknown, ids), [['f'], ['g']]);
  assert.equal(riverRelatedGroups(unknown[0]).length, 0);
  assert.equal(riverRelatedGroups(find('汉代', '卷云纹')).length, 0);
  assert.deepEqual(Array.from(riverRelatedGroups(find('西周', '云纹')), group => group.era), ['商代']);
  assert.deepEqual(Array.from(riverRelatedGroups(find('西周', '鸟纹')), group => group.era), ['汉代']);
});

test('continuous waterway uses seamless era gradient, transforms on zoom, and clears motif links on leave', () => {
  const viewer = loadViewer();
  viewer.load(fixture);
  const { river, $, drawRiverWaterway, drawRiverMotifLinks, riverRelatedGroups, riverToScreen } = viewer;
  drawRiverWaterway('dark');
  const defs = $('riverDefs');
  const grad = defs.children.find(el => el.tag === 'linearGradient' && el.attributes.id === 'riverEraGrad');
  assert.ok(grad && grad.children.length >= 4);

  const current = $('riverCurrent');
  const paths = current.children;
  assert.ok(paths.length >= 7);
  assert.ok(paths.every(path => path.tag === 'path' && path.attributes['vector-effect'] === 'non-scaling-stroke'));

  Object.assign(river, { zoom: 4, panX: 45, panY: -18 });
  drawRiverWaterway('dark');
  assert.equal(current.attributes.transform, 'translate(-2115 -1368) scale(4)');
  assert.equal(current.children, paths);

  for (const group of river.groups) {
    const { x, y } = riverToScreen(group.wx, group.wy);
    Object.assign(group, { sx: x, sy: y });
  }
  const hovered = river.groups.find(group => group.count === 2);
  const related = riverRelatedGroups(hovered);
  const [target] = related;
  const links = $('riverMotifLinks');
  drawRiverMotifLinks(hovered, related, 'dark');
  assert.equal(links.children.length, 1);
  assert.ok(links.children[0].attributes.d.startsWith(`M ${hovered.sx} ${hovered.sy} Q `));
  assert.ok(links.children[0].attributes.d.endsWith(` ${target.sx} ${target.sy}`));
  drawRiverMotifLinks(null, [], 'dark');
  assert.equal(links.children.length, 0);
});

test('clicking dynasty, clustered motif, and individual specimen all enter 聚类图谱', () => {
  const viewer = loadViewer();
  viewer.load(fixture);
  const { river, openRiverTarget, graphCalls, drawerCalls } = viewer;

  // 1) Dynasty click → openGraph('era', ...)
  assert.equal(openRiverTarget(null, '西周'), true);
  assert.equal(graphCalls.at(-1).kind, 'era');
  assert.equal(graphCalls.at(-1).id, '西周');

  // 2) Clustered motif click (count > 1) → openGraph('motif', ...)
  const cluster = river.groups.find(g => g.era === '西周' && g.motif === '云纹');
  assert.ok(cluster && cluster.count === 2);
  assert.equal(openRiverTarget(cluster, null), true);
  assert.equal(graphCalls.at(-1).kind, 'motif');
  assert.equal(graphCalls.at(-1).id, '云纹');

  // 3) Individual specimen WITH motif click → openGraph('motif', ...) + openDrawer(item.id)
  const singleMotif = river.groups.find(g => g.era === '汉代' && g.motif === '卷云纹');
  assert.ok(singleMotif && singleMotif.count === 1);
  assert.equal(openRiverTarget(singleMotif, null), true);
  assert.equal(graphCalls.at(-1).kind, 'motif');
  assert.equal(graphCalls.at(-1).id, '卷云纹');
  assert.equal(drawerCalls.at(-1), 'e');

  // 4) Individual specimen WITHOUT motif click → openGraph('era', ...) + openDrawer(item.id)
  const singleUnlabeled = river.groups.find(g => g.era === '西周' && g.motif === null);
  assert.ok(singleUnlabeled && singleUnlabeled.count === 1);
  assert.equal(openRiverTarget(singleUnlabeled, null), true);
  assert.equal(graphCalls.at(-1).kind, 'era');
  assert.equal(graphCalls.at(-1).id, '西周');
  assert.equal(drawerCalls.at(-1), singleUnlabeled.item.id);
});

test('seamless dynasty continuity, embedded minor eras, large clusters, and anti-trypophobia spacing on three-volume corpus', () => {
  const manifestPath = new URL('../data/local-kg/share/wikibridge-three-volumes/site/manifest.json', import.meta.url);
  if (!existsSync(manifestPath)) return;
  const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'));
  const viewer = loadViewer();
  viewer.load(manifest, 1440, 900);
  const G = viewer.getG();
  const { river, riverEraColor } = viewer;

  // Spine eras must be strictly contiguous with ZERO gaps from 0 to 1
  const spine = G.eras.filter(e => !e.embedded);
  assert.equal(spine[0].t0, 0);
  assert.equal(spine.at(-1).t1, 1);
  for (let i = 1; i < spine.length; i++) {
    assert.equal(spine[i].t0, spine[i - 1].t1, `gap between ${spine[i - 1].id} and ${spine[i].id}`);
    // Adjacent spine dynasties must have distinct colors
    assert.notEqual(riverEraColor(spine[i].id, 'dark'), riverEraColor(spine[i - 1].id, 'dark'));
    assert.notEqual(riverEraColor(spine[i].id, 'light'), riverEraColor(spine[i - 1].id, 'light'));
  }

  // Embedded minor eras placed at the exact historical junctions
  const byId = G.eraById;
  const zhou = byId.get('周代'), westZhou = byId.get('西周'), spring = byId.get('春秋');
  const dongZhou = byId.get('东周'), warring = byId.get('战国');
  const han = byId.get('汉代'), sanguo = byId.get('三国');
  const sui = byId.get('隋代'), tang = byId.get('唐代'), wudai = byId.get('五代');

  assert.equal(zhou.embedded, true);
  assert.ok(zhou.t0 >= westZhou.t0 && zhou.t0 < westZhou.t1 && zhou.t1 > spring.t0 && zhou.t1 <= spring.t1);

  assert.equal(dongZhou.embedded, true);
  assert.ok(dongZhou.t0 >= spring.t0 && dongZhou.t0 < spring.t1 && dongZhou.t1 > warring.t0 && dongZhou.t1 <= warring.t1);

  assert.equal(sanguo.embedded, true);
  assert.ok(sanguo.t0 >= han.t0 && Math.abs(sanguo.t1 - han.t1) < 1e-9);

  // 隋代 directly precedes 唐代, 五代 directly follows 唐代 with zero gap
  assert.equal(sui.t1, tang.t0);
  assert.equal(tang.t1, wudai.t0);

  // Curated overview avoids trypophobia swarms (modest count, large clusters, non-overlapping)
  const overview = river.groups.filter(g => g.tier === 0);
  assert.ok(overview.length >= 60 && overview.length <= 140, `overview count=${overview.length}`);
  const largestCluster = Math.max(...overview.filter(g => g.count > 1).map(g => g.layoutR));
  const avgSingle = overview.filter(g => g.count === 1).reduce((s, g) => s + g.layoutR, 0)
    / overview.filter(g => g.count === 1).length;
  assert.ok(largestCluster >= 28, `largestCluster=${largestCluster}`);
  assert.ok(largestCluster > avgSingle * 2.2, `cluster=${largestCluster} vs single=${avgSingle}`);

  // No severe overlaps among overview medallions
  let overlapCount = 0;
  for (let i = 0; i < overview.length; i++) {
    for (let j = i + 1; j < overview.length; j++) {
      const a = overview[i], b = overview[j];
      if (Math.hypot(a.wx - b.wx, a.wy - b.wy) < a.layoutR + b.layoutR + 1) overlapCount++;
    }
  }
  assert.equal(overlapCount, 0, `found ${overlapCount} overlapping overview circles`);

  // No overlapping dynasty plaques
  for (let i = 0; i < G.eras.length; i++) {
    for (let j = i + 1; j < G.eras.length; j++) {
      const a = G.eras[i].riverLabel.box, b = G.eras[j].riverLabel.box;
      const ox = Math.max(0, Math.min(a[2], b[2]) - Math.max(a[0], b[0]));
      const oy = Math.max(0, Math.min(a[3], b[3]) - Math.max(a[1], b[1]));
      assert.equal(ox * oy, 0, `plaque overlap between ${G.eras[i].id} and ${G.eras[j].id}`);
    }
  }
});
