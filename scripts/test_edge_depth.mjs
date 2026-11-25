import assert from 'node:assert/strict';
import { test } from 'node:test';
import { castToFloor, coneVertices, floorY, depthCuts, edgeDepthAt, splitByDepth } from '../src/edge-depth.js';

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


test('light rays have one world-space intersection with the floor at every height',()=>{
  const receiver={x:17,y:floorY,z:-28};
  for(const height of [0,35,180]) {
    const point={x:receiver.x-.21*height,y:floorY-height,z:receiver.z-.17*height};
    const hit=castToFloor(point);
    assert.equal(hit.y,floorY);
    assert.ok(Math.hypot(hit.x-receiver.x,hit.z-receiver.z)<1e-10);
  }
});

test('arrow silhouette and shadow share the same three-dimensional cone',()=>{
  const tip={x:30,y:5,z:10}, before={x:30,y:-2,z:10};
  const cone=coneVertices(before,tip);
  assert.equal(cone[0],tip);assert.equal(cone.length,9);
  for(const p of cone.slice(1)){
    assert.equal(p.y,tip.y-9);
    assert.ok(Math.abs(Math.hypot(p.x-tip.x,p.z-tip.z)-3.7)<1e-8);
    assert.equal(castToFloor(p).y,floorY);
  }
});

test('only potentially overlapping node bounds split a wire',()=>{
  const wire=[{x:0,y:0,z:-140},{x:100,y:0,z:100}];
  assert.deepEqual(depthCuts([wire],[],[
    {left:30,right:50,top:-5,bottom:8,z:0},
    {left:20,right:40,top:60,bottom:80,z:40}
  ]),[[0]]);
});
