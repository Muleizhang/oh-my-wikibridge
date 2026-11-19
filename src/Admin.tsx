import { useEffect, useState } from 'react';
import { Check, ChevronDown, CircleAlert, FolderOpen, LockKeyhole, Plus, RefreshCw, Upload } from 'lucide-react';
import { open } from '@tauri-apps/plugin-dialog';
import { call, desktop, errorText } from './api';
import type { BackendStatus, Corpus, Fact, ImportResult, Source } from './types';

const labels: Record<Source['status'], string> = { processing: '处理中', failed: '失败', draft: '待发布', published: '已发布', archived: '已归档' };
const fileName = (path: string) => path.split(/[/\\]/).at(-1) ?? path;

export function Admin({ token, corpora, refresh, onLogin, onEvidence }: {
  token?: string; corpora: Corpus[]; refresh: () => Promise<void>;
  onLogin: (token: string) => Promise<void>; onEvidence: (id: string) => void;
}) {
  const [exists, setExists] = useState(true);
  const [password, setPassword] = useState('');
  const [corpus, setCorpus] = useState('');
  const [newName, setNewName] = useState('');
  const [description, setDescription] = useState('');
  const [sources, setSources] = useState<Source[]>([]);
  const [review, setReview] = useState<Fact[]>();
  const [status, setStatus] = useState<BackendStatus>();
  const [models, setModels] = useState<string[]>([]);
  const [path, setPath] = useState('');
  const [model, setModel] = useState('homo/gpt-6.1-terra');
  const [allowRemote, setAllowRemote] = useState(false);
  const [language, setLanguage] = useState('chi_sim+eng');
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [approved, setApproved] = useState(false);
  const activeCorpus = corpora.some(entry => entry.id === corpus) ? corpus : (corpora[0]?.id ?? '');

  useEffect(() => { if (desktop && !token) void call<boolean>('admin_exists').then(setExists).catch(error => setError(errorText(error))); }, [token]);
  useEffect(() => {
    if (!token) return;
    void call<BackendStatus>('backend_status').then(next => {
      setStatus(next);
      setModel(next.model ?? '');
      setAllowRemote(next.remoteAllowed);
    }).catch(error => setError(errorText(error)));
  }, [token]);
  useEffect(() => {
    setReview(undefined);
    setApproved(false);
    if (!token || !activeCorpus) { setSources([]); return; }
    let active = true;
    void call<Source[]>('list_sources', { token, corpusId: activeCorpus }).then(next => { if (active) setSources(next); })
      .catch(error => { if (active) setError(errorText(error)); });
    return () => { active = false; };
  }, [activeCorpus, token]);

  async function act(action: () => Promise<void>) {
    setBusy(true);
    setNotice('');
    setError('');
    try { await action(); }
    catch (error) { setError(errorText(error)); }
    finally { setBusy(false); }
  }
  async function reloadSources() {
    setSources(await call<Source[]>('list_sources', { token, corpusId: activeCorpus }));
    setReview(undefined);
    setApproved(false);
    await refresh();
  }
  async function addFiles() {
    if (!token) return;
    const { completeImport, importExtensions } = await import('./importer');
    const picked = await open({ title: '导入资料', multiple: true, filters: [{ name: '知识库资料', extensions: importExtensions }] });
    if (!picked) return;
    const names = Array.isArray(picked) ? picked : [picked];
    const failures: string[] = [];
    let drafts = 0;
    let duplicates = 0;
    for (const path of names) {
      try {
        setNotice(`正在导入 ${fileName(path)}`);
        const result = await call<ImportResult>('begin_import', { token, corpusId: activeCorpus, path });
        if (result.duplicate) { duplicates++; continue; }
        if (result.source.status === 'failed') throw new Error(result.source.error ?? '解析失败');
        await completeImport(result, token, language, setNotice);
        drafts++;
      } catch (error) {
        failures.push(`${fileName(path)}：${errorText(error)}`);
      }
    }
    await reloadSources();
    setNotice(`${drafts} 个文件待发布${duplicates ? ` · 跳过 ${duplicates} 个重复文件` : ''}`);
    if (failures.length) setError(failures.join('\n'));
  }

  if (!desktop) return <div className="surface admin-empty"><LockKeyhole size={25} /><h2>管理员工作区</h2><p>在 Tauri 桌面应用中导入资料、审核和配置 OpenCode。</p></div>;
  if (!token) return (
    <div className="surface admin-empty">
      <span className="feature-icon"><LockKeyhole size={23} /></span><h2>{exists ? '解锁管理员工作区' : '设置管理员口令'}</h2>
      <p>{exists ? '解锁后可导入、审核发布和配置 OpenCode。' : '本机首次使用。设置口令后可开始导入资料。'}</p>
      <form className="form-row" onSubmit={event => { event.preventDefault(); void act(async () => {
        const next = await call<string>('admin_login', { password });
        setPassword('');
        await onLogin(next);
      }); }}>
        <input aria-label="管理员口令" type="password" autoComplete={exists ? 'current-password' : 'new-password'} value={password} onChange={event => setPassword(event.target.value)} required minLength={exists ? 1 : 8} />
        <button className="button primary" disabled={busy}>{exists ? '解锁' : '创建管理员'}</button>
      </form>
      {error && <p className="error" role="alert">{error}</p>}
    </div>
  );

  const currentDrafts = sources.filter(file => file.status === 'draft');
  return <div className="admin-grid">
    {notice && <div className="notice" role="status">{busy && <RefreshCw className="spin" size={15} />}{notice}</div>}
    {error && <div className="error notice" role="alert"><CircleAlert size={17} />{error}</div>}
    <section className="surface admin-surface">
      <div className="section-heading"><div><h2>语料库与文件</h2><p>导入后的资料会留在草稿区，审核发布后供访客查询。</p></div></div>
      <form className="create-form" onSubmit={event => { event.preventDefault(); void act(async () => {
        const id = await call<string>('create_corpus', { token, name: newName, description });
        setNewName('');
        setDescription('');
        await refresh();
        setCorpus(id);
      }); }}>
        <input aria-label="新语料库名称" placeholder="新语料库名称" required value={newName} onChange={event => setNewName(event.target.value)} />
        <input aria-label="语料库说明" placeholder="说明（可选）" value={description} onChange={event => setDescription(event.target.value)} />
        <button className="button subtle" disabled={busy}><Plus size={16} /> 新建</button>
      </form>
      {activeCorpus && <>
        <div className="file-controls">
          <label className="select wrap"><FolderOpen size={16} /><select aria-label="管理语料库" value={activeCorpus} disabled={busy} onChange={event => setCorpus(event.target.value)}>
            {corpora.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select><ChevronDown size={15} /></label>
          <label className="select wrap"><select aria-label="OCR 语言" value={language} disabled={busy} onChange={event => setLanguage(event.target.value)}>
            <option value="chi_sim+eng">简体中文 + 英语</option><option value="chi_tra+eng">繁体中文 + 英语</option><option value="eng">英语</option>
          </select><ChevronDown size={15} /></label>
          <button type="button" className="button primary" disabled={busy} onClick={() => void act(addFiles)}><Upload size={16} /> 导入资料</button>
        </div>
        <div className="file-list">
          {!sources.length && <p className="muted">此语料库还没有文件。</p>}
          {sources.map(file => <div className="file-row" key={file.id}>
            <div className="extension">{file.extension.toUpperCase()}</div><div className="file-title"><strong>{file.name}</strong><small>{file.unitCount} 个内容单元 · {file.sha256.slice(0, 8)}{file.error && ` · ${file.error}`}</small></div>
            <span className={`status-pill ${file.status}`}>{labels[file.status]}</span>
            {(file.status === 'failed' || file.status === 'processing') && <button className="icon-button" title="重新处理" disabled={busy} type="button" onClick={() => void act(async () => {
              const { completeImport } = await import('./importer');
              const result = await call<ImportResult>('retry_import', { token, sourceId: file.id });
              try { await completeImport(result, token, language, setNotice); }
              finally { await reloadSources(); }
              if (result.source.status === 'failed') throw new Error(result.source.error ?? '解析失败');
              setNotice('文件重新处理完成。');
            })}><RefreshCw size={15} /></button>}
          </div>)}
        </div>
        <div className="review">
          <div className="section-heading"><div><h3>发布前整体审核</h3><p>{currentDrafts.length} 个文件 · {currentDrafts.reduce((total, file) => total + file.unitCount, 0)} 个内容单元</p></div>
            <button className="button subtle" disabled={busy || !currentDrafts.length} type="button" onClick={() => void act(async () => {
              setReview(await call<Fact[]>('graph_library', { corpusIds: [activeCorpus], evidenceIds: [], reviewToken: token }));
            })}>查看抽取样例</button>
          </div>
          {review && <div className="review-samples">{review.length ? review.slice(0, 8).map((fact, index) =>
            <button type="button" key={index} onClick={() => onEvidence(fact.evidenceId)}>{fact.subject} <span>{fact.relation}</span> {fact.object}</button>
          ) : <p>草稿中没有匹配当前规则的三元组。发布后仍可检索原文。</p>}</div>}
          <div className="publish-row">
            <label><input type="checkbox" checked={approved} disabled={!currentDrafts.length || busy} onChange={event => setApproved(event.target.checked)} /> 已完成本批次审核</label>
            <button type="button" className="button primary" disabled={!approved || !currentDrafts.length || busy} onClick={() => void act(async () => {
              const version = await call<number>('publish_corpus', { token, corpusId: activeCorpus });
              await reloadSources();
              setNotice(`已发布版本 ${version}，访客现在可以查询。`);
            })}><Check size={17} /> 发布</button>
          </div>
        </div>
      </>}
    </section>
    <section className="surface admin-surface">
      <div className="section-heading"><div><h2>OpenCode</h2><p>{status?.version ? `已检测到 ${status.version}` : '尚未连接到可识别的 OpenCode。'}</p></div>
        <a className="button subtle" href={status?.installUrl ?? 'https://opencode.ai/docs/'} target="_blank" rel="noreferrer">官方安装说明</a>
      </div>
      <form className="backend-form" onSubmit={event => { event.preventDefault(); void act(async () => {
        await call('configure_backend', { token, path, model, allowRemote });
        setStatus(await call<BackendStatus>('backend_status'));
        setNotice('OpenCode 设置已保存。');
      }); }}>
        <label>可执行文件 <input placeholder="自动检测，或输入绝对路径" value={path} onChange={event => setPath(event.target.value)} /></label>
        <label>模型 <input value={model} onChange={event => setModel(event.target.value)} list="opencode-models" placeholder="provider/model" /></label>
        <datalist id="opencode-models">{models.map(id => <option key={id} value={id} />)}</datalist>
        <label className="checkbox-label"><input type="checkbox" checked={allowRemote} onChange={event => setAllowRemote(event.target.checked)} /> 启用问答，允许 OpenCode 将问题和检索片段发送给所选模型提供商</label>
        <div className="action-row"><button className="button primary" disabled={busy}>保存并检测</button>
          <button className="button subtle" type="button" disabled={busy} onClick={() => void act(async () => {
            const listed = await call<string[]>('backend_models', { token });
            setModels(listed);
            setNotice(`OpenCode 返回 ${listed.length} 个模型。可在模型输入框选择。`);
          })}>检查模型列表</button>
        </div>
      </form>
    </section>
  </div>;
}
