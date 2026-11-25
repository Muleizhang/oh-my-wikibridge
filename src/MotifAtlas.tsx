import { drawNetwork } from './motif-network.js';
import { useEffect, useMemo, useRef, useState } from 'react';
import { call, desktop, errorText } from './api';
import { catalog, motifQuestion, relations, specimens, type Box, type MotifRow } from './motif-data';

function Plate({ row }: { row: MotifRow }) {
  const full = useRef<HTMLCanvasElement>(null);
  const detail = useRef<HTMLCanvasElement>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    if (!row.regions || !desktop) return;
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
    })().catch(e => { if (active) setError(errorText(e)); }).finally(() => { const release = close; close = undefined; void release?.(); });
    return () => { active = false; const release = close; close = undefined; void release?.(); };
  }, [row]);
  if (row.imageUrl) return <div className="atlas-plates">
    <figure><img src={row.detailUrl} alt={row.object + '局部'} /><figcaption>{row.detailLabel ?? '纹样局部'}</figcaption></figure>
    <figure><img src={row.imageUrl} alt={row.artifact} /><figcaption>器物全图</figcaption></figure></div>;
  if (!row.regions) return <p className="atlas-source">此条目尚未标注图版区域，可查看下方原页证据。</p>;
  if (error) return <p role="alert">{error}</p>;
  return <div className="atlas-plates"><figure><canvas ref={detail} aria-label="纹样局部" /><figcaption>纹样局部</figcaption></figure>
    <figure><canvas ref={full} aria-label="器物全图" /><figcaption>器物全图</figcaption></figure></div>;
}

export function MotifAtlas({ scope, onEvidence, onAsk }: {
  scope: string[]; onEvidence: (id: string) => void; onAsk: (q: string, id: string) => void;
}) {
  const [rows, setRows] = useState<MotifRow[]>([]);
  const [selected, select] = useState('');
  const [activeId, focus] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const scopeKey = JSON.stringify(scope);
  useEffect(() => {
    let active = true;
    setLoading(true); setError(''); setRows([]);
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
  const imageRow = group?.find(r => r.id === activeId && r.regions) ?? group?.find(r => r.regions) ?? group?.[0];
  const network = useRef<SVGSVGElement>(null);
  useEffect(() => {
    if (network.current && groups.length) drawNetwork(network.current, groups, edge?.id ?? '', focus);
  }, [groups, edge?.id]);
  return <section className="surface atlas"><div className="section-heading"><h2>纹样图录</h2>
    {motif && <select aria-label="选择纹样" value={motif.id} onChange={e => { select(e.target.value); focus(''); }}>
      {motifs.map(m => <option key={m.id} value={m.id}>{m.name} · {m.source}</option>)}</select>}</div>
    {error ? <p role="alert">{error}</p> : loading ? <p role="status">正在读取纹样…</p> : !motif ? <p>所选资料中尚无已发布且经确认的纹样关系。</p> :
      <><header className="atlas-title"><div><p>{motif.source}</p><h3>{motif.name}</h3></div>
        <button type="button" className="button subtle" onClick={() => onAsk(motifQuestion(motif.name), motif.id)}>查询器物与出处</button></header>
        <p className="atlas-caption">{groups.length} 个器物条目 · 选择关系可核对原文</p>
        <div className="atlas-network"><svg ref={network} /></div>
        <div className="atlas-paths">{groups.map(g => <article key={g[0].artifactId} className="atlas-path">
          <div className="atlas-owner"><small>器物 · {g[0].locator ?? `第 ${g[0].page} 页图注 ${g[0].item}`}</small><strong>{g[0].artifact}</strong></div>
          <div className="atlas-edges">{g.map(r => <button key={r.id} type="button" aria-pressed={edge?.id === r.id}
            onClick={() => focus(r.id)}><span>{relations[r.predicate]} →</span><strong>{r.object}</strong>
              {r.qualifiers.map((q,i) => <small key={i}>{q.text}</small>)}</button>)}</div>
        </article>)}</div>
        {edge && <aside className="atlas-proof"><h4>{edge.artifact} · {relations[edge.predicate]} · {edge.object}</h4>
          <blockquote>{edge.quote}</blockquote><button className="button subtle" type="button" onClick={() => onEvidence(edge.evidenceId)}>
            查看来源 · {edge.proofLocator ?? edge.locator ?? `第 ${edge.page} 页图注 ${edge.item}`}</button>
          {imageRow && <Plate key={imageRow.id} row={imageRow} />}</aside>}</>}
  </section>;
}
