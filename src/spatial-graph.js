import { cameraDistance, castToFloor, coneVertices, floorY, depthCuts, splitByDepth } from './edge-depth.js';
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
  // The background stays in screen space. The plinth and its contents share the camera.
  const studio=svgEl('linearGradient',defs,{id:uid+'studio',x1:'0%',y1:'0%',x2:'80%',y2:'100%'});
  svgEl('stop',studio,{offset:0,'stop-color':'#fdfcf9'});
  svgEl('stop',studio,{offset:1,'stop-color':'#eeede9'});
  const penumbra=svgEl('radialGradient',defs,{id:uid+'shadow'});
  for (const [offset,opacity] of [[0,.68],[.42,.54],[.72,.21],[1,0]]) {
    svgEl('stop',penumbra,{offset,'stop-color':'#4b4843','stop-opacity':opacity});
  }
  const backdrop=svgEl('g',svg,{'aria-hidden':true,'pointer-events':'none'});
  svgEl('rect',backdrop,{width:'100%',height:'100%',fill:'url(#'+uid+'studio)'});
  const plinth=svgEl('g',backdrop,{class:'space-plinth'});
  const rim=svgEl('path',plinth,{fill:'#cbc7be',stroke:'#c6c2b8','stroke-width':.8});
  const surface=svgEl('path',plinth,{fill:'#e8e5de',stroke:'#c9c5bc','stroke-width':1});
  const perimeter=[[-238,-162],[238,-162],[286,-95],[286,95],[238,162],[-238,162],[-286,95],[-286,-95]];
  const clip=svgEl('clipPath',defs,{id:uid+'receiver'});
  const clipFace=svgEl('path',clip);
  const ink=svgEl('g',plinth,{'clip-path':'url(#'+uid+'receiver)'});
  const shadows=svgEl('g',ink,{fill:'url(#'+uid+'shadow)'});
  const blur=svgEl('filter',defs,{id:uid+'wire-blur',filterUnits:'userSpaceOnUse',x:-160,y:-180,width:1280,height:850});
  svgEl('feGaussianBlur',blur,{stdDeviation:1.5});
  const wireShadows=svgEl('g',ink,{filter:'url(#'+uid+'wire-blur)',opacity:.29,'pointer-events':'none'});
  const scene=svgEl('g',svg,{class:'space-objects'});
  let previousOrder=[];
  const status=html('p',host,'space-status'); status.setAttribute('aria-live','polite');
  const tip=html('small',bar,'space-tip','拖动旋转 · 点选关系');
  let width=720, yaw, pitch, zoom, spatial=true, selected='', pickEdge, pickNode;
  let pointer=null, suppressClick=false;
  const dense=nodes.length>=15;
  const glyphScale=dense?Math.min(.65,2.8/Math.sqrt(nodes.length)):1;
  svg.setAttribute('data-density',dense?'dense':'regular');
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
  if(center) Object.assign(center,{x:0,y:0,z:24,flatY:0});
  others.forEach((n,i)=>{
    if(dense) {
      // Fill the footprint instead of stacking every sample on one perimeter.
      const distance=Math.sqrt((i+1)/others.length);
      const angle=i*Math.PI*(3-Math.sqrt(5));
      const x=245*distance*Math.cos(angle),flatY=155*distance*Math.sin(angle);
      Object.assign(n,{x,flatY,y:.56*flatY,z:.67*flatY+26*Math.sin(i*1.7)});
      return;
    }
    const a=Math.PI+i*2*Math.PI/others.length;
    Object.assign(n,{x:215*Math.cos(a),y:78*Math.sin(a),z:105*Math.sin(a)+25*Math.cos(2*a+.5),flatY:120*Math.sin(a)});
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
    const cast=svgEl('path',shadows,{});
    const g=svgEl('g',scene,{class:'space-node','data-kind':n.kind,tabindex:0,role:'button','aria-label':[n.label,n.sub].filter(Boolean).join(' · ')});
    if(n.kind==='material') materialMark(g,n.label);
    else if(n.kind==='period') periodMark(g,n.label);
    else if(n.kind==='concept') {
      svgEl('rect',g,{x:-radius*.7,y:-radius*.7,width:radius*1.4,height:radius*1.4,rx:5,fill:'#dfdbd3',stroke:'#928a7c'});
    } else {
      svgEl('circle',g,{class:'space-rim',r:radius,cy:1.8,fill:n.image?'#a79c8e':spacePalette[n.kind][2]});
      svgEl('circle',g,{class:'space-face',r:radius,fill:n.image?'#fffdfa':'url(#'+uid+n.kind+')',
        stroke:n.image?'#cec7bc':spacePalette[n.kind][1],'stroke-width':.9});
      if(n.image) {
        const clipId=uid+'crop-'+scene.childElementCount;
        const clip=svgEl('clipPath',defs,{id:clipId});
        svgEl('circle',clip,{r:radius-3});
        svgEl('image',g,{href:n.image,x:-radius,y:-radius,width:2*radius,height:2*radius,preserveAspectRatio:'xMidYMid slice','clip-path':'url(#'+clipId+')'});
      }
    }
    const outline={class:'space-selection',fill:'none','stroke-width':1.8};
    if(emblem) svgEl('rect',g,{...outline,x:-29,y:-25,width:58,height:51,rx:10});
    else svgEl('circle',g,{...outline,r:radius+4});
    const name=svgEl('text',g,{class:'space-name','text-anchor':'middle',y:radius+20});
    if(dense) {
      name.setAttribute('transform','translate(0 '+(radius+15/glyphScale)+') scale('+(1/glyphScale)+')');
      name.setAttribute('y',0);
    }
    name.textContent=n.label.length>15?n.label.slice(0,14)+'…':n.label;
    if(n.sub) svgEl('text',g,{class:'space-sub','text-anchor':'middle',y:radius+35}).textContent=n.sub;
    svgEl('title',g).textContent=[n.sub,n.label].filter(Boolean).join(' · ');
    action(g,()=>pickNode(n.id));
    return {n,g,radius:radius*glyphScale,cast};
  });
  const parallels=new Map();
  const edgeViews=edges.map(e=>{
    const pair=JSON.stringify([e.from,e.to].sort()); const siblings=parallels.get(pair)??[];
    const label=byId.get(e.from).label+' → '+e.label+' → '+byId.get(e.to).label;
    const g=svgEl('g',scene,{class:'space-edge',tabindex:0,role:'button','aria-label':label});
    const arrow=svgEl('path',g,{class:'space-arrow'});
    svgEl('title',g).textContent=label;
    action(g,()=>pickEdge(e.id));
    const caption=svgEl('text',scene,{class:'space-predicate','text-anchor':'middle'});
    caption.textContent=e.label;
    action(caption,()=>pickEdge(e.id));
    const shade=svgEl('path',wireShadows,{fill:'none',stroke:'#60594f','stroke-linecap':'round'});
    const arrowShade=svgEl('path',wireShadows,{fill:'#60594f'});
    const v={e,g,arrow,caption,shade,arrowShade,siblings,index:siblings.length,strokes:[]};
    siblings.push(v);parallels.set(pair,siblings);return v;
  });
  function project(x,y,z) {
    const dx=x*Math.cos(yaw)+z*Math.sin(yaw), dz=z*Math.cos(yaw)-x*Math.sin(yaw);
    const dy=y*Math.cos(pitch)-dz*Math.sin(pitch), depth=y*Math.sin(pitch)+dz*Math.cos(pitch);
    const k=zoom*(spatial?cameraDistance/(cameraDistance-depth):1);
    return {x:width/2+dx*k*Math.min(1,(width-115)/500),y:173+dy*k,z:depth,k};
  }
  function onScreen(p) { return project(p.x,p.y,p.z); }
  function onFloor(p) { return onScreen(castToFloor(p)); }
  function makeCurve(v,flat) {
    const node=id=>{
      const n=byId.get(id);
      return {x:n.x,y:flat?n.flatY:n.y,z:flat?0:n.z};
    };
    const a=node(v.e.from),b=node(v.e.to);
    const dx=b.x-a.x,dy=b.y-a.y,dz=b.z-a.z;
    const bend=(v.index-(v.siblings.length-1)/2)*25*(v.e.from>v.e.to?-1:1);
    const loop=v.e.from===v.e.to, norm=Math.hypot(dx,dy)||1;
    const steps=loop?32:bend?20:2, points=[];
    for(let i=0;i<=steps;i++) {
      const t=i/steps, u=1-t;
      if(loop) points.push({x:a.x+3*u*t*(-75*u+65*t),y:a.y-3*u*t*90,z:a.z+(flat?0:90*u*t)});
      else points.push({x:a.x+t*dx-2*u*t*bend*dy/norm,y:a.y+t*dy+2*u*t*bend*dx/norm,z:a.z+t*dz});
    }
    // End each wire on its entity's surface in world space, including curved and self edges.
    function trim(origin,r) {
      const outside=points.findIndex(p=>Math.hypot(p.x-origin.x,p.y-origin.y,p.z-origin.z)>r);
      if(outside<0) {points.length=0;return;}
      if(outside===0) return;
      const u=points[outside-1],v=points[outside];
      const x=v.x-u.x,y=v.y-u.y,z=v.z-u.z;
      const ox=u.x-origin.x,oy=u.y-origin.y,oz=u.z-origin.z;
      const len2=x*x+y*y+z*z,dot=ox*x+oy*y+oz*z;
      const t=(-dot+Math.sqrt(Math.max(0,dot*dot-len2*(ox*ox+oy*oy+oz*oz-r*r))))/len2;
      points.splice(0,outside,{x:u.x+t*x,y:u.y+t*y,z:u.z+t*z});
    }
    trim(a,radii.get(v.e.from)+2);
    points.reverse();trim(b,radii.get(v.e.to)+3);points.reverse();
    return points;
  }
  const radii=new Map(nodeViews.map(v=>[v.n.id,v.radius]));
  function shape(v,flat) {
    const points=makeCurve(v,flat),tip=points.at(-1);
    return {points,head:points.length>1?coneVertices(points.at(-2),tip):[]};
  }
  for(const v of edgeViews) {v.spatial=shape(v,false);v.flat=shape(v,true);}
  function pathOf(points) {
    return points.map((p,i)=>(i?'L':'M')+p.x.toFixed(2)+' '+p.y.toFixed(2)).join(' ');
  }
  function silhouette(points) {
    const sorted=[...points].sort((a,b)=>a.x-b.x||a.y-b.y);
    function half(vertices) {
      const h=[];
      for(const p of vertices) {
        while(h.length>1) {
          const a=h[h.length-2],b=h[h.length-1];
          if((b.x-a.x)*(p.y-a.y)>(b.y-a.y)*(p.x-a.x)) break;
          h.pop();
        }
        h.push(p);
      }
      return h.slice(0,-1);
    }
    return pathOf([...half(sorted),...half(sorted.reverse())])+' Z';
  }
  function strokeAt(v,i) {
    if(v.strokes[i]) return v.strokes[i];
    const g=svgEl('g',scene,{class:'space-edge','aria-hidden':true});
    const line=svgEl('path',g,{class:'space-wire',fill:'none','stroke-linecap':'round'});
    const hit=svgEl('path',g,{fill:'none',stroke:'transparent','stroke-width':14});
    action(g,()=>pickEdge(v.e.id));
    const stroke={g,line,hit};v.strokes.push(stroke);
    return stroke;
  }
  function render() {
    width=Math.max(345,Math.min(860,host.clientWidth || 720));
    svg.setAttribute('viewBox','0 0 '+width+(spatial?' 490':' 390'));
    svg.setAttribute('data-mode',spatial?'space':'flat');
    plinth.setAttribute('display',spatial?'inline':'none');
    if(spatial) {
      const face=pathOf(perimeter.map(([x,z])=>project(x,floorY,z)))+' Z';
      surface.setAttribute('d',face);clipFace.setAttribute('d',face);
      const lower=perimeter.map(([x,z])=>project(x,floorY+4,z));
      rim.setAttribute('d',silhouette([...lower,...perimeter.map(([x,z])=>project(x,floorY,z))]));
    }
    const points=new Map(), paint=[];
    for(const view of nodeViews) {
      const {n}=view,p=project(n.x,spatial?n.y:n.flatY,spatial?n.z:0);
      points.set(n.id,{...p,r:view.radius*p.k});
      if(spatial) {
        const foot=castToFloor(n),height=floorY-n.y;
        const r=view.radius+4+.07*height;
        const footprint=Array.from({length:24},(_,i)=>{
          const a=i*Math.PI/12;
          return project(foot.x+r*Math.cos(a),floorY,foot.z+r*Math.sin(a));
        });
        set(view.cast,{d:pathOf(footprint)+' Z',opacity:.83-height*.0018});
      }
      paint.push({el:view.g,z:spatial?p.z:1});
      view.g.setAttribute('transform','translate('+p.x+' '+p.y+') scale('+(p.k*glyphScale)+')');
    }
    const curves=edgeViews.map(v=>(spatial?v.spatial:v.flat).points.map(onScreen));
    const bounds=dense?nodeViews.map(({n})=>{
      const p=points.get(n.id),half=Math.max(p.r+8,Math.min(n.label.length,15)*8*p.k);
      return {left:p.x-half,right:p.x+half,top:p.y-p.r-8,bottom:p.y+p.r+32*p.k,z:p.z};
    }):[];
    const cuts=spatial?depthCuts(curves,dense?[]:[...points.values()].map(p=>p.z),bounds):[];
    edgeViews.forEach((v,i)=>{
      const curve=curves[i],shown=curve.length>0,display=shown?'inline':'none';
      for(const el of [v.g,v.caption,v.shade,v.arrowShade]) el.setAttribute('display',display);
      const pieces=splitByDepth(curve,cuts[i] ?? []);
      for(let j=0;j<pieces.length;j++){
        const part=pieces[j],stroke=strokeAt(v,j),d=pathOf([part.a,part.b]);
        set(stroke.g,{display:'inline','data-selected':String(v.e.id===selected)});
        stroke.line.setAttribute('d',d);stroke.hit.setAttribute('d',d);
        paint.push({el:stroke.g,z:part.z});
      }
      for(let j=pieces.length;j<v.strokes.length;j++) v.strokes[j].g.setAttribute('display','none');
      if(!shown) return;
      const tip=curve[curve.length-1],mid=curve[Math.floor(curve.length/2)];
      const geometry=spatial?v.spatial:v.flat;
      v.arrow.setAttribute('d',silhouette(geometry.head.map(onScreen)));
      set(v.caption,{x:mid.x,y:mid.y-6});
      paint.push({el:v.g,z:tip.z+.0001},{el:v.caption,z:mid.z+.0001});
      if(spatial) {
        set(v.shade,{d:pathOf(geometry.points.map(onFloor)),'stroke-width':1.8*zoom});
        v.arrowShade.setAttribute('d',silhouette(geometry.head.map(onFloor)));
      }
    });
    paint.sort((a,b)=>a.z-b.z);
    if(previousOrder.length!==paint.length || paint.some((v,i)=>v.el!==previousOrder[i])) {
      const focused=scene.contains(document.activeElement)?document.activeElement:null;
      for(const v of paint) scene.append(v.el);
      focused?.focus();previousOrder=paint.map(v=>v.el);
    }
    svg.setAttribute('data-labels',width>=530 && edges.length<=8?'all':'selected');
    smaller.disabled=zoom<=.7;larger.disabled=zoom>=1.45;
  }
  function mode(on) {
    spatial=on;space.setAttribute('aria-pressed',String(on));flat.setAttribute('aria-pressed',String(!on));
    tip.textContent=on?'拖动旋转 · 点选关系':'点选关系';
    reset();
  }
  function reset() {yaw=spatial ? -.16 : 0; pitch=spatial ? -.56 : 0;zoom=spatial ? .87 : 1;render();}
  function magnify(d) {zoom=Math.max(.7,Math.min(1.45,zoom+d));render();}
  function rotate(dx,dy){yaw+=dx;pitch=Math.max(-1.03,Math.min(-.12,pitch+dy));render();}
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
      for(const v of edgeViews) {
        const active=String(v.e.id===selected);
        for(const el of [v.g,v.caption,...v.strokes.map(s=>s.g)]) el.setAttribute('data-selected',active);
      }
      for(const {n,g} of nodeViews) g.setAttribute('data-selected',String(Boolean(current&&(current.from===n.id||current.to===n.id))));
      status.textContent=current?[byId.get(current.from).label,current.label,byId.get(current.to).label].join('　→　'):nodes.length+' 个实体 · '+edges.length+' 条关系';
    },
    dispose(){observer?.disconnect();host.replaceChildren();}
  };
}
