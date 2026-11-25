// A compact perspective renderer shared by the application and the single-file atlas.
const spaceScenes = new WeakMap();
let spaceSerial = 0;
const spacePalette = {
  motif: ['#fff5e6','#d7ae87','#866347'], artifact: ['#fffaf2','#dcc6ac','#8f7864']
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
  // A continuous studio backdrop also provides a surface for the soft cast shadows.
  const studio=svgEl('linearGradient',defs,{id:uid+'studio',x1:'0%',y1:'0%',x2:'80%',y2:'100%'});
  svgEl('stop',studio,{offset:0,'stop-color':'#fdfcf9'});
  svgEl('stop',studio,{offset:1,'stop-color':'#eeede9'});
  const penumbra=svgEl('radialGradient',defs,{id:uid+'shadow'});
  for (const [offset,opacity] of [[0,.68],[.42,.54],[.72,.21],[1,0]]) {
    svgEl('stop',penumbra,{offset,'stop-color':'#4b4843','stop-opacity':opacity});
  }
  const backdrop=svgEl('g',svg,{'aria-hidden':true,'pointer-events':'none'});
  svgEl('rect',backdrop,{width:'100%',height:'100%',fill:'url(#'+uid+'studio)'});
  const shadows=svgEl('g',backdrop,{fill:'url(#'+uid+'shadow)'});
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
    Object.assign(n,{x:215*Math.cos(a),y:120*Math.sin(a),z:48*Math.cos(2*a+.5)});
  });
  function action(el,fn) {
    el.addEventListener('click',()=>{if(!suppressClick) fn();});
    el.addEventListener('keydown',ev=>{if(ev.key==='Enter'||ev.key===' '){ev.preventDefault();ev.stopPropagation();fn();}});
  }
  function materialMark(g,label) {
    // Illustrative samples. Only the actual material name comes from the graph.
    const ceramic=/^(彩陶|黑陶|灰陶|红陶|白陶|陶)(质|器|土)?$/.test(label);
    const bronze=/^(青铜|铜|黄铜|红铜)(质|器)?$/.test(label);
    const jade=/^(玉|青玉|白玉|碧玉|翡翠)(质|石|器)?$/.test(label);
    const textile=/^(丝|丝绸|织锦|棉|麻|纺织)(织物|织品|布)?$/.test(label);
    const colors=ceramic?['#be7753','#804b38','#dfac84']:bronze?['#9c8451','#5d5640','#cbb98b']:
      jade?['#adc1af','#788d80','#e0e5d9']:textile?['#c3a181','#967654','#eddbc0']:['#b6ada0','#867e72','#e0dacf'];
    g.setAttribute('data-symbol',ceramic?'ceramic':bronze?'bronze':jade?'jade':textile?'textile':'sample');
    const tile=svgEl('g',g,{'stroke-linejoin':'round'});
    svgEl('path',tile,{d:'M-23 -12 L-9 -21 L19 -16 L24 -5 L17 13 L4 20 L-21 13 Z',fill:colors[0],stroke:colors[1],'stroke-width':1.2});
    svgEl('path',tile,{d:'M-21 8 L3 14 L16 8 L24 -5 L17 13 L4 20 L-21 13 Z',fill:colors[1]});
    svgEl('path',tile,{d:'M-21 -11 L-9 -19 L17 -15',fill:'none',stroke:colors[2],'stroke-width':1.6});
    if(ceramic) {
      for(const [x,y,r] of [[-15,-8,1.1],[-9,4,.9],[-7,-13,1.2],[2,0,1.3],[10,-8,.85],[13,3,1],[-17,1,.65],[3,-10,.6]]) {
        svgEl('circle',tile,{cx:x,cy:y,r,fill:colors[1],opacity:.74});
      }
      svgEl('path',tile,{d:'M-14 10 l5 1 m8 3 l5 1 m8 -5 l3 -2',stroke:colors[2],fill:'none','stroke-width':1.2});
    } else if(jade) {
      svgEl('path',tile,{d:'M-20 4 Q-10 3 -5 -6 T14 -12 M-3 10 Q1 4 14 -1',fill:'none',stroke:colors[2],'stroke-width':2});
    } else if(bronze) {
      svgEl('path',tile,{d:'M-16 2 L-2 -13 M-10 5 L6 -12 M4 3 L13 -7',stroke:colors[2],opacity:.7});
    } else if(textile) {
      svgEl('path',tile,{d:'M-14 -9 l-2 13 m9 -15 l-3 17 m10 -16 l-3 17 m10 -16 l-3 15 M-17 -5 l32 4 m-33 1 l30 4 m-31 1 l23 4',stroke:colors[2],fill:'none'});
    }
  }
  function periodMark(g,label) {
    const stone=label==='新石器时代';
    g.setAttribute('data-symbol',stone?'stone-adze':'period-seal');
    const badge=svgEl('g',g,{'stroke-linejoin':'round'});
    svgEl('path',badge,{d:'M-20 -16 Q-20 -20 -16 -20 H16 Q20 -20 20 -16 V12 L0 22 L-20 12 Z',fill:'#eee7d8',stroke:'#8a7860','stroke-width':1.4});
    svgEl('path',badge,{d:'M-16 10 L0 18 L16 10',stroke:'#ad9577',fill:'none','stroke-width':1.1});
    if(stone) {
      // A polished stone-tool emblem for the period, separate from artifact photographs.
      svgEl('path',badge,{d:'M-3 -14 Q2 -18 6 -12 L11 5 Q3 11 -9 7 Z',fill:'#687075',stroke:'#454c50','stroke-width':1.2});
      svgEl('path',badge,{d:'M-3 -12 L-5 4 L2 5 L4 -12 Z',fill:'#959b98'});
      svgEl('path',badge,{d:'M-8 5 Q1 8 10 3 L11 6 Q2 12 -9 7 Z',fill:'#c1c3b8'});
    } else {
      const stamp=svgEl('text',badge,{'text-anchor':'middle',y:5,'font-size':14,fill:'#5b4d3d','font-weight':650});
      const short=label.replace(/(?:时代|时期|王朝|朝|代)$/, '');
      if(short.length>0 && short.length<=2) stamp.textContent=short;
      else svgEl('path',badge,{d:'M-12 -2 H12 M-9 -7 V3 M0 -5 V1 M9 -7 V3',fill:'none',stroke:'#736250','stroke-width':2});
    }
  }
  const nodeViews=[...byId.values()].map(n=>{
    const emblem=n.kind==='material'||n.kind==='period';
    const radius=emblem?25:n===center?40:n.kind==='artifact'?32:16;
    const cast=svgEl('ellipse',shadows,{});
    const contact=svgEl('ellipse',shadows,{});
    const g=svgEl('g',nodeLayer,{class:'space-node','data-kind':n.kind,tabindex:0,role:'button','aria-label':[n.label,n.sub].filter(Boolean).join(' · ')});
    if(n.kind==='material') materialMark(g,n.label);
    else if(n.kind==='period') periodMark(g,n.label);
    else if(n.kind==='concept') {
      svgEl('rect',g,{x:-radius*.7,y:-radius*.7,width:radius*1.4,height:radius*1.4,rx:5,fill:'#dfdbd3',stroke:'#928a7c'});
    } else {
      svgEl('circle',g,{class:'space-rim',r:radius,cy:1.8,fill:n.image?'#a79c8e':spacePalette[n.kind][2]});
      svgEl('circle',g,{class:'space-face',r:radius,fill:n.image?'#fffdfa':'url(#'+uid+n.kind+')',
        stroke:n.image?'#cec7bc':spacePalette[n.kind][1],'stroke-width':.9});
      if(n.image) {
        const clipId=uid+'crop-'+nodeLayer.childElementCount;
        const clip=svgEl('clipPath',defs,{id:clipId});
        svgEl('circle',clip,{r:radius-3});
        svgEl('image',g,{href:n.image,x:-radius,y:-radius,width:2*radius,height:2*radius,preserveAspectRatio:'xMidYMid slice','clip-path':'url(#'+clipId+')'});
      }
    }
    const outline={class:'space-selection',fill:'none','stroke-width':1.8};
    if(emblem) svgEl('rect',g,{...outline,x:-29,y:-25,width:58,height:51,rx:10});
    else svgEl('circle',g,{...outline,r:radius+4});
    const name=svgEl('text',g,{class:'space-name','text-anchor':'middle',y:radius+20});
    name.textContent=n.label.length>15?n.label.slice(0,14)+'…':n.label;
    if(n.sub) svgEl('text',g,{class:'space-sub','text-anchor':'middle',y:radius+35}).textContent=n.sub;
    svgEl('title',g).textContent=[n.sub,n.label].filter(Boolean).join(' · ');
    action(g,()=>pickNode(n.id));
    return {n,g,radius,cast,contact};
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
    svg.setAttribute('data-mode',spatial?'space':'flat');
    shadows.setAttribute('display',spatial?'inline':'none');
    const points=new Map();
    for(const view of nodeViews) {
      const {n}=view,p=project(n.x,n.y,n.z);points.set(n.id,{...p,r:view.radius*p.k});
      if(spatial) {
        // A fixed upper-left light: increasing separation from the backing plane
        // widens and displaces the shadow while reducing its peak density.
        const lift=Math.max(0,Math.min(1,(p.z+230)/460));
        const radius=view.radius*p.k;
        const spread=radius*(1.17+.37*lift);
        set(view.cast,{cx:p.x+(5+15*lift)*p.k,cy:p.y+(8+18*lift)*p.k,
          rx:spread,ry:spread*.94,opacity:.87-.24*lift});
        set(view.contact,{cx:p.x+2*p.k,cy:p.y+4*p.k,rx:radius*1.14,ry:radius*1.13,opacity:.6-.25*lift});
      }
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
    pointer.x=ev.clientX; pointer.y=ev.clientY;rotate(dx*.009,-dy*.008);
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
      for(const {n,g} of nodeViews) g.setAttribute('data-selected',String(Boolean(current&&(current.from===n.id||current.to===n.id))));
      status.textContent=current?[byId.get(current.from).label,current.label,byId.get(current.to).label].join('　→　'):nodes.length+' 个实体 · '+edges.length+' 条关系';
    },
    dispose(){observer?.disconnect();host.replaceChildren();}
  };
}
