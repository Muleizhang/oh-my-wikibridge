import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { createKGReasoner } from '../src/kg-reasoner.js';

const manifest = JSON.parse(readFileSync('data/local-kg/atlas-100/site/manifest.json', 'utf8'));
const reasoner = createKGReasoner(manifest);

test('ontology closure materializes axioms and inferred triples dynamically', () => {
  const summary = reasoner.getCatalogSummary();
  assert.ok(summary.counts.artifacts > 200);
  assert.ok(summary.counts.axioms > 20);
  assert.ok(summary.counts.inferredTriples > 100);
  assert.ok(summary.suggestions.length >= 4);
});

test('multi-hop semantic path reasoning compares literal vs ontology closure', () => {
  const lit = reasoner.findPaths('新石器时代', '商代', { useOntology: false, maxHops: 6 });
  const ont = reasoner.findPaths('新石器时代', '商代', { useOntology: true, maxHops: 6 });
  assert.equal(lit.ok, true);
  assert.equal(ont.ok, true);
  assert.ok(ont.paths.length >= 1, 'should find paths between 新石器时代 and 商代');
  assert.ok(ont.evidence.length >= 2);
  console.log('  [Path literal count]:', lit.paths.length, '| [Path ontology count]:', ont.paths.length);
  console.log('  [Top ontology path]:', ont.paths[0].summary);

  const transfer = reasoner.findPaths('彩陶', '青铜', { useOntology: true, maxHops: 6 });
  assert.equal(transfer.ok, true);
  assert.ok(transfer.paths.length >= 1);
  console.log('  [彩陶 → 青铜]:', transfer.paths[0].summary, '| ontologyUnlocked:', transfer.ontologyUnlocked);
});

test('set comparison computes intersection, difference, Jaccard, and executable NOT EXISTS SPARQL', () => {
  const cmp = reasoner.compareEntities('era', '商代', '春秋', { useOntology: true });
  assert.equal(cmp.ok, true);
  assert.ok(cmp.countA > 0 && cmp.countB > 0);
  assert.ok(cmp.sparql.includes('FILTER NOT EXISTS'));

  const sp = reasoner.runSparql(cmp.sparql, { useOntology: true });
  assert.equal(sp.ok, true);
  assert.ok(sp.plan.length >= 3);
  console.log('  [Compare 商代 vs 春秋]: shared motifs =', cmp.primary.shared.map(x => x.label),
    '| onlyA =', cmp.primary.onlyA.map(x => x.label).slice(0, 5),
    '| onlyB =', cmp.primary.onlyB.map(x => x.label).slice(0, 5),
    '| SPARQL rows =', sp.rows.length);
});

test('zero-LLM link prediction infers missing periods with association rules & supporters', () => {
  const pred = reasoner.predictMissing({ targetPredicate: 'period', useOntology: true, limit: 8 });
  assert.equal(pred.ok, true);
  assert.ok(pred.predictions.length > 0);
  const first = pred.predictions[0];
  assert.ok(first.confidence > 0.4 && first.confidence <= 0.96);
  assert.ok(first.supporters.length >= 1);
  console.log('  [Top 3 period predictions]:');
  for (const p of pred.predictions.slice(0, 3)) {
    console.log(`   - ${p.artifactTitle} => ${p.predictedValue} (${Math.round(p.confidence * 100)}%, lift ${p.lift}x) | ${p.ruleFormula}`);
  }
});
