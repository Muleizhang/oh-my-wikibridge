import { drawNetwork } from './motif-network.js';
import { useEffect, useMemo, useRef, useState } from 'react';
import { call, desktop, errorText } from './api';
import { catalog, motifQuestion, relations, specimens, type Box, type MotifRow } from './motif-data';

import './folio.css';

type View = 'detail' | 'whole';
type Zoom = { src: string; label: string; locator: string };

function Plate({ row, view, onZoom }: { row: MotifRow; view: View; onZoom: (value: Zoom) => void }) {
  const full = useRef<HTMLCanvasElement>(null);
  const detail = useRef<HTMLCanvasElement>(null);
  const [error, setError] = useState('');
  const [ready, setReady] = useState(false);
  useEffect(() => {
    if (row.imageUrl || !row.regions || !desktop) return;
    setReady(false); setError('');
    let active = true;
    let close: (() => Promise<void>) | undefined;
    const regions = row.regions;
    (async () => {
      const { openPdf, renderPage } = await import('./pdf');
      if (!active) return;
      const opened = await openPdf(row.sourceId, row.bytes);
      if (!active) { await opened.close(); return; }
      close = opened.close;
      const page = document.createElement('canvas');
      const task = await renderPage(opened.pdf, row.page, 1700, page);
      await task.promise;
      if (!active) return;
      function crop(target: HTMLCanvasElement | null, box: Box) {
        if (!target) return;
        const [x, y, endX, endY] = box;
        target.width = Math.max(1, Math.round((endX-x)*page.width));
        target.height = Math.max(1, Math.round((endY-y)*page.height));
        target.getContext('2d')?.drawImage(page, x*page.width, y*page.height, target.width, target.height,
          0, 0, target.width, target.height);
      }
      crop(full.current, regions.artifact);
      crop(detail.current, regions.motif);
      setReady(true);
    })().catch(e => { if (active) setError(errorText(e)); }).finally(() => { const release = close; close = undefined; void release?.(); });
    return () => { active = false; const release = close; close = undefined; void release?.(); };
  }, [row]);
  const label = view === 'detail' ? row.detailLabel ?? '纹样局部' : '器物全图';
  const image = view === 'detail' ? row.detailUrl : row.imageUrl;
  const description = row.artifact + ' · ' + label;
  function enlarge() {
    const src = image ?? (view === 'detail' ? detail : full).current?.toDataURL();
    if (src) onZoom({src, label: description, locator: row.locator ?? `第 ${row.page} 页 · 图 ${row.item}`});
  }
  return <div className="folio-mat">
    {image ? <img src={image} alt={description} /> : row.regions && desktop && !error ? <>
      <canvas ref={detail} hidden={view !== 'detail'} aria-label={description} />
      <canvas ref={full} hidden={view !== 'whole'} aria-label={description} /></>
      : <span className="atlas-source">{error || '此条目的图像可从原页证据查看。'}</span>}
    {(image || ready) && <button className="folio-zoom" type="button" aria-label={'放大'+description} onClick={enlarge}>放大</button>}
  </div>;
}

export function MotifAtlas({ scope, onEvidence, onAsk }: {
  scope: string[]; onEvidence: (id: string) => void; onAsk: (q: string, id: string) => void;
}) {
  const [rows, setRows] = useState<MotifRow[]>([]);
  const [view, setView] = useState<View>('detail');
  const [sheet, setSheet] = useState(0);
  const [zoom, setZoom] = useState<Zoom | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => { if (zoom) dialog.current?.showModal(); }, [zoom]);
  const [selected, select] = useState('');
  const [activeId, focus] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const scopeKey = JSON.stringify(scope);
  useEffect(() => {
    let active = true;
    setLoading(true); setError(''); setRows([]); setSheet(0);
    void call<MotifRow[]>('published_motifs', { corpusIds: JSON.parse(scopeKey) }).then(value => {
      if (active) setRows(value);
    }).catch(e => { if (active) setError(errorText(e)); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [scopeKey]);
  const motifs = useMemo(() => catalog(rows), [rows]);
  const motif = motifs.find(m => m.id === selected) ?? motifs[0];
  const groups = useMemo(() => specimens(rows, motif?.links ?? []), [rows, motif]);
  const group = groups.find(g => g.some(r => r.id === activeId)) ?? groups[0];
  const edge = group?.find(r => r.id === activeId) ?? group?.[0];
  const lastSheet = Math.max(0, Math.ceil(groups.length/2)-1);
  const currentSheet = Math.min(sheet,lastSheet);
  const network = useRef<HTMLDivElement>(null);
  const disposeNetwork = useRef<(()=>void)|undefined>(undefined);
  useEffect(() => {
    if (network.current && groups.length) disposeNetwork.current = drawNetwork(network.current, groups, edge?.id ?? '', focus);
    else { disposeNetwork.current?.(); disposeNetwork.current = undefined; }
  }, [groups, edge?.id]);
  useEffect(() => () => disposeNetwork.current?.(), []);
  return <section className="surface atlas folio"><div className="section-heading"><h2>纹样图录</h2>
    {motif && <select aria-label="选择纹样" value={motif.id} onChange={e => { select(e.target.value); focus(''); setSheet(0); }}>
      {motifs.map(m => <option key={m.id} value={m.id}>{m.name} · {m.source}</option>)}</select>}</div>
    {error ? <p role="alert">{error}</p> : loading ? <p role="status">正在读取纹样…</p> : !motif ? <p>所选资料中尚无已发布且经确认的纹样关系。</p> :
      <><header className="folio-head"><div><p className="folio-sub">{motif.source}</p><h3 className="folio-title">{motif.name}</h3></div>
        <button type="button" className="button subtle" onClick={() => onAsk(motifQuestion(motif.name), motif.id)}>查询器物与出处</button></header>
        <div className="folio-controls"><h2>图版对读</h2><div className="switch" aria-label="图版视图">
          <button type="button" aria-pressed={view === 'detail'} onClick={() => setView('detail')}>纹样局部</button>
          <button type="button" aria-pressed={view === 'whole'} onClick={() => setView('whole')}>器物全图</button></div></div>
        <div className="folio-gallery">{groups.slice(currentSheet*2,currentSheet*2+2).map(g => {
          const row = g.find(r => r.predicate === 'decorated_with' && (r.regions || r.detailUrl))
            ?? g.find(r => r.regions || r.detailUrl) ?? g[0];
          return <figure className="folio-card" key={row.artifactId}><Plate key={row.id} row={row} view={view} onZoom={setZoom} />
            <figcaption><div className="folio-caption"><div><p className="folio-sub">{row.findspot ? row.findspot+'出土 · ' : ''}
              {row.locator ?? `第 ${row.page} 页 · 图 ${row.item}`}</p><h3>{row.artifact}</h3></div>
              <button className="folio-link" type="button" onClick={() => {focus(g[0].id);onEvidence(g[0].evidenceId);}}>查看出处</button></div>
              {row.observation && <p className="folio-note">图像观察 · {row.observation}</p>}</figcaption></figure>;
        })}</div>
        {lastSheet > 0 && <div className="folio-controls"><button className="folio-link" type="button" disabled={currentSheet === 0} onClick={() => setSheet(currentSheet-1)}>上一组</button>
          <span>{currentSheet+1} / {lastSheet+1}</span><button className="folio-link" type="button" disabled={currentSheet === lastSheet} onClick={() => setSheet(currentSheet+1)}>下一组</button></div>}
        <dialog ref={dialog} aria-label={zoom?.label} onClose={() => setZoom(null)}>{zoom && <>
          <div className="folio-bar"><strong>{zoom.label}</strong><button type="button" className="folio-link" onClick={() => dialog.current?.close()}>关闭</button></div>
          <img src={zoom.src} alt={zoom.label} /><p className="folio-sub">{zoom.locator}</p></>}</dialog>
        <h3 className="atlas-graph-heading">知识图谱</h3>
        {groups.length > 6 && <small>当前显示选中器物的关系，全部器物见下方列表。</small>}
        <div className="space-graph" ref={network} />
        <div className="atlas-paths">{groups.map(g => <article key={g[0].artifactId} className="atlas-path">
          <div className="atlas-owner"><small>器物 · {g[0].locator ?? `第 ${g[0].page} 页图注 ${g[0].item}`}</small><strong>{g[0].artifact}</strong></div>
          <div className="atlas-edges">{g.map(r => <button key={r.id} type="button" aria-pressed={edge?.id === r.id}
            onClick={() => focus(r.id)}><span>{relations[r.predicate]} →</span><strong>{r.object}</strong>
              {r.qualifiers.map((q,i) => <small key={i}>{q.text}</small>)}</button>)}</div>
        </article>)}</div>
        {edge && <aside className="atlas-proof"><h4>{edge.artifact} · {relations[edge.predicate]} · {edge.object}</h4>
          <blockquote>{edge.quote}</blockquote><button className="button subtle" type="button" onClick={() => onEvidence(edge.evidenceId)}>
            查看来源 · {edge.proofLocator ?? edge.locator ?? `第 ${edge.page} 页图注 ${edge.item}`}</button>
          </aside>}</>}
  </section>;
}
