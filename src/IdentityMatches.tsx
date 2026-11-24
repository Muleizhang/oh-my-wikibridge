import { useEffect, useMemo, useState, type ReactNode } from 'react';

type Evidence = { page: number; engine: string; text: string; span: [number, number]; bbox?: number[] | null };
export type IdentitySource = { entityId: string; rawName: string; normalizedName: string; kind: string; conceptId?: string; page: number; item: number | null; recordId: string | null; context: string; evidence: Evidence[] };
export type IdentityProposal = { id: string; left: string; right: string; rerankerLogit: number; typeAgreement: boolean };
type NameGroup = { id: string; name: string; kind: string; conceptId?: string | null; memberIds: string[]; proposalIds: string[]; variants: string[]; pages: number[] };
export type IdentityReview = {
  sources: { [id: string]: IdentitySource }; groups: NameGroup[]; concepts: NameGroup[];
  differentNameProposalIds: string[]; typeConflictProposalIds: string[];
  summary: { nameGroups: number; groupedOccurrences: number; sameNamePairs: number; differentNamePairs: number; typeConflictPairs: number; totalPairs: number; concepts: number; conceptOccurrences: number; instanceNameGroups: number };
};
type Props = {
  review?: IdentityReview; proposals: IdentityProposal[]; query: string;
  decision: (id: string) => string | undefined;
  onCompare: (proposal: IdentityProposal) => void;
  onSource: (source: IdentitySource) => void;
};
const types: { [kind: string]: string } = { artifact: '器物记录', motif: '纹样', technique: '工艺', material: '材质', period: '时代', place: '地点', organization: '机构', culture: '文化' };
const status = (value?: string) => value === 'accept' ? '已确认同一对象' : value === 'reject' ? '已否定匹配' : value === 'revoke' ? '已撤销，待复核' : '待复核';
const pairKey = (left: string, right: string) => [left, right].sort().join(':');
const searchKey = (text: string) => text.normalize('NFKC').trim().replace(/\s+/g, ' ').replace(/(?<=[\u3400-\u9fff])\s+(?=[\u3400-\u9fff])/g, '').toLowerCase();
export const sourceLocation = (source: IdentitySource) => `PDF 第 ${source.page} 页 · ${source.item === null ? `正文位置 ${source.evidence[0].span[0] + 1}` : `图注 ${source.item}`}`;

function SourceCard({ source, onSource, children }: { source: IdentitySource; onSource: Props['onSource']; children?: ReactNode }) {
  return <div className="identity-source" data-entity-id={source.entityId}>
    <div className="identity-source-heading"><strong>{sourceLocation(source)}</strong><span>{types[source.kind] ?? source.kind}</span></div>
    <p className="identity-original">原文名称：<q>{source.rawName}</q></p>
    <p className="identity-context">{source.context.length > 230 ? source.context.slice(0, 230) + '…' : source.context}</p>
    <div className="identity-source-actions"><button className="button subtle" onClick={() => onSource(source)}>查看原图</button>{children}</div>
  </div>;
}

function GroupCard({ group, sources, pairs, decision, onCompare, onSource }: {
  group: NameGroup; sources: IdentityReview['sources']; pairs: Map<string, IdentityProposal>;
  decision: Props['decision']; onCompare: Props['onCompare']; onSource: Props['onSource'];
}) {
  const [reference, setReference] = useState(group.memberIds[0]);
  const [expanded, setExpanded] = useState(false);
  const confirmed = group.proposalIds.filter(id => decision(id) === 'accept').length;
  const rejected = group.proposalIds.filter(id => decision(id) === 'reject').length;
  return <article className="typed-claim identity-group" data-group-name={group.name}>
    <div className="identity-group-heading"><div><span className="identity-type">{types[group.kind] ?? group.kind}</span><h3>{group.name}</h3></div><div className="identity-occurrences"><strong>{group.memberIds.length}</strong><span>处来源</span></div></div>
    <p className="identity-group-meta">分布于 PDF 第 {group.pages.join('、')} 页{group.proposalIds.length > 0 && ` · ${group.proposalIds.length} 对同名候选已收起`}</p>
    <p className="identity-group-policy">{group.conceptId ? rejected > 0 ? '存在同名异义的复核意见，关系图中暂不统一这些来源。' : '同名、同类型的来源已归入一个概念节点；原文与出处分别保留。' : group.kind === 'artifact' ? '同名器物可能是不同实物，需比较各自图注。' : '按名称和类型整理来源；是否指同一对象仍需结合上下文确认。'}{confirmed + rejected > 0 && ` 已确认 ${confirmed} 对，已否定 ${rejected} 对。`}</p>
    {(group.variants.length > 1 || group.variants[0] !== group.name) && <p className="identity-variants">格式统一前：{group.variants.map(v => <q key={v}>{v}</q>)}</p>}
    {!expanded && <div className="identity-source-grid">{group.memberIds.slice(0, 2).map(id => <SourceCard key={id} source={sources[id]} onSource={onSource} />)}</div>}
    <button className="button subtle identity-expand" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>{expanded ? '收起来源' : `展开 ${group.memberIds.length} 处来源${group.conceptId ? '' : '并比较'}`}</button>
    {expanded && <div className="identity-expanded">
      <label className="identity-reference">选择比较基准<select aria-label={`${group.name}的比较基准`} value={reference} onChange={e => setReference(e.target.value)}>{group.memberIds.map(id => <option key={id} value={id}>{sourceLocation(sources[id])}</option>)}</select></label>
      <p className="muted">{group.conceptId ? '若发现同名异义，可打开一对来源并否定匹配，关系图会暂停本概念的自动归组。撤销该否定后恢复。' : '选择一处来源作为基准，再逐项比较。确认或否定只作用于选中的一对来源。'}</p>
      <div className="identity-source-grid">{group.memberIds.map(id => {
        const pair = pairs.get(pairKey(reference, id));
        return <SourceCard key={id} source={sources[id]} onSource={onSource}>{id === reference ? <span className="identity-reference-badge">当前比较基准</span> : <><button className="button primary" disabled={!pair} onClick={() => pair && onCompare(pair)}>{group.conceptId ? '检查同名歧义' : '与基准比较'}</button><small>{pair ? status(decision(pair.id)) : '尚无匹配候选'}</small></>}</SourceCard>;
      })}</div>
    </div>}
  </article>;
}

export function IdentityMatches({ review, proposals, query, decision, onCompare, onSource }: Props) {
  const [mode, setMode] = useState<'concepts' | 'names' | 'different' | 'conflicts'>(() => {
    const value = new URLSearchParams(location.search).get('matches');
    return value === 'names' || value === 'different' || value === 'conflicts' ? value : 'concepts';
  });
  const [page, setPage] = useState(0);
  useEffect(() => { setPage(0); }, [query, mode]);
  const byId = useMemo(() => new Map(proposals.map(p => [p.id, p])), [proposals]);
  const byPair = useMemo(() => new Map(proposals.map(p => [pairKey(p.left, p.right), p])), [proposals]);
  if (!review) return <p className="typed-notice">尚未整理名称分组，请运行新版流水线后刷新。</p>;
  const key = searchKey(query);
  const matches = (source: IdentitySource) => !key || [source.rawName, source.normalizedName, source.context, sourceLocation(source)].some(text => searchKey(text).includes(key));
  const grouped = mode === 'concepts' || mode === 'names';
  const groupItems = mode === 'concepts' ? review.concepts : review.groups.filter(g => !g.conceptId);
  const nameRank = (group: NameGroup) => !key ? 0 : searchKey(group.name) === key ? 2 : searchKey(group.name).includes(key) ? 1 : 0;
  const groups = groupItems.filter(g => !key || searchKey(g.name).includes(key) || g.memberIds.some(id => matches(review.sources[id])))
    .sort((a, b) => nameRank(b) - nameRank(a));
  const pairIds = mode === 'conflicts' ? review.typeConflictProposalIds : review.differentNameProposalIds;
  const pairs = pairIds.map(id => byId.get(id)!).filter(p => p && (matches(review.sources[p.left]) || matches(review.sources[p.right])));
  const total = grouped ? groups.length : pairs.length;
  const size = grouped ? 6 : 8;
  const currentPage = Math.min(page, Math.max(0, Math.ceil(total / size) - 1));
  return <div className="identity-workspace">
    <div className="identity-intro"><h3>同名概念统一，器物实例独立</h3><p>{review.summary.conceptOccurrences} 处纹样、时代、工艺等提及，按名称与类型整理为 {review.summary.concepts} 个概念。展开查看各次出处；具体器物仍单独保留。</p><small>{review.summary.sameNamePairs} 对重复名称候选已收起，名称差异和类型问题分别核对。</small></div>
    <div className="identity-modes" aria-label="匹配候选分类">{([
      ['concepts', '概念词表', review.summary.concepts],
      ['names', '同名对象', review.summary.instanceNameGroups],
      ['different', '异名候选', review.summary.differentNamePairs],
      ['conflicts', '类型待核对', review.summary.typeConflictPairs],
    ] as const).map(([id, label, count]) => <button key={id} className={`button ${mode === id ? 'primary' : 'subtle'}`} aria-pressed={mode === id} onClick={() => setMode(id)}>{label}<span>{count}</span></button>)}</div>
    {mode === 'conflicts' && <p className="typed-notice">这些候选的类型不同，例如器物与时代。先检查类型或两者的关系，此处不能直接确认同一对象。</p>}
    {mode === 'different' && <p className="muted">名称不同但描述相关的候选。排序分数表示相关性，身份需要结合两侧证据判断。</p>}
    {grouped ? groups.slice(currentPage * size, (currentPage + 1) * size).map(group => <GroupCard key={group.id} group={group} sources={review.sources} pairs={byPair} decision={decision} onCompare={onCompare} onSource={onSource} />) :
      pairs.slice(currentPage * size, (currentPage + 1) * size).map(pair => <article className="typed-claim identity-pair" key={pair.id}>
        <div className="identity-pair-heading"><h3>{review.sources[pair.left].normalizedName} <span>与</span> {review.sources[pair.right].normalizedName}</h3><span>{status(decision(pair.id))}</span></div>
        <div className="identity-source-grid"><SourceCard source={review.sources[pair.left]} onSource={onSource} /><SourceCard source={review.sources[pair.right]} onSource={onSource} /></div>
        <div className="identity-pair-actions"><button className="button primary" onClick={() => onCompare(pair)}>{mode === 'conflicts' ? '查看类型差异' : '比较与复核'}</button><small>相关性重排分数 {pair.rerankerLogit.toFixed(2)}</small></div>
      </article>)}
    {total === 0 && <p className="identity-empty">没有符合搜索条件的{grouped ? '名称分组' : '候选'}。</p>}
    <div className="kg-pagination"><span>{total} {mode === 'concepts' ? '个概念' : mode === 'names' ? '组' : '对'} · 第 {currentPage + 1} / {Math.max(1, Math.ceil(total / size))} 页</span><button className="button subtle" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>上一页</button><button className="button subtle" disabled={(currentPage + 1) * size >= total} onClick={() => setPage(currentPage + 1)}>下一页</button></div>
  </div>;
}
