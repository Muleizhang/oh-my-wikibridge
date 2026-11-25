import { drawSpace } from './spatial-graph.js';

// Fixed cases with shared hubs and a repeatable mix of many-to-one relations.
export function trialGraph(size) {
  const nodes=[], edges=[];
  function series(kind,count,names) {
    const values=Array.from({length:count},(_,i)=>({
      id:kind+'-'+i,kind,label:names[i] ?? names[0]+' '+String(i+1).padStart(2,'0')
    }));
    nodes.push(...values);
    return values;
  }
  const motifs=series('motif',size/8,['花卉纹','旋纹','弦纹','菱格纹','水波纹','回纹','云纹','网格纹']);
  const materials=series('material',Math.min(4,size/8),['陶','青铜','玉','丝绸']);
  const periods=series('period',Math.min(4,size/8),['新石器时代','商代','西周','春秋']);
  const objects=series('artifact',size-nodes.length,['模拟器物']);
  objects.forEach((o,i)=>{
    function link(to,label) { edges.push({id:o.id+'/'+to.id,from:o.id,to:to.id,label}); }
    link(motifs[i%motifs.length],'饰有纹样');
    link(materials[Math.floor(i/2)%materials.length],'材质');
    link(periods[Math.floor(i/3)%periods.length],'所属时代');
    if(i%4===0) link(motifs[(i+1)%motifs.length],'饰有纹样');
  });
  return {nodes,edges};
}

export function mountGraphTrial(root) {
  function add(tag,parent,txt='') {
    const node=document.createElement(tag); node.textContent=txt; parent.append(node); return node;
  }
  const controls=add('div',root); controls.className='trial-controls';
  function select(label) { const wrap=add('label',controls,label+' '); return add('select',wrap); }
  function option(menu,id,label) {const op=add('option',menu,label);op.value=id;}
  const scale=select('节点数');
  for(const size of [16,32,64]) option(scale,String(size),String(size));
  const target=select('查看节点');
  const layout=select('范围'); option(layout,'all','全图');option(layout,'near','一跳邻域');
  const run=add('button',controls,'测量旋转帧率');run.type='button';
  const counts=add('p',root);counts.className='trial-counts';
  const host=add('div',root);host.className='space-graph';
  const report=add('p',root);report.setAttribute('role','status');
  let data, picked='',dispose,frame=0;
  function cancel() {
    cancelAnimationFrame(frame);frame=0;run.textContent='测量旋转帧率';
  }
  function show() {
    const edges=layout.value==='near'?data.edges.filter(e=>e.from===target.value||e.to===target.value):data.edges;
    const visible=new Set([target.value,...edges.flatMap(e=>[e.from,e.to])]);
    const nodes=data.nodes.filter(n=>visible.has(n.id));
    counts.textContent=nodes.length+' / '+data.nodes.length+' 个节点　·　'+edges.length+' / '+data.edges.length+' 条关系';
    if(!edges.some(e=>e.id===picked)) picked='';
    dispose=drawSpace(host,nodes,edges,picked,id=>{picked=id;show();},id=>{
      cancel();report.textContent='';target.value=id;choose();
    });
  }
  function choose() {
    const edge=data.edges.find(e=>e.from===target.value||e.to===target.value);
    picked=edge?.id ?? '';show();
  }
  function load() {
    cancel();report.textContent='';data=trialGraph(Number(scale.value));target.replaceChildren();
    for(const n of data.nodes) option(target,n.id,n.label);
    target.value=data.nodes[0].id;choose();
  }
  scale.onchange=load;
  target.onchange=()=>{cancel();report.textContent='';choose();};
  layout.onchange=()=>{cancel();report.textContent='';choose();};
  run.onclick=()=>{
    if(frame){cancel();report.textContent='已停止测量。';return;}
    const svg=host.querySelector('svg.space-stage');
    if(svg.getAttribute('data-mode')!=='space'){report.textContent='切换到 3D 空间后可测量旋转帧率。';return;}
    const intervals=[],subject=counts.textContent;
    let previous;
    run.textContent='停止测量';report.textContent='正在测量 60 帧，请保持此页面可见。';
    function step(now) {
      if(!root.isConnected||document.hidden||svg.getAttribute('data-mode')!=='space'){cancel();report.textContent='测量已中断。';return;}
      if(previous!==undefined) intervals.push(now-previous);
      if(intervals.length===60){
        const fps=60000/intervals.reduce((a,b)=>a+b,0);
        const sorted=intervals.sort((a,b)=>a-b);
        report.textContent=subject+'　｜　本机平均 '+fps.toFixed(1)+' FPS，P95 帧间隔 '+sorted[56].toFixed(1)+' ms。';cancel();return;
      }
      previous=now;
      svg.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true,cancelable:true}));
      frame=requestAnimationFrame(step);
    }
    frame=requestAnimationFrame(step);
  };
  function visibilityChanged() {
    if(document.hidden && frame){cancel();report.textContent='页面进入后台，测量已中断。';}
  }
  document.addEventListener('visibilitychange',visibilityChanged);
  scale.value='16';layout.value='all';load();
  return ()=>{document.removeEventListener('visibilitychange',visibilityChanged);cancel();dispose?.();root.replaceChildren();};
}
