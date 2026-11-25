// Shared by the desktop atlas and the self-contained, offline book viewer.
export function drawNetwork(svg, groups, picked, onPick) {
  const ns = 'http://www.w3.org/2000/svg';
  const label = { period:'所属时代', made_of:'材质', uses_technique:'工艺' };
  const restoreFocus = svg.contains(document.activeElement);
  svg.replaceChildren();
  if (!groups.length) return;
  function element(tag, attrs, parent = svg) {
    const e = document.createElementNS(ns, tag);
    for (const [name,value] of Object.entries(attrs)) e.setAttribute(name,String(value));
    parent.append(e);
    return e;
  }
  function text(parent, x, y, value, size, color, anchor = 'middle') {
    const t = element('text',{x,y,'font-size':size,fill:color,'text-anchor':anchor},parent);
    t.textContent = value;
  }
  const gap = 62;
  const bands = groups.map(g => Math.max(115, gap * g.filter(r=>r.predicate !== 'decorated_with').length + 20));
  const height = bands.reduce((a,b)=>a+b,0) + 30;
  svg.setAttribute('viewBox','0 0 750 ' + height);
  svg.setAttribute('aria-label','纹样、器物与已记录属性的关系图');
  function node(x,y,w,kind,value,active,action,focusTarget=false) {
    const g = element('g', {tabindex:0,role:'button','aria-label':kind+' '+value,style:'cursor:pointer'});
    if (restoreFocus && focusTarget) g.focus();
    g.addEventListener('click',action);
    g.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();action();}});
    const dark = kind === '纹样';
    element('rect',{x,y:y-23,width:w,height:46,rx:6,fill:dark?'#48392e':active?'#f3dfce':'#fbf8f0',
      stroke:active?'#92432e':'#bbafa0','stroke-width':active?2:1},g);
    text(g,x+w/2,y-6,kind,10,dark?'#e8dbc7':'#685b50');
    text(g,x+w/2,y+12,value.length>17?value.slice(0,16)+'…':value,14,dark?'white':'#332a24');
    element('title',{},g).textContent=value;
  }
  function edge(x1,y1,x2,y2,caption,row) {
    const g = element('g',{style:'cursor:pointer'});
    const mid=(x1+x2)/2;
    const path='M'+x1+' '+y1+' C'+mid+' '+y1+' '+mid+' '+y2+' '+x2+' '+y2;
    element('path',{d:path,fill:'none',stroke:picked===row.id?'#94412c':'#a69b89','stroke-width':2},g);
    element('path',{d:path,fill:'none',stroke:'transparent','stroke-width':16},g);
    const sign=x2>x1?1:-1;
    element('path',{d:'M'+(x2-sign*7)+' '+(y2-4)+' L'+x2+' '+y2+' L'+(x2-sign*7)+' '+(y2+4),fill:'none',stroke:'#82725f'},g);
    text(g,mid,(y1+y2)/2-5,caption,12,'#51463b');
    g.addEventListener('click',()=>onPick(row.id));
  }
  let top=15;
  const center=height/2;
  const nodes=[];
  for (const [i,g] of groups.entries()) {
    const y=top+bands[i]/2;
    edge(284,y,155,center,'饰有纹样',g[0]);
    nodes.push(()=>node(284,y,170,g[0].findspot ?? ('器物 · 图 '+g[0].item),g[0].artifact,g.some(r=>r.id===picked),()=>onPick(g[0].id),g[0].id===picked));
    const attrs=g.filter(r=>r.predicate!=='decorated_with');
    attrs.forEach((r,j)=>{
      const yy=y+(j-(attrs.length-1)/2)*gap;
      edge(454,y,590,yy,label[r.predicate],r);
      nodes.push(()=>node(590,yy,146,label[r.predicate],r.object,r.id===picked,()=>onPick(r.id),r.id===picked));
    });
    top+=bands[i];
  }
  node(8,center,147,'纹样',groups[0][0].object,false,()=>onPick(groups[0][0].id));
  nodes.forEach(add=>add());
}
