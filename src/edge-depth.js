// Split projected curves into depth intervals. A node defines one boundary;
// a crossing defines another between the two wires at their point of overlap.
export function depthCuts(curves, nodeDepths) {
  const cuts=curves.map(()=>new Set(nodeDepths));
  const segments=[];
  for(const [wire,points] of curves.entries()) {
    for(let i=1;i<points.length;i++) {
      const a=points[i-1], b=points[i];
      segments.push({wire,a,b,left:Math.min(a.x,b.x),right:Math.max(a.x,b.x),
        top:Math.min(a.y,b.y),bottom:Math.max(a.y,b.y)});
    }
  }
  segments.sort((a,b)=>a.left-b.left);
  for(let i=0;i<segments.length;i++) {
    const p=segments[i], dx=p.b.x-p.a.x, dy=p.b.y-p.a.y;
    for(let j=i+1;j<segments.length && segments[j].left<=p.right;j++) {
      const q=segments[j];
      if(p.wire===q.wire || p.bottom<q.top || q.bottom<p.top) continue;
      const ex=q.b.x-q.a.x, ey=q.b.y-q.a.y, det=dx*ey-dy*ex;
      if(Math.abs(det)<1e-8) continue;
      const rx=q.a.x-p.a.x, ry=q.a.y-p.a.y;
      const t=(rx*ey-ry*ex)/det, u=(rx*dy-ry*dx)/det;
      if(t<0||t>1||u<0||u>1) continue;
      const z1=edgeDepthAt(p.a.z,p.b.z,t), z2=edgeDepthAt(q.a.z,q.b.z,u);
      if(Math.abs(z1-z2)>1e-6) {
        const boundary=(z1+z2)/2;
        cuts[p.wire].add(boundary);cuts[q.wire].add(boundary);
      }
    }
  }
  return cuts.map(set=>[...set].sort((a,b)=>a-b));
}

// Screen-space interpolation is linear in reciprocal camera distance.
export const cameraDistance=780;
export function edgeDepthAt(a,b,t) {
  return cameraDistance-1/((1-t)/(cameraDistance-a)+t/(cameraDistance-b));
}

export function splitByDepth(points,cuts) {
  const pieces=[];
  for(let i=1;i<points.length;i++) {
    const a=points[i-1], b=points[i];
    let start=a;
    const lo=Math.min(a.z,b.z), hi=Math.max(a.z,b.z);
    const inside=cuts.filter(z=>z>lo+1e-7 && z<hi-1e-7);
    if(a.z>b.z) inside.reverse();
    for(const z of inside) {
      const t=(z-a.z)*(cameraDistance-b.z)/((b.z-a.z)*(cameraDistance-z));
      const end={x:a.x+(b.x-a.x)*t,y:a.y+(b.y-a.y)*t,z};
      pieces.push({a:start,b:end,z:(start.z+z)/2}); start=end;
    }
    pieces.push({a:start,b,z:(start.z+b.z)/2});
  }
  return pieces;
}

// Positive y points down. The receiver and directional light are in world units.
export const floorY=122;
export function castToFloor(p) {
  const height=floorY-p.y;
  return {x:p.x+.21*height,y:floorY,z:p.z+.17*height};
}

// Arrowheads are small cones. Their silhouette and its cast shadow use the same vertices.
export function coneVertices(before,tip) {
  const length=Math.hypot(tip.x-before.x,tip.y-before.y,tip.z-before.z);
  if(length<1e-7) return [tip];
  const dx=(tip.x-before.x)/length,dy=(tip.y-before.y)/length,dz=(tip.z-before.z)/length;
  const horizontal=Math.hypot(dx,dz);
  const ux=horizontal>1e-7?dz/horizontal:1, uz=horizontal>1e-7?-dx/horizontal:0;
  const vx=dy*uz,vy=dz*ux-dx*uz,vz=-dy*ux;
  return [tip,...Array.from({length:8},(_,i)=>{
    const a=i*Math.PI/4,c=3.7*Math.cos(a),s=3.7*Math.sin(a);
    return {x:tip.x-9*dx+c*ux+s*vx,y:tip.y-9*dy+s*vy,z:tip.z-9*dz+c*uz+s*vz};
  })];
}
