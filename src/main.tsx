import { MotifAtlas } from './MotifAtlas';
import { StrictMode, useCallback, useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { listen } from '@tauri-apps/api/event';
import ReactMarkdown from 'react-markdown';
import {
  ArrowDownToLine, ArrowRight, ArrowUpRight, BarChart3, BookOpen, ChevronDown, CircleHelp,
  Database, FileText, FolderOpen, GitFork, Globe2, LockKeyhole, Network, ScanSearch,
  Search, Send, Sparkles, Workflow, type LucideIcon,
} from 'lucide-react';
import { Admin } from './Admin';
import { call, desktop, errorText } from './api';
import { EvidencePanel } from './EvidencePanel';
import { AnalyticsView, GraphView } from './Explore';
import { ReliableGraph } from './ReliableGraph';
import type { Answer, Corpus, Evidence, Hit, SearchResult, Source, Trace } from './types';
import './style.css';

const pages = [
  { id: 'research', title: '知识检索', icon: ScanSearch },
  { id: 'library', title: '资料目录', icon: BookOpen },
  { id: 'graph', title: '关系图谱', icon: Network },
  { id: 'localgraph', title: '本地语料图谱', icon: GitFork },
  { id: 'analytics', title: '语料分析', icon: BarChart3 },
  { id: 'admin', title: '管理员工作区', icon: LockKeyhole },
] as const;
type Page = typeof pages[number]['id'];
type Mode = 'rag' | 'keyword' | 'tfidf' | 'hybrid';

const descriptions: Record<Page, string> = {
  research: '检索资料、查看来源，并提出需要证据支持的问题。',
  library: '按语料库浏览已发布的资料。',
  graph: '沿实体关系查找出处。',
  localgraph: '查看器物属性、事件、来源陈述与复核依据。',
  analytics: '用课堂方法观察语料中的词汇与关联。',
  admin: '导入多格式文件、审核资料并设置 OpenCode。',
};
const tools: Record<string, string> = {
  search_fts: '全文检索', rank_hybrid: '混合排序', rank_tfidf: 'TF-IDF 排序',
  book_relations: '原书图版关系查询', reviewed_motifs: '已复核纹样关系', query_graph: 'RDF 图谱查询', opencode_generate: 'OpenCode 生成',
};
const choices: { label: string; value: Mode; icon: LucideIcon }[] = [
  { label: 'RAG 问答', value: 'rag', icon: Sparkles },
  { label: '关键词', value: 'keyword', icon: Search },
  { label: 'TF-IDF', value: 'tfidf', icon: BarChart3 },
  { label: '混合检索', value: 'hybrid', icon: Workflow },
];
const sampleQueries = ['汉代云气纹与哪些器物有关？', '唐代铜镜出现了哪种纹样？', '比较不同年代的纹样构成'];

function KnowledgeLibrary({ corpora, selection }: { corpora: Corpus[]; selection: string[] }) {
  const key = selection.join(',');
  const [documents, setDocuments] = useState<Record<string, Source[]>>({});
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    if (!key) return;
    setError('');
    void Promise.all(key.split(',').map(async id => [id, await call<Source[]>('list_sources', { corpusId: id })] as const))
      .then(data => { if (active) setDocuments(Object.fromEntries(data)); })
      .catch(error => { if (active) setError(errorText(error)); });
    return () => { active = false; };
  }, [key, corpora]);
  return <section className="surface explore-surface">
    {error && <p className="error" role="alert">{error}</p>}
    {!selection.length && <div className="evidence-empty"><Database size={26} /><h3>尚未选择语料库</h3><p>通过左侧菜单选择已发布的语料。</p></div>}
    {corpora.filter(item => selection.includes(item.id)).map(item => <div className="catalog" key={item.id}>
      <h2>{item.name}</h2><p>{item.description || `已发布版本 ${item.revision}`}</p>
      {(documents[item.id] ?? []).map(source => <div className="file-row" key={source.id}>
        <span className="extension">{source.extension.toUpperCase()}</span><div className="file-title"><strong>{source.name}</strong><small>{source.unitCount} 个内容单元 · {source.sha256.slice(0, 12)}</small></div>
        <span className="status-pill published">已发布</span>
      </div>)}
    </div>)}
  </section>;
}

function App() {
  const [page, setPage] = useState<Page>(new URLSearchParams(location.search).get('view') === 'localgraph' ? 'localgraph' : 'research');
  const [corpora, setCorpora] = useState<Corpus[]>([]);
  const [adminCorpora, setAdminCorpora] = useState<Corpus[]>([]);
  const [chosen, setChosen] = useState<string[]>();
  const [token, setToken] = useState<string>();
  const [scopeOpen, setScopeOpen] = useState(false);
  const [mode, setMode] = useState<Mode>('rag');
  const [input, setInput] = useState('');
  const [lastQuestion, setLastQuestion] = useState('');
  const [lastScope, setLastScope] = useState<string[]>([]);
  const [results, setResults] = useState<Hit[]>([]);
  const [answer, setAnswer] = useState<Answer>();
  const [trace, setTrace] = useState<Trace[]>([]);
  const [evidence, setEvidence] = useState<Evidence>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [exportNotice, setExportNotice] = useState('');
  const selected = useMemo(() => (chosen ?? (desktop ? corpora.slice(0,1) : corpora).map(c => c.id))
    .filter(id => corpora.some(entry => entry.id === id)), [chosen, corpora]);
  const current = pages.find(entry => entry.id === page)!;

  const refresh = useCallback(async (activeToken = token) => {
    setCorpora(await call<Corpus[]>('list_corpora'));
    if (activeToken) setAdminCorpora(await call<Corpus[]>('list_corpora', { token: activeToken }));
  }, [token]);
  useEffect(() => { void refresh().catch(error => setError(errorText(error))); }, [refresh]);
  useEffect(() => {
    if (!desktop) return;
    let unlisten: (() => void) | undefined;
    void listen('wikibridge://open-admin', () => {
      setPage('admin');
      setScopeOpen(false);
      setEvidence(undefined);
    }).then(stop => { unlisten = stop; });
    return () => { unlisten?.(); };
  }, []);

  function navigate(target: Page) {
    setPage(target);
    setScopeOpen(false);
    setEvidence(undefined);
    setError('');
  }
  function toggleCorpus(id: string) {
    setChosen(selected.includes(id) ? selected.filter(item => item !== id) : [...selected, id]);
  }
  function showEvidence(id: string, review = false) {
    const existing = answer?.evidence.find(entry => entry.id === id) ?? results.find(hit => hit.evidence.id === id)?.evidence;
    if (existing) { setEvidence(existing); return; }
    void call<Evidence>('evidence', { id, token: review ? token : undefined }).then(setEvidence).catch(error => setError(errorText(error)));
  }
  async function search(question = input, queryMode = mode, motifId?: string) {
    const query = question.trim();
    if (!query || !selected.length || busy) return;
    setInput(query);
    setLastQuestion(query);
    setLastScope(corpora.filter(corpus => selected.includes(corpus.id)).map(corpus => `${corpus.name} v${corpus.revision}`));
    setBusy(true);
    setError('');
    setAnswer(undefined);
    setResults([]);
    setTrace([]);
    setEvidence(undefined);
    setExportNotice('');
    try {
      if (queryMode === 'rag') {
        const response = await call<Answer>('ask_library', { question: query, corpusIds: selected, motifId });
        setAnswer(response);
        setTrace(response.trace);
      } else {
        const response = await call<SearchResult>('search_library', { query, corpusIds: selected, mode: queryMode });
        setResults(response.hits);
        setTrace(response.trace);
      }
    } catch (error) { setError(errorText(error)); }
    finally { setBusy(false); }
  }
  async function exportResult() {
    const sources = answer?.evidence ?? results.map(result => result.evidence);
    const body = [
      '# WikiBridge 检索记录', '', lastQuestion, '', `范围：${lastScope.join('、')}`,
      ...(answer?.model ? [`模型：${answer.model}`] : []),
      '', ...(answer?.answer ? [answer.answer, ''] : []),
      '## 来源证据', ...sources.flatMap((source, index) => [
        `\n[${index + 1}] ${source.corpusName} / ${source.sourceName} / ${source.locator}`,
        `SHA-256: ${source.sha256}`, '', source.text,
      ]),
      '\n## 检索过程', ...trace.map(step => `- ${tools[step.tool] ?? step.tool}: ${step.detail}`),
    ].join('\n');
    try {
      if (desktop) {
        const saved = await call<boolean>('save_report', { text: body });
        if (!saved) return;
      } else {
        const url = URL.createObjectURL(new Blob([body], { type: 'text/markdown;charset=utf-8' }));
        const link = document.createElement('a');
        link.href = url;
        link.download = 'WikiBridge.md';
        link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      }
      setExportNotice('检索记录已导出。');
    } catch (error) { setError(errorText(error)); }
  }

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><span className="brand-mark"><GitFork size={22} /></span><div><strong>WikiBridge</strong><small>本地知识工作台</small></div></div>
      <nav aria-label="主导航">{pages.map(item => <button type="button" key={item.id} aria-current={page === item.id ? 'page' : undefined}
        className={page === item.id ? 'nav-button active' : 'nav-button'} onClick={() => navigate(item.id)}><item.icon size={18} />{item.title}</button>)}</nav>
      <div className="sidebar-libraries">
        <div className="sidebar-label">已发布语料库</div>
        {!corpora.length && <span className="sidebar-empty">暂无已发布语料</span>}
        {corpora.map(item => <button type="button" key={item.id} aria-pressed={selected.includes(item.id)} onClick={() => toggleCorpus(item.id)}
          className="corpus-button"><span className={`library-dot ${selected.includes(item.id) ? 'selected' : ''}`} /><span>{item.name}</span><small>{item.documentCount}</small></button>)}
      </div>
      <div className="sidebar-foot"><div className="role-mark">{token ? <LockKeyhole size={17} /> : <Globe2 size={17} />}</div><div><strong>{token ? '管理员已解锁' : '访客模式'}</strong><small>{desktop ? '桌面工作区' : '浏览器演示'}</small></div>
        {token && <button className="icon-button" type="button" title="锁定管理员" onClick={() => {
          void call('admin_logout', { token }).then(() => { setToken(undefined); setAdminCorpora([]); navigate('research'); })
            .catch(error => setError(errorText(error)));
        }}><LockKeyhole size={16} /></button>}
      </div>
    </aside>

    <main className="main"><header className="topbar"><span><current.icon size={17} />{current.title}</span>
      {page !== 'admin' && page !== 'localgraph' && <div className="scope">
        <button type="button" className="button subtle scope-toggle" aria-expanded={scopeOpen} onClick={() => setScopeOpen(!scopeOpen)}>
          <FolderOpen size={16} />{selected.length === 1 ? corpora.find(item => item.id === selected[0])?.name : `已选 ${selected.length} 个语料库`}<ChevronDown size={15} /></button>
        {scopeOpen && <div className="scope-menu"><strong>查询范围</strong>{corpora.length ? corpora.map(item => <label key={item.id}>
          <input type="checkbox" checked={selected.includes(item.id)} onChange={() => toggleCorpus(item.id)} />{item.name}
        </label>) : <p>暂无已发布语料。</p>}</div>}
      </div>}
    </header>
    <div className={`work-area ${evidence ? 'with-evidence' : ''} ${page === 'localgraph' ? 'local-graph-area' : ''}`}>
      <section className="content">
        <div className="headline"><h1>{page === 'research' ? '从问题到证据' : current.title}</h1><p>{descriptions[page]}</p></div>
        {error && <div className="error notice" role="alert">{error}</div>}
        {page === 'research' && <>
          <form className="query-box" onSubmit={event => { event.preventDefault(); void search(); }}>
            <label className="sr-only" htmlFor="question">搜索或提问</label>
            <textarea id="question" placeholder={mode === 'rag' ? '输入你想了解的问题…' : '输入资料中可能出现的词语…'} maxLength={600} value={input} onChange={event => setInput(event.target.value)}
              onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void search(); } }} />
            <div className="query-actions">
              <div className="modes" aria-label="查询方式">{choices.map(choice => <button type="button" key={choice.value} disabled={busy} className={mode === choice.value ? 'selected' : ''}
                aria-pressed={mode === choice.value} onClick={() => setMode(choice.value)}><choice.icon size={15} />{choice.label}</button>)}</div>
              <button className="button primary send" disabled={!input.trim() || !selected.length || busy}>{busy ? '处理中…' : '查询'}<Send size={15} /></button>
            </div>
          </form>
          {!desktop && <div className="quick-queries">{sampleQueries.map(query => <button type="button" key={query} disabled={busy} onClick={() => void search(query)}>{query}<ArrowUpRight size={14} /></button>)}</div>}
          {!selected.length && <div className="surface start-card"><span className="feature-icon"><Database size={20} /></span><div>
            <h2>{corpora.length ? '选择查询范围' : '还没有已发布的语料'}</h2><p>{corpora.length ? '从左侧或右上方选择要查询的语料库。' : '在管理员工作区导入、审核并发布资料后，即可开始检索。'}</p>
            {!corpora.length && <button type="button" className="text-button" onClick={() => navigate('admin')}>打开管理员工作区 <ArrowRight size={16} /></button>}
          </div></div>}
          {busy && <p role="status" className="notice"><Workflow size={17} /> 正在查找证据{mode === 'rag' ? '，并准备问答' : ''}…</p>}
          {!busy && lastQuestion && (trace.length > 0 || answer) && <section className="surface results">
            <div className="section-heading"><div><h2>{answer ? '知识问答' : '检索结果'}</h2><p>{lastScope.join('、')}</p></div>
              {(results.length > 0 || Boolean(answer?.evidence.length)) && <button type="button" className="button subtle" onClick={() => void exportResult()}><ArrowDownToLine size={16} /> 导出</button>}
            </div>
            {exportNotice && <p role="status" className="muted">{exportNotice}</p>}
            {answer?.error && <p className="muted">{answer.error}</p>}
            {answer?.answer && <div className="answer-text"><ReactMarkdown skipHtml components={{
              a: ({ href, children }) => {
                const index = Number(href?.match(/^#source-(\d+)$/)?.[1]);
                const source = answer.evidence[index - 1];
                return source ? <button className="citation" type="button" onClick={() => setEvidence(source)}>{children}</button> : <span>{children}</span>;
              },
              img: ({ alt }) => <span>{alt}</span>,
            }}>{answer.answer.replace(/\[(\d+)\](?!\()/g, '[$1](#source-$1)')}</ReactMarkdown></div>}
            {answer?.evidence.map((item, index) => <ResultRow key={item.id} item={item} index={index + 1} onClick={() => setEvidence(item)} />)}
            {results.map((hit, index) => <ResultRow key={hit.evidence.id} item={hit.evidence} index={index + 1} score={hit.score} onClick={() => setEvidence(hit.evidence)} />)}
            {!answer && !results.length && <p className="muted">所选语料中没有匹配的文本片段。</p>}
            {!!trace.length && <details className="trace" open><summary><Workflow size={17} /> 检索与工具调用 <span>{trace.length} 步</span></summary><ol>
              {trace.map((step, index) => <li key={index}><span className="step-index">{index + 1}</span><div><strong>{tools[step.tool] ?? step.tool}</strong><p>{step.detail}</p>
                {step.evidenceIds.length > 0 && <div className="trace-links">{[...new Set(step.evidenceIds)].slice(0, 10).map((id, index) =>
                  <button type="button" key={id} onClick={() => showEvidence(id)}>证据 {index + 1}</button>)}</div>}</div></li>)}
            </ol></details>}
          </section>}
          {!trace.length && !busy && selected.length > 0 && <div className="surface start-card">
            <span className="feature-icon"><CircleHelp size={20} /></span><div><h2>可以从哪里开始</h2><p>检索一个纹样、一个时代或一种材质。提问后可逐步查看检索结果、图谱关系和引用原文。</p></div>
          </div>}
        </>}
        {page === 'library' && <KnowledgeLibrary corpora={corpora} selection={selected} />}
        {page === 'graph' && <><MotifAtlas key={JSON.stringify(selected)} scope={selected} onEvidence={id => {
          void call<Evidence>('evidence', { id }).then(setEvidence).catch(e => setError(errorText(e)));
        }} onAsk={(q, id) => { navigate('research'); setMode('rag'); void search(q, 'rag', id); }} />
          <GraphView selection={selected} onEvidence={showEvidence} /></>}
        {page === 'localgraph' && <ReliableGraph token={token} onUnlock={() => navigate('admin')} />}
        {page === 'analytics' && <AnalyticsView selection={selected} />}
        <div hidden={page !== 'admin'}><Admin token={token} corpora={adminCorpora} refresh={refresh} onLogin={async next => {
          setToken(next); await refresh(next);
        }} onEvidence={id => showEvidence(id, true)} /></div>
      </section>
      {page !== 'localgraph' && <EvidencePanel key={evidence?.id ?? 'empty'} evidence={evidence} token={page === 'admin' ? token : undefined} onClose={() => setEvidence(undefined)} />}
    </div></main>
  </div>;
}

function ResultRow({ item, index, score, onClick }: { item: Evidence; index: number; score?: number; onClick: () => void }) {
  return <button type="button" className="result-row" onClick={onClick}>
    <span className="result-icon"><FileText size={17} /></span><span className="result-main"><strong>{item.sourceName}</strong>
      <small>[{index}] {item.corpusName} · {item.locator}{score !== undefined && ` · 排序分 ${score.toFixed(3)}`}</small><span>{item.text}</span></span><ArrowUpRight size={16} />
  </button>;
}

createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>);
