import { useEffect, useMemo, useState } from 'react';
import { BarChart3, GitFork, Network, RefreshCw } from 'lucide-react';
import { call, errorText } from './api';
import type { Analytics, Fact } from './types';

export function FactGraph({ facts, onEvidence }: { facts: Fact[]; onEvidence: (id: string) => void }) {
  const { nodes, edges } = useMemo(() => {
    const chosen = new Set<string>();
    const visible = facts.filter(fact => {
      if (new Set([...chosen, fact.subject, fact.object]).size > 11) return false;
      chosen.add(fact.subject);
      chosen.add(fact.object);
      return true;
    });
    const nodes = [...chosen].map((label, index) => {
      const angle = 2 * Math.PI * index / chosen.size - Math.PI / 2;
      return { label, x: 330 + Math.cos(angle) * 194, y: 158 + Math.sin(angle) * 104 };
    });
    const byLabel = new Map(nodes.map(node => [node.label, node]));
    const edges = [...new Map(visible.map(fact => [JSON.stringify([fact.subject, fact.object]), fact])).values()]
      .map(fact => ({ ...fact, from: byLabel.get(fact.subject)!, to: byLabel.get(fact.object)! }));
    return { nodes, edges };
  }, [facts]);
  if (!nodes.length) return <div className="evidence-empty"><GitFork size={25} /><h3>没有匹配的关系</h3><p>已发布语料中的显式三元组和纹样同句共现会出现在这里。</p></div>;
  return <>
    <div className="graph-visual">
      <svg viewBox="0 0 660 316" role="img" aria-label="基于所选语料的关系图。连线出处见下方列表。">
        {edges.map(edge => <line key={JSON.stringify([edge.subject, edge.object])} x1={edge.from.x} x2={edge.to.x} y1={edge.from.y} y2={edge.to.y} />)}
        {nodes.map(node => <g key={node.label} transform={`translate(${node.x},${node.y})`}>
          <circle r="6" /><text y="-12" textAnchor="middle">{node.label.length > 14 ? `${node.label.slice(0, 13)}…` : node.label}</text>
        </g>)}
      </svg>
    </div>
    <div className="graph-list">{facts.map((fact, index) => <button type="button" key={index} onClick={() => onEvidence(fact.evidenceId)}>
      <strong>{fact.subject}</strong><span>{fact.relation}</span><strong>{fact.object}</strong><small>查看证据</small>
    </button>)}</div>
  </>;
}

export function GraphView({ selection, onEvidence }: { selection: string[]; onEvidence: (id: string) => void }) {
  const [facts, setFacts] = useState<Fact[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [query, setQuery] = useState('');
  const scope = selection.join(',');
  useEffect(() => {
    let active = true;
    if (!scope) { setFacts([]); return; }
    setLoading(true);
    setError('');
    void call<Fact[]>('graph_library', { corpusIds: scope.split(','), evidenceIds: [] })
      .then(value => { if (active) setFacts(value); })
      .catch(error => { if (active) setError(errorText(error)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [scope]);
  const filtered = facts.filter(fact => !query || [fact.subject, fact.relation, fact.object].some(value => value.toLowerCase().includes(query.toLowerCase())));
  return <section className="surface explore-surface">
    <div className="section-heading"><div><h2><Network size={19} /> 纹样与知识关系</h2><p>查询已发布的 RDF 关系。点击下方任意三元组查看来源。</p></div>
      <input aria-label="筛选关系" placeholder="筛选实体或关系" value={query} onChange={event => setQuery(event.target.value)} />
    </div>
    {error ? <p className="error" role="alert">{error}</p> : loading ? <p className="muted"><RefreshCw className="spin" size={15} /> 正在查询图谱</p> :
      <FactGraph facts={filtered} onEvidence={onEvidence} />}
  </section>;
}

export function AnalyticsView({ selection }: { selection: string[] }) {
  const [result, setResult] = useState<Analytics>();
  const [keyword, setKeyword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [scopeOfResult, setScopeOfResult] = useState('');
  const scope = selection.join(',');
  const shown = scope === scopeOfResult ? result : undefined;
  async function run() {
    setBusy(true);
    setError('');
    try {
      setResult(await call<Analytics>('analyze_library', { corpusIds: selection, keyword }));
      setScopeOfResult(scope);
    } catch (error) { setError(errorText(error)); }
    finally { setBusy(false); }
  }
  const max = shown?.topTerms[0]?.[1] || 1;
  const extent = Math.max(1, ...shown?.projection.flatMap(([, x, y]) => [Math.abs(x), Math.abs(y)]) ?? []);
  return <section className="surface explore-surface">
    <div className="section-heading"><div><h2><BarChart3 size={19} /> 语料分析</h2><p>从已选语料抽样，观察词频、近邻共现和 SVD 投影。</p></div></div>
    <form className="form-row analysis-form" onSubmit={event => { event.preventDefault(); void run(); }}>
      <input value={keyword} onChange={event => setKeyword(event.target.value)} placeholder="Word2Vec 查询词（可选）" aria-label="Word2Vec 查询词" />
      <button className="button primary" disabled={busy || !selection.length}>{busy ? '分析中…' : '运行分析'}</button>
    </form>
    {error && <p className="error" role="alert">{error}</p>}
    {shown && <>
      <p className="muted">{shown.sampleSize} 条证据片段参与分析，最多抽样 240 条。</p>
      <div className="analysis-grid">
        <div className="analysis-card"><h3>词频</h3>{shown.topTerms.length ? shown.topTerms.slice(0, 10).map(([word, count]) => <div className="bar" key={word}><span>{word}</span><i style={{ width: `${count / max * 100}%` }} /><small>{count}</small></div>) : <p>没有足够样本。</p>}</div>
        <div className="analysis-card"><h3>近邻共现</h3>{shown.pairs.length ? shown.pairs.slice(0, 10).map(([left, right, count]) => <div className="data-line" key={`${left}/${right}`}><span>{left} · {right}</span><strong>{count}</strong></div>) : <p>没有重复出现的近邻词对。</p>}</div>
        {shown.projection.length > 0 && <div className="analysis-card"><h3>SVD 二维投影</h3><svg className="scatter" viewBox="0 0 350 250" role="img" aria-label="共现矩阵的前两个奇异向量投影">
          <path d="M25 125h300M175 25v200" /><g>{shown.projection.map(([label, x, y]) => <g key={label} transform={`translate(${175 + x / extent * 124},${125 - y / extent * 86})`}><circle r="4" /><text x="6" y="-3">{label}</text></g>)}</g></svg></div>}
        {shown.neighbors.length > 0 && <div className="analysis-card"><h3>Word2Vec 近邻</h3><p>使用采样语料训练的 Skip-gram 负采样模型。</p>{shown.neighbors.map(([word, score]) => <div className="data-line" key={word}><span>{word}</span><strong>{score.toFixed(3)}</strong></div>)}</div>}
      </div>
    </>}
  </section>;
}
