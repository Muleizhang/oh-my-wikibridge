import assert from 'node:assert/strict';
import { test } from 'node:test';
import { trialGraph } from '../src/graph-trial.js';

for (const [size,edgeCount] of [[16,33],[32,65],[64,156]]) {
  test(`the ${size}-node test case is reproducible and every entity participates`,()=>{
    const graph=trialGraph(size);
    assert.deepEqual(graph,trialGraph(size));
    assert.equal(graph.nodes.length,size);
    assert.equal(graph.edges.length,edgeCount);
    const ids=new Set(graph.nodes.map(n=>n.id));
    assert.equal(ids.size,size);
    assert.equal(new Set(graph.edges.map(e=>e.id)).size,edgeCount);
    assert.deepEqual(new Set(graph.edges.flatMap(e=>[e.from,e.to])),ids);
  });
}
