import type { SpaceNode } from './spatial-graph.js';
import { SpaceGraph } from './SpaceGraph';
import { PlateEditor } from './PlateEditor';
import type { Regions } from './motif-data';
import { useEffect, useMemo, useState } from 'react';
import { Download, RefreshCw, Search } from 'lucide-react';
import { call, desktop, errorText } from './api';
import { IdentityMatches, sourceLocation, type IdentityReview, type IdentityProposal } from './IdentityMatches';

type Ev = { page: number; engine: string; text: string; span: [number, number]; bbox?: number[] | null };
type Entity = { id: string; label: string; kind: string; description?: string; recordId?: string; evidence: Ev[] };
type Value = { kind: string; id?: string; raw?: string; value?: string | null; lower?: string; upper?: string; unit?: string; approximate?: boolean; normalized?: { lower: string; upper: string; unit: string } };
type Assertion = { id: string; subject: string | null; subjectMention?: Value; recordId: string | null; predicate: string; label: string; object: Value; qualifiers: { role: string; text: string }[]; evidence: Ev[]; issues: string[]; origin: string };
type Record = { id: string; page: number; item: number; label: string; text: string; bbox: number[]; span: [number, number]; issues: string[] };
type Event = { id: string; label: string; recordId: string | null; participants: { role: string; entityId: string }[]; unresolvedArguments?: { role: string; text: string }[]; time: Value | null; evidence: Ev[]; issues: string[] };
type Proposal = { id: string; left: string; right: string; nameMatch: boolean; typeAgreement: boolean; cosineSimilarity: number; rerankerLogit: number };
type Review = { id: string; targetKind: string; targetId: string; decision: string; reviewer: string; note: string; createdAt: string };
type EvalRow = { truePositive: number; falsePositive: number; falseNegative: number; precision: number; recall: number; precisionLower95: number };
type Data = { plateRegions?: { [id: string]: Regions }; identityReview?: IdentityReview; version: string; runId: string; summary: { pages: number; records: number; quantities: number; assertions: number; events: number; unresolvedMentions: number }; records: Record[]; entities: Entity[]; assertions: Assertion[]; events: Event[]; identityProposals: Proposal[]; relationProposals: { id: string; rawPredicate: string; candidateCount: number; examples: { evidence: Ev }[] }[]; ocrDisagreements: { kind: string; page: number; old: unknown; new: unknown }[]; publication: { automaticAcceptance: boolean; reasons: string[] }; evaluation?: { quantity: { [key: string]: EvalRow } }; reviews?: Review[]; documents: { page: number; engine: string; text: string; imageSize: number[] }[] };
type Selection = { kind: 'assertion' | 'identity' | 'record' | 'event' | 'source'; id: string; title: string; evidence: Ev[] };

const issueLabels: { [key: string]: string } = {
  unresolved_subject: '所属对象未确定', unresolved_object: '关系对象未确定', relation_definition_pending: '关系定义待确认', semantic_support_pending: '原文支持情况待复核',
  quantity_dimension_mismatch: '数值单位与属性不匹配', quantity_owner_not_artifact: '尺寸所属对象类型有误', missing_evidence: '缺少证据', conflicting_values: '存在不同数值',
  ocr_numeric_disagreement: '两版 OCR 数值不同', multiple_places_in_one_field: '同一字段有多个地点', field_value_type_conflict: '字段与值类型不一致',
  relation_subject_type: '主体类型待确认', relation_object_type: '客体类型待确认', event_participant_identity_pending: '事件参与对象尚未消歧',
};
const blocked = ['unresolved_subject', 'unresolved_object', 'quantity_dimension_mismatch', 'quantity_owner_not_artifact', 'missing_evidence', 'relation_subject_type', 'relation_object_type', 'field_value_type_conflict', 'relation_definition_pending'];


export function ReliableGraph({ token, onUnlock }: { token?: string; onUnlock: () => void }) {
  const [data, setData] = useState<Data>();
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState(new URLSearchParams(location.search).get('q') ?? '');
  const [tab, setTab] = useState<'records' | 'assertions' | 'events' | 'identity' | 'definitions' | 'evaluation'>(new URLSearchParams(location.search).get('tab') === 'identity' ? 'identity' : 'records');
  const [minimumHeight, setMinimumHeight] = useState('');
  const [onlyAccepted, setOnlyAccepted] = useState(false);
  const [pageIndex, setPageIndex] = useState(0);
  const [selection, setSelection] = useState<Selection>();
  const [image, setImage] = useState('');
  const [reviews, setReviews] = useState<Review[]>([]);
  const [reviewer, setReviewer] = useState('');
  const [note, setNote] = useState('');
  const [notice, setNotice] = useState('');
  async function refresh() {
    if (desktop && !token) { setData(undefined); return; }
    setBusy(true); setError('');
    try {
      const result = desktop ? await call<Data>('local_pipeline_graph', { token, version: 'typed-kg-v2' }) : await fetch('/data/local-kg/graph.json', { cache: 'no-store' }).then(r => {
        if (!r.ok) throw new Error('尚未生成新版结果，请运行 npm run pipeline:reliable。');
        return r.json() as Promise<Data>;
      });
      setData(result);
      const saved = desktop ? result.reviews ?? [] : JSON.parse(localStorage.getItem('kg-reviews:' + result.runId) ?? '[]') as Review[];
      setReviews(saved); setPageIndex(0);
    } catch (e) { setError(errorText(e)); }
    finally { setBusy(false); }
  }
  useEffect(() => { void refresh(); }, [token]);
  useEffect(() => { setPageIndex(0); }, [tab, query, minimumHeight, onlyAccepted]);
  useEffect(() => {
    setImage('');
    const ev = selection?.evidence[0];
    if (!ev) return;
    if (!desktop) { setImage(`/data/local-kg/images/v1-p${String(ev.page).padStart(4, '0')}.png`); return; }
    let active = true, url: string | undefined;
    void call<ArrayBuffer>('local_pipeline_image', { token, page: ev.page }).then(bytes => {
      if (active) { url = URL.createObjectURL(new Blob([bytes], { type: 'image/png' })); setImage(url); }
    }).catch(e => { if (active) setError(errorText(e)); });
    return () => { active = false; if (url) URL.revokeObjectURL(url); };
  }, [selection, token]);
  const entities = useMemo(() => new Map(data?.entities.map(e => [e.id, e])), [data]);
  const events = useMemo(() => new Map(data?.events.map(e => [e.id, e])), [data]);
  const decisions = useMemo(() => {
    const values = new Map<string, Review>();
    for (const r of reviews) values.set(r.targetKind + ':' + r.targetId, r);
    return values;
  }, [reviews]);
  const canonical = useMemo(() => {
    const parents = new Map(data?.entities.map(e => [e.id, e.id]));
    for (const concept of data?.identityReview?.concepts ?? []) {
      if (concept.proposalIds.some(id => decisions.get('identity:' + id)?.decision === 'reject')) continue;
      parents.set(concept.id, concept.id);
      for (const id of concept.memberIds) parents.set(id, concept.id);
    }
    const root = (id: string): string => { while (parents.has(id) && parents.get(id) !== id) id = parents.get(id)!; return id; };
    for (const p of data?.identityProposals ?? []) {
      if (p.typeAgreement && decisions.get('identity:' + p.id)?.decision === 'accept') {
        const [left, right] = [root(p.left), root(p.right)].sort(); parents.set(right, left);
      }
    }
    return new Map([...parents.keys()].map(id => [id, root(id)]));
  }, [data, decisions]);
  const accepted = (id: string) => decisions.get('assertion:' + id)?.decision === 'accept';
  const entityLabel = (id: string | null | undefined) => id ? entities.get(id)?.label ?? data?.identityReview?.concepts.find(c => c.id === id)?.name ?? '对象未确定' : '对象未确定';
  const valueLabel = (value: Value): string => {
    if (value.kind === 'quantity') return (value.approximate ? '约 ' : '') + (value.value ?? `${value.lower}–${value.upper}`) + ' ' + value.unit;
    if (value.kind === 'entity') return entityLabel(value.id);
    if (value.kind === 'event') return events.get(value.id ?? '')?.label ?? '事件';
    return value.raw ?? value.value ?? '待确定';
  };
  const search = (...parts: (string | undefined)[]) => !query || parts.some(s => s?.toLowerCase().includes(query.toLowerCase()));
  const recordRows = data?.records.filter(r => search(r.label, r.text) && (!onlyAccepted || data.assertions.some(a => a.recordId === r.id && accepted(a.id))) && (!minimumHeight || data.assertions.some(a => a.recordId === r.id && a.predicate === 'height' && a.object.kind === 'quantity' && Number(a.object.normalized?.lower) > Number(minimumHeight)))) ?? [];
  const assertionRows = data?.assertions.filter(a => search(entityLabel(a.subject), a.subjectMention?.raw, a.label, valueLabel(a.object)) && (!onlyAccepted || accepted(a.id))) ?? [];
  const shownNodes = new Set<string>();
  const graphEdges = assertionRows.filter(a => {
    if (!a.subject || a.object.kind !== 'entity' || !a.object.id) return false;
    const left = canonical.get(a.subject)!, right = canonical.get(a.object.id)!;
    if (left === right || new Set([...shownNodes, left, right]).size > 14) return false;
    shownNodes.add(left); shownNodes.add(right); return true;
  }).slice(0, 22);
  const spatialEdges=graphEdges.map(a=>({id:a.id,from:canonical.get(a.subject!)!,to:canonical.get(a.object.id!)!,label:a.label}));
  const spatialNodes=[...new Set(spatialEdges.flatMap(e=>[e.from,e.to]))]
    .map(id=>{
      const type=entities.get(id)?.kind ?? data?.identityReview?.concepts.find(c=>c.id===id)?.kind;
      const kind: SpaceNode['kind']=type==='material'||type==='period'||type==='motif'||type==='artifact'?type:'concept';
      return {id,label:entityLabel(id),kind};
    });
  const eventRows = data?.events.filter(e => search(e.label, e.time?.raw, ...e.evidence.map(v => v.text))) ?? [];
  const identityRows = data?.identityProposals.filter(p => search(entityLabel(p.left), entityLabel(p.right))) ?? [];
  const definitionRows = data?.relationProposals.filter(p => search(p.rawPredicate)) ?? [];
  const total = { records: recordRows.length, assertions: assertionRows.length, events: eventRows.length, identity: identityRows.length, definitions: definitionRows.length, evaluation: 0 }[tab];
  function showAssertion(a: Assertion) { setSelection({ kind: 'assertion', id: a.id, title: `${entityLabel(a.subject)} · ${a.label} · ${valueLabel(a.object)}`, evidence: a.evidence }); setNote(''); }
  function showRecord(r: Record) { setSelection({ kind: 'record', id: r.id, title: r.label, evidence: [{ page: r.page, engine: 'ppstructure', text: r.text, span: r.span, bbox: r.bbox }] }); setNote(''); }
  function showIdentity(p: IdentityProposal) { setSelection({ kind: 'identity', id: p.id, title: `${entityLabel(p.left)} / ${entityLabel(p.right)}`, evidence: [...entities.get(p.left)!.evidence, ...entities.get(p.right)!.evidence] }); setNote(''); }
  const activeAssertion = data?.assertions.find(a => a.id === selection?.id);
  const activeProposal = data?.identityProposals.find(p => p.id === selection?.id);
  const cannotAccept = Boolean(activeAssertion?.issues.some(i => blocked.includes(i)) || activeProposal && !activeProposal.typeAgreement);
  async function review(decision: string) {
    if (!data || !selection || !['assertion', 'identity'].includes(selection.kind)) return;
    if (!reviewer.trim() || !note.trim()) { setNotice('请填写复核者与依据。'); return; }
    setBusy(true); setNotice('');
    try {
      if (decision === 'accept' && cannotAccept) throw new Error('对象或类型尚未解决，不能直接确认。');
      const args = { token, runId: data.runId, targetKind: selection.kind, targetId: selection.id, decision, reviewer, note };
      if (desktop) { await call('review_pipeline_item', args); await refresh(); }
      else {
        const next = [...reviews, { id: crypto.randomUUID(), targetKind: selection.kind, targetId: selection.id, decision, reviewer, note, createdAt: new Date().toISOString() }];
        localStorage.setItem('kg-reviews:' + data.runId, JSON.stringify(next)); setReviews(next);
      }
      setNotice(decision === 'revoke' ? '已撤销上次决定，历史记录保留。' : '复核记录已保存。');
    } catch (e) { setNotice(errorText(e)); }
    finally { setBusy(false); }
  }
  function exportReviews() {
    if (!data) return;
    const blob = new Blob([JSON.stringify({ runId: data.runId, authority: 'manual_review_log_not_independent_gold', reviews }, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob), a = document.createElement('a'); a.href = url; a.download = 'kg-reviews.json'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  const activeEv = selection?.evidence[0];
  const source = data?.documents.find(d => d.page === activeEv?.page && d.engine === activeEv.engine);
  const latestReview = selection && decisions.get(selection.kind + ':' + selection.id);
  return <section className="surface explore-surface typed-kg">
    <div className="section-heading"><div><h2>器物条目与知识陈述</h2><p>{data ? `${data.summary.pages} 页语料 · ` : ''}尺寸作为属性值，采集年份归入事件，无法确定的对象保留待解。</p></div><button className="button subtle" disabled={busy} onClick={() => void refresh()}><RefreshCw size={15} />刷新</button></div>
    {desktop && !token && <p>请解锁管理员以查看尚未发布的资料。<button className="button subtle" onClick={onUnlock}>解锁管理员</button></p>}
    {error && <p className="error" role="alert">{error}</p>}
    {!data ? <p>{busy ? '正在读取…' : '暂无结果。'}</p> : <>
      <div className="kg-stats">{[[data.summary.records, '器物条目'], [data.summary.quantities, '数值属性'], [data.summary.events, '事件候选'], [data.summary.unresolvedMentions, '待解提及'], [data.assertions.filter(a => accepted(a.id)).length, '人工确认陈述']].map(([v, name]) => <div key={name}><strong>{v.toLocaleString()}</strong><span>{name}</span></div>)}</div>
      <p className="typed-notice">自动验收尚未开启：缺少独立人工评测。模型候选、来源图像和人工复核决定分别保存。</p>
      <div className="kg-controls"><Search size={17} /><input aria-label="搜索条目与陈述" placeholder="搜索器物、属性、事件，如人面鱼纹彩陶盆" value={query} onChange={e => setQuery(e.target.value)} /><button className="button subtle" onClick={exportReviews}><Download size={14} />导出复核记录</button></div>
      <div className="kg-tabs">{([['records', '器物与属性'], ['assertions', '陈述与关系'], ['events', '事件'], ['identity', '实体匹配'], ['definitions', '新关系待定义'], ['evaluation', '评测与质量']] as const).map(([id, text]) => <button className={`button ${tab === id ? 'primary' : 'subtle'}`} key={id} onClick={() => setTab(id)}>{text}</button>)}</div>
      {['records', 'assertions'].includes(tab) && <div className="typed-filters"><label><input type="checkbox" checked={onlyAccepted} onChange={e => setOnlyAccepted(e.target.checked)} />只看有人工确认的结果</label>{tab === 'records' && <label>高度大于 <input aria-label="最低高度厘米" type="number" min="0" step="0.1" value={minimumHeight} onChange={e => setMinimumHeight(e.target.value)} /> 厘米</label>}</div>}
      {tab === 'assertions' && graphEdges.length > 0 && <SpaceGraph nodes={spatialNodes} edges={spatialEdges}
        picked={selection?.id ?? ''} onEdge={id=>{const a=graphEdges.find(a=>a.id===id); if(a) showAssertion(a);}}
        onNode={id=>setQuery(entityLabel(id))} />}
      {tab === 'records' && recordRows.slice(pageIndex * 12, pageIndex * 12 + 12).map(r => <article className="typed-record" key={r.id}><div className="section-heading"><div><small>PDF 第 {r.page} 页 · 图注 {r.item}</small><h3>{r.label}</h3><span className="muted">书内条目身份；跨条目是否同一器物尚待复核</span></div><button className="button subtle" onClick={() => showRecord(r)}>查看条目原图</button></div><div className="typed-attributes">{data.assertions.filter(a => a.recordId === r.id && a.object.kind === 'quantity' && (!onlyAccepted || accepted(a.id))).map(a => <button key={a.id} className="typed-attribute" onClick={() => showAssertion(a)}><span>{a.label}</span><strong>{valueLabel(a.object)}</strong><small>{accepted(a.id) ? '已人工确认' : a.issues.length ? '需检查' : '机器候选'}</small></button>)}</div><div className="typed-record-relations">{data.assertions.filter(a => a.recordId === r.id && a.object.kind !== 'quantity' && (!onlyAccepted || accepted(a.id))).map(a => <button key={a.id} onClick={() => showAssertion(a)}>{a.label}：{a.object.kind === 'event' ? events.get(a.object.id!)?.participants.filter(p => p.role !== 'object').map(p => entityLabel(p.entityId)).join('、') : valueLabel(a.object)}</button>)}</div>{r.issues.length > 0 && <p className="kg-qualifiers">条目边界或对象类型待检查。</p>}</article>)}
      {tab === 'assertions' && assertionRows.slice(pageIndex * 12, pageIndex * 12 + 12).map(a => <article className="typed-claim" key={a.id}><button className="typed-claim-title" onClick={() => showAssertion(a)}><strong>{a.subject ? entityLabel(a.subject) : a.subjectMention?.raw ?? '主体待确定'}</strong><span>{a.label}</span><strong>{valueLabel(a.object)}</strong></button><p className="muted">{a.object.kind === 'quantity' ? '属性值' : a.object.kind === 'event' ? '事件陈述' : '关系陈述'} · PDF {a.evidence.map(e => e.page).join('、')} 页 · {accepted(a.id) ? '已人工确认' : '待复核'}</p>{a.qualifiers.length > 0 && <p>{a.qualifiers.map(q => q.role + '：' + q.text).join('；')}</p>}{a.issues.length > 0 && <p className="kg-qualifiers">{a.issues.map(i => issueLabels[i] ?? i).join('；')}</p>}</article>)}
      {tab === 'events' && eventRows.slice(pageIndex * 12, pageIndex * 12 + 12).map(e => <article className="typed-record" key={e.id}><h3>{e.label}{e.time && ' · ' + valueLabel(e.time)}</h3><p>{e.participants.map(p => `${p.role === 'object' ? '对象' : p.role === 'location' ? '地点' : '持有方'}：${entityLabel(p.entityId)}`).join('；')}</p>{e.unresolvedArguments?.length ? <p>未完成身份绑定的参数：{e.unresolvedArguments.map(a => a.text).join('；')}</p> : null}<blockquote>{e.evidence[0].text}</blockquote><button className="button subtle" onClick={() => setSelection({ kind: 'event', id: e.id, title: e.label, evidence: e.evidence })}>查看事件证据</button></article>)}
      {tab === 'identity' && <IdentityMatches review={data.identityReview} proposals={data.identityProposals} query={query}
        decision={id => decisions.get('identity:' + id)?.decision} onCompare={showIdentity}
        onSource={source => { setSelection({ kind: 'source', id: source.entityId, title: `${source.normalizedName} · ${sourceLocation(source)}`, evidence: source.evidence }); setNote(''); }} />}
      {tab === 'definitions' && definitionRows.slice(pageIndex * 12, pageIndex * 12 + 12).map(p => <article className="typed-claim" key={p.id}><h3>{p.rawPredicate}</h3><p>{p.candidateCount} 条候选 · 关系定义、方向与适用对象待确认</p>{p.examples.slice(0, 2).map((ex, i) => <blockquote key={i}>PDF 第 {ex.evidence.page} 页：{ex.evidence.text}</blockquote>)}</article>)}
      {tab === 'evaluation' && <div className="typed-quality"><h3>尺寸与所属器物的开发诊断</h3><p>18 条参考来自助手对扫描图的核读，属于已查看的开发样本，不是独立专家金标准，也不能代表整本书的准确率。</p><table><thead><tr><th>同一条目解析器</th><th>正确</th><th>错误</th><th>漏抽</th></tr></thead><tbody>{Object.entries(data.evaluation?.quantity ?? {}).map(([name, score]) => <tr key={name}><td>{name.startsWith('ppstructure') ? '新版 OCR' : '旧版 OCR'}</td><td>{score.truePositive}</td><td>{score.falsePositive}</td><td>{score.falseNegative}</td></tr>)}</tbody></table><p>匹配要求：页码、条目编号、属性、数值、单位和约数标记同时正确。</p><h3>自动验收门槛</h3><ul>{data.publication.reasons.map(r => <li key={r}>{r}</li>)}</ul><p>跨记录身份、正文关系及开放关系尚无独立标注成绩。关系和身份的质量需要独立标注评测。</p><h3>OCR 差异保留</h3><p>{data.ocrDisagreements.length} 处名称或数值差异。旧 OCR 保留，新版识别不自动视为人工纠错。</p>{data.ocrDisagreements.slice(0, 15).map((d, i) => <p key={i}>第 {d.page} 页：{typeof d.old === 'string' ? d.old : JSON.stringify(d.old)} → {typeof d.new === 'string' ? d.new : JSON.stringify(d.new)}</p>)}</div>}
      {tab !== 'evaluation' && tab !== 'identity' && <div className="kg-pagination"><span>{total} 项 · 第 {pageIndex + 1} 页</span><button className="button subtle" disabled={pageIndex === 0} onClick={() => setPageIndex(pageIndex - 1)}>上一页</button><button className="button subtle" disabled={(pageIndex + 1) * 12 >= total} onClick={() => setPageIndex(pageIndex + 1)}>下一页</button></div>}
      {selection && <aside className="kg-evidence typed-evidence" aria-label="条目证据与复核"><div className="section-heading"><h3>{selection.title}</h3><button className="button subtle" onClick={() => { setSelection(undefined); setNotice(''); }}>关闭</button></div>{selection.evidence.map((ev, i) => <blockquote key={i}><small>PDF 第 {ev.page} 页 · {ev.engine === 'ppstructure' ? '新版 OCR' : '旧版 OCR'}</small><p>{ev.text}</p>{selection.evidence.length > 1 && <button className="button subtle" disabled={i === 0} onClick={() => setSelection({ ...selection, evidence: [ev, ...selection.evidence.filter((_, index) => index !== i)] })}>{i === 0 ? '当前原图区域' : '查看该处原图'}</button>}</blockquote>)}
        {selection.kind === 'identity' && activeProposal && <p>{entities.get(activeProposal.left)?.description}<br />{entities.get(activeProposal.right)?.description}</p>}
        {['assertion', 'identity'].includes(selection.kind) && <div className="typed-review"><h4>人工复核</h4><p className="muted">{desktop ? '决定写入本地数据库，保留历史并支持撤销。' : '决定保存在当前浏览器，可导出复核记录备份。'}</p>{latestReview && <p>最新决定：{latestReview.decision === 'accept' ? '确认' : latestReview.decision === 'reject' ? '否定' : '已撤销'} · {latestReview.reviewer}<br />{latestReview.note}</p>}<input aria-label="复核者" placeholder="复核者" value={reviewer} onChange={e => setReviewer(e.target.value)} /><textarea aria-label="复核依据" placeholder="根据原图和上下文填写依据" value={note} onChange={e => setNote(e.target.value)} /><div className="kg-tabs"><button className="button primary" disabled={busy || cannotAccept} onClick={() => void review('accept')}>确认</button><button className="button subtle" disabled={busy} onClick={() => void review('reject')}>否定</button><button className="button subtle" disabled={busy || !latestReview} onClick={() => void review('revoke')}>撤销决定</button></div>{cannotAccept && <p className="kg-qualifiers">对象身份或值类型尚未解决，需要先修订，不能直接确认。</p>}{notice && <p role="status">{notice}</p>}</div>}
        {image && source && <div className="typed-page-image"><img src={image} alt={`PDF 第${activeEv!.page}页原图`} /><svg viewBox={`0 0 ${source.imageSize.join(' ')}`} aria-label="证据区域">{activeEv?.bbox && <rect x={activeEv.bbox[0]} y={activeEv.bbox[1]} width={activeEv.bbox[2] - activeEv.bbox[0]} height={activeEv.bbox[3] - activeEv.bbox[1]} fill="#ffcc3333" stroke="#d78b18" strokeWidth="7" />}</svg></div>}{image && token && desktop && activeAssertion?.predicate === 'decorated_with' && activeEv === selection.evidence[0] && activeEv?.page === activeAssertion.evidence[0]?.page &&
          <PlateEditor key={activeAssertion.id} image={image} token={token} runId={data.runId} assertionId={activeAssertion.id} initial={data.plateRegions?.[activeAssertion.id]} />}
        <details><summary>完整 OCR 文本</summary><pre>{source?.text}</pre></details>
      </aside>}
    </>}
  </section>;
}
