import assert from 'node:assert/strict';
import { readFileSync, mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { runInNewContext } from 'node:vm';
import { defaultAtlasSite, resolveAtlasSite } from '../server/atlas-site.js';

const template = readFileSync(new URL('./atlas_viewer.html', import.meta.url), 'utf8');
const reasoner = readFileSync(new URL('../src/kg-reasoner.js', import.meta.url), 'utf8').replace(/^export\s+/gm, '');
const source = template.match(/<script>\s*([\s\S]*?)\s+boot\(\)\.catch/)[1];
function model(manifest) {
  return runInNewContext(`${reasoner}\n${source}\nreturn buildGraphModel(manifest, 'http://localhost:1423/kg/manifest.json'); })();`,
    { manifest, URL, window: {}, document: { documentElement: { getAttribute: () => 'dark' } } });
}

test('partial imports recover candidate crops by record ID and retain all dimension arrays', () => {
  const m = { items: [{ artifactId: 'a', sourceRecordId: 'v2:r1', artifact: '鸟纹壶',
    imageUrl: 'page.jpg', imageKind: 'page', periods: ['汉代'], motifs: ['鸟纹'],
    shapes: ['鸟形'], techniques: ['刻划'], decorationMaterials: ['金'], cultures: ['仰韶文化'] }],
    rows: [{ artifactId: 'a', sourceRecordId: 'v2:r1', predicate: 'has_composition', object: '对称',
      imageUrl: 'annotations-v2/vol2/p0001/crops/r01.jpg', detailUrl: 'thumb.jpg',
      imageKind: 'artifact_candidate', pageUrl: 'original.jpg' },
    { artifactId: 'a', predicate: 'uses_technique', object: '错配', reviewStatus: 'rejected' } ] };
  const g = model(m), item = g.items[0];
  assert.equal(item.plateUrl, 'http://localhost:1423/kg/annotations-v2/vol2/p0001/crops/r01.jpg');
  assert.equal(item.imageKind, 'artifact_candidate');
  for (const field of ['periods', 'motifs', 'shapes', 'techniques', 'decorationMaterials', 'cultures', 'compositions']) {
    assert.equal(item[field].length, 1, field);
  }
  assert.equal(item.techniques[0], '刻划');
  assert.equal(g.techniqueById.has('错配'), false);
});

test('same-name records never borrow a crop from another source record', () => {
  const g = model({ items: [{ artifactId: 'a', sourceRecordId: 'v1:r1', artifact: '鸟纹壶',
    imageUrl: 'page.jpg', imageKind: 'page' }], rows: [{ artifactId: 'a', sourceRecordId: 'v2:r1',
    imageKind: 'artifact_candidate', imageUrl: 'wrong.jpg', predicate: 'period', object: '汉代' }] });
  assert.equal(g.items[0].plateUrl, 'http://localhost:1423/kg/page.jpg');
});

test('document-only techniques and compositions are discoverable without inventing artifact edges', () => {
  const records = [
    { id: 'i1', kind: 'technique', subject: { label: '鸟纹' }, value: '浮雕' },
    { id: 'i2', kind: 'composition', subject: { label: '鸟纹' }, value: '两面对称' },
    { id: 'i3', kind: 'belief', subject: { label: '莲花' }, value: '佛教' },
    { id: 'i4', kind: 'symbolism', subject: { label: '莲花纹' }, value: '纯洁' },
  ];
  const manifest = { items: [{ artifactId: 'a' }], rows: [], interpretations: records };
  const g = model(manifest);
  assert.equal(g.techniqueById.get('浮雕').documentRecords[0].id, 'i1');
  assert.equal(g.compositionById.get('两面对称').count, 0);
  assert.equal(g.items[0].techniques.length, 0);
  assert.equal(g.items[0].compositions.length, 0);
  assert.equal(g.interpretationsBySubject.get('莲花').length, 2);
  assert.equal(g.patternAttributes.get('莲花').size, 2);
  assert.equal(manifest.rows.length, 0);
});

test('server accepts extracted package roots and defaults to the full merged atlas', () => {
  const root = mkdtempSync(join(tmpdir(), 'atlas-site-'));
  try {
    const put = dir => { mkdirSync(dir, { recursive: true }); writeFileSync(join(dir, 'manifest.json'), '{}'); return dir; };
    const sample = put(join(root, 'data/local-kg/atlas-100/site'));
    assert.equal(defaultAtlasSite(root), sample);
    const merged = put(join(root, 'data/local-kg/merged/site'));
    assert.equal(defaultAtlasSite(root), merged);
    const pkg = put(join(root, 'unzip/wikibridge-three-volumes/site'));
    assert.equal(resolveAtlasSite(join(root, 'unzip')), pkg);
    assert.equal(resolveAtlasSite(join(root, 'unzip/wikibridge-three-volumes')), pkg);
    assert.equal(resolveAtlasSite(pkg), pkg);
  } finally { rmSync(root, { recursive: true, force: true }); }
});
