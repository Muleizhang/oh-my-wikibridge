// A compact perspective renderer shared by the application and the single-file atlas.
const spaceScenes = new WeakMap();
let spaceSerial = 0;
const spacePalette = {
  motif: ['#ffdaa2','#b87740','#704026'], artifact: ['#ffd0a6','#ad6141','#603b32'],
  concept: ['#cfebe2','#579d91','#25565c']
};

export function drawSpace(host, nodes, edges, picked, onEdge, onNode) {
  let scene = spaceScenes.get(host);
  const key = JSON.stringify([nodes.map(n=>[n.id,n.label,n.kind,n.sub]),edges.map(e=>[e.id,e.from,e.to,e.label])]);
  if (!scene || scene.key !== key) {
    scene?.dispose();
    scene = buildSpace(host,nodes,edges);
    scene.key = key;
    spaceScenes.set(host,scene);
  }
  scene.select(picked,onEdge,onNode);
  return () => { if (spaceScenes.get(host) === scene) { scene.dispose(); spaceScenes.delete(host); } };
}

function buildSpace(host,nodes,edges) {
  host.replaceChildren();
  const uid = 'space-'+(++spaceSerial)+'-';
  function html(tag,parent,cls,content) {
    const el = document.createElement(tag); el.className = cls;
    el.textContent = content ?? ''; parent.append(el); return el;
  }
  function button(parent,label,action) {
    const b = html('button',parent,'',label); b.type='button'; b.onclick=action; return b;
  }
  function svgEl(tag,parent,attrs={}) {
    const el=document.createElementNS('http://www.w3.org/2000/svg',tag);
    set(el,attrs); parent.append(el); return el;
  }
  function set(el,attrs) { for (const [k,v] of Object.entries(attrs)) el.setAttribute(k,String(v)); }
  const bar=html('div',host,'space-bar');
  const modes=html('div',bar,'space-buttons');
  const space=button(modes,'3D 空间',()=>mode(true));
  const flat=button(modes,'2D 平面',()=>mode(false));
  const tools=html('div',bar,'space-buttons');
  const smaller=button(tools,'−',()=>magnify(-0.15)), larger=button(tools,'＋',()=>magnify(0.15));
  smaller.setAttribute('aria-label','缩小图谱'); larger.setAttribute('aria-label','放大图谱');
  button(tools,'复位',reset);
  const svg=svgEl('svg',host,{class:'space-stage',tabindex:0,role:'group','aria-label':'关系图谱。使用方向键旋转，加减键缩放，Home 复位'});
  const defs=svgEl('defs',svg);
  for (const [kind,colors] of Object.entries(spacePalette)) {
    const grad=svgEl('radialGradient',defs,{id:uid+kind,cx:'30%',cy:'22%',r:'83%'});
    colors.forEach((c,i)=>svgEl('stop',grad,{offset:[0,.55,1][i],'stop-color':c}));
  }
  const floor=svgEl('g',svg,{'aria-hidden':true,fill:'none',stroke:'#7eafa3','stroke-width':.8,opacity:.19});
  const grid=[];
  for (let i=-4;i<=4;i++) {
    const d=i*64;
    grid.push([svgEl('line',floor),[d,116,-255],[d,116,255]],
              [svgEl('line',floor),[-285,116,d],[285,116,d]]);
  }
  const edgeLayer=svgEl('g',svg), nodeLayer=svgEl('g',svg);
  const status=html('p',host,'space-status'); status.setAttribute('aria-live','polite');
  const tip=html('small',bar,'space-tip','拖动旋转 · 点选关系查看出处');
  let width=720, yaw, pitch, zoom, spatial=true, selected='', pickEdge, pickNode;
  let pointer=null, suppressClick=false;
  const byId=new Map(nodes.map(n=>[n.id,{...n,degree:0}]));
  for (const e of edges) { byId.get(e.from).degree++; byId.get(e.to).degree++; }
  const center=[...byId.values()].find(n=>n.kind==='motif') ?? [...byId.values()].sort((a,b)=>b.degree-a.degree)[0];
  const others=[...byId.values()].filter(n=>n!==center);
  // Alternate specimens and shared concepts around the central motif.
  if (center?.kind==='motif') {
    const items=others.filter(n=>n.kind==='artifact'), attrs=others.filter(n=>n.kind!=='artifact');
    others.length=0;
    for (let i=0;i<Math.max(items.length,attrs.length);i++) {
      if (items[i]) others.push(items[i]); if (attrs[i]) others.push(attrs[i]);
    }
  }
  if(center) Object.assign(center,{x:0,y:0,z:40});
  others.forEach((n,i)=>{
    const a=Math.PI+i*2*Math.PI/others.length;
    Object.assign(n,{x:215*Math.cos(a),y:112*Math.sin(a),z:48*Math.cos(2*a+.5)});
  });
  function action(el,fn) {
    el.addEventListener('click',()=>{if(!suppressClick) fn();});
    el.addEventListener('keydown',ev=>{if(ev.key==='Enter'||ev.key===' '){ev.preventDefault();ev.stopPropagation();fn();}});
  }
  const nodeViews=[...byId.values()].map(n=>{
    const radius=n===center?35:n.kind==='artifact'?28:15;
    const g=svgEl('g',nodeLayer,{class:'space-node',tabindex:0,role:'button','aria-label':[n.label,n.sub].filter(Boolean).join(' · ')});
    const ring=svgEl('circle',g,{r:radius+5,fill:'none','stroke-width':1.8});
    svgEl('circle',g,{r:radius,fill:'url(#'+uid+n.kind+')',stroke:spacePalette[n.kind][0],'stroke-width':1});
    if(n.image) {
      const clipId=uid+'crop-'+nodeLayer.childElementCount;
      const clip=svgEl('clipPath',defs,{id:clipId});
      svgEl('circle',clip,{r:radius-3});
      svgEl('image',g,{href:n.image,x:-radius,y:-radius,width:2*radius,height:2*radius,preserveAspectRatio:'xMidYMid slice','clip-path':'url(#'+clipId+')'});
    }
    const name=svgEl('text',g,{class:'space-name','text-anchor':'middle',y:radius+20});
    name.textContent=n.label.length>15?n.label.slice(0,14)+'…':n.label;
    if(n.sub) svgEl('text',g,{class:'space-sub','text-anchor':'middle',y:radius+35}).textContent=n.sub;
    svgEl('title',g).textContent=[n.sub,n.label].filter(Boolean).join(' · ');
    action(g,()=>pickNode(n.id));
    return {n,g,ring,radius};
  });
  const parallels=new Map();
  const edgeViews=edges.map(e=>{
    const pair=JSON.stringify([e.from,e.to].sort()); const siblings=parallels.get(pair)??[];
    const from=byId.get(e.from),to=byId.get(e.to);
    const label=from.label+' → '+e.label+' → '+to.label;
    const g=svgEl('g',edgeLayer,{class:'space-edge',tabindex:0,role:'button','aria-label':label});
    const line=svgEl('path',g,{fill:'none'}), arrow=svgEl('path',g,{});
    svgEl('title',g).textContent=label;
    const hit=svgEl('path',g,{fill:'none',stroke:'transparent','stroke-width':14});
    action(g,()=>pickEdge(e.id));
    const caption=svgEl('text',g,{class:'space-predicate','text-anchor':'middle'});
    caption.textContent=e.label;
    const v={e,from,to,g,line,arrow,hit,caption,siblings,index:siblings.length};
    siblings.push(v);parallels.set(pair,siblings);return v;
  });
  function project(x,y,z) {
    const dx=x*Math.cos(yaw)+z*Math.sin(yaw), dz=z*Math.cos(yaw)-x*Math.sin(yaw);
    const dy=y*Math.cos(pitch)-dz*Math.sin(pitch), depth=y*Math.sin(pitch)+dz*Math.cos(pitch);
    const k=zoom*(spatial?780/(780-depth):1);
    return {x:width/2+dx*k*Math.min(1,(width-115)/500),y:173+dy*k,z:depth,k};
  }
  function render() {
    width=Math.max(345,Math.min(860,host.clientWidth || 720));
    svg.setAttribute('viewBox','0 0 '+width+' 390');
    floor.setAttribute('display',spatial?'inline':'none');
    for(const [el,a,b] of grid) {
      const p=project(...a),q=project(...b);set(el,{x1:p.x,y1:p.y,x2:q.x,y2:q.y});
    }
    const points=new Map();
    for(const view of nodeViews) {
      const {n}=view,p=project(n.x,n.y,n.z);points.set(n.id,{...p,r:view.radius*p.k});
      view.g.setAttribute('transform','translate('+p.x+' '+p.y+') scale('+p.k+')');
    }
    const sorted=[...nodeViews].sort((a,b)=>points.get(a.n.id).z-points.get(b.n.id).z);
    // Reorder only when the depth order changes, so pointer targets and keyboard focus stay stable.
    const order=sorted.map(v=>v.n.id).join('\n');
    if(nodeLayer.getAttribute('data-order')!==order){
      const focused=document.activeElement;
      for(const v of sorted) nodeLayer.append(v.g);
      if(nodeLayer.contains(focused)) focused.focus();
      nodeLayer.setAttribute('data-order',order);
    }
    for(const v of edgeViews) {
      const a=points.get(v.e.from),b=points.get(v.e.to);
      const dx=b.x-a.x,dy=b.y-a.y,len=Math.hypot(dx,dy)||1;
      const bend=(v.index-(v.siblings.length-1)/2)*25*(v.e.from>v.e.to?-1:1);
      const cx=(a.x+b.x)/2-bend*dy/len,cy=(a.y+b.y)/2+bend*dx/len;
      const loop=v.e.from===v.e.to;
      const angle=loop?1.9:Math.atan2(b.y-cy,b.x-cx);
      const x=b.x-Math.cos(angle)*(b.r+3), y=b.y-Math.sin(angle)*(b.r+3);
      const d=loop?'M '+(a.x-a.r)+' '+a.y+' C '+(a.x-65)+' '+(a.y-74)+' '+(a.x+40)+' '+(a.y-78)+' '+x+' '+y:
        'M '+a.x+' '+a.y+' Q '+cx+' '+cy+' '+x+' '+y;
      set(v.caption,{x:(a.x+2*cx+b.x)/4,y:loop?a.y-52:(a.y+2*cy+b.y)/4-6});
      v.line.setAttribute('d',d);v.hit.setAttribute('d',d);
      set(v.arrow,{d:'M0 0 L-8 -3.6 L-8 3.6 Z',transform:'translate('+x+' '+y+') rotate('+angle*180/Math.PI+')'});
    }
    svg.setAttribute('data-labels',width>=530 && edges.length<=8?'all':'selected');
    smaller.disabled=zoom<=.7;larger.disabled=zoom>=1.45;
  }
  function mode(on) {
    spatial=on;space.setAttribute('aria-pressed',String(on));flat.setAttribute('aria-pressed',String(!on));
    tip.textContent=on?'拖动旋转 · 点选关系查看出处':'点选关系查看出处';
    reset();
  }
  function reset() {yaw=spatial ? -.16 : 0; pitch=spatial ? .19 : 0;zoom=1;render();}
  function magnify(d) {zoom=Math.max(.7,Math.min(1.45,zoom+d));render();}
  function rotate(dx,dy){yaw+=dx;pitch=Math.max(-1,Math.min(1,pitch+dy));render();}
  svg.onpointerdown=ev=>{
    if(ev.button!==0||!ev.isPrimary) return;
    suppressClick=false;
    if(spatial) pointer={id:ev.pointerId,x:ev.clientX,y:ev.clientY,drag:false};
  };
  svg.onpointermove=ev=>{
    if(pointer?.id!==ev.pointerId) return;
    const dx=ev.clientX-pointer.x,dy=ev.clientY-pointer.y;
    if(!pointer.drag && Math.hypot(dx,dy)<4) return;
    pointer.drag=true; suppressClick=true;svg.setPointerCapture(ev.pointerId);
    pointer.x=ev.clientX; pointer.y=ev.clientY;rotate(dx*.009,dy*.008);
  };
  svg.onpointerup=svg.onpointercancel=svg.onlostpointercapture=()=>{pointer=null;};
  svg.onpointerleave=()=>{if(!pointer?.drag) pointer=null;};
  svg.onkeydown=ev=>{
    const turns={ArrowLeft:[-.14,0],ArrowRight:[.14,0],ArrowUp:[0,-.12],ArrowDown:[0,.12]};
    if(spatial&&turns[ev.key]) rotate(...turns[ev.key]);
    else if(ev.key==='Home') reset(); else if(ev.key==='+'||ev.key==='=') magnify(.15);
    else if(ev.key==='-') magnify(-.15); else return;
    ev.preventDefault();
  };
  mode(true);
  const observer=typeof ResizeObserver==='undefined'?null:new ResizeObserver(render);observer?.observe(host);
  return {
    select(id,onEdge,onNode) {
      selected=id;pickEdge=onEdge;pickNode=onNode;
      const current=edges.find(e=>e.id===selected);
      for(const v of edgeViews) v.g.setAttribute('data-selected',String(v.e.id===selected));
      for(const {n,ring} of nodeViews) ring.setAttribute('stroke',current&&(current.from===n.id||current.to===n.id)?'#ffc477':'transparent');
      status.textContent=current?[byId.get(current.from).label,current.label,byId.get(current.to).label].join('　→　'):nodes.length+' 个实体 · '+edges.length+' 条关系';
    },
    dispose(){observer?.disconnect();host.replaceChildren();}
  };
}
