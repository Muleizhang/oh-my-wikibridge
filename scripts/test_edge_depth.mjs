import assert from 'node:assert/strict';
import { test } from 'node:test';
import { depthCuts, edgeDepthAt, splitByDepth } from '../src/edge-depth.js';

test('a long wire can pass both behind and in front of a node plane',()=>{
  const wire=[{x:0,y:0,z:-160},{x:100,y:0,z:100}];
  for(const points of [wire,[...wire].reverse()]) {
    const pieces=splitByDepth(points,[0]);
    assert.equal(pieces.length,2);
    assert.equal(pieces[0].b.z,0);
    const t=(pieces[0].b.x-points[0].x)/(points[1].x-points[0].x);
    assert.ok(Math.abs(edgeDepthAt(points[0].z,points[1].z,t))<1e-8);
    assert.ok(pieces[0].z*pieces[1].z<0);
  }
});

test('crossing order uses depth at the intersection even when midpoint order disagrees',()=>{
  const across=[{x:0,y:0,z:-140},{x:100,y:0,z:80}];
  const vertical=[{x:90,y:-10,z:0},{x:90,y:10,z:0}];
  assert.ok((across[0].z+across[1].z)/2<0);
  const [cuts]=depthCuts([across,vertical],[]);
  const atCrossing=splitByDepth(across,cuts).find(p=>p.a.x<=90 && p.b.x>=90);
  assert.ok(atCrossing.z>0);
  assert.deepEqual(depthCuts([[],vertical],[]),[[],[]]);
});
