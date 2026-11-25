import { drawSpace } from './spatial-graph.js';

export function drawNetwork(host,groups,picked,onPick,resolveImage=url=>url) {
  const names={decorated_with:'饰有纹样',made_of:'材质',period:'所属时代',uses_technique:'工艺'};
  const current=groups.find(g=>g.some(r=>r.id===picked)) ?? groups[0];
  if (!current) return;
  // Keep a readable local view for large collections. The full relationship list remains available.
  const focusGroups=groups.length<=6?groups:[current];
  const nodes=new Map(), edges=[], original=new Map();
  const motif=current[0];
  function put(id,label,kind,sub,image) {
    if(!nodes.has(id)) nodes.set(id,{id,label,kind,sub,image:image?resolveImage(image):undefined});
  }
  put(motif.objectId,motif.object,'motif','纹样',motif.detailUrl);
  for(const group of focusGroups){
    const row=group[0];
    put(row.artifactId,row.artifact,'artifact',row.findspot ?? ('图 '+row.item),row.imageUrl);
    for (const r of group) {
      if(r.predicate!=='decorated_with') put(r.objectId,r.object,'concept',names[r.predicate]);
      edges.push({id:r.id,from:r.artifactId,to:r.objectId,label:names[r.predicate]});
      original.set(r.id,r);
    }
  }
  function pickNode(id) {
    const row=nodes.get(id).kind==='artifact' ? focusGroups.find(g=>g[0].artifactId===id)?.[0] :
      current.find(r=>r.objectId===id) ?? [...original.values()].find(r=>r.objectId===id);
    if(row) onPick(row.id);
  }
  return drawSpace(host,[...nodes.values()],edges,picked,onPick,pickNode);
}
