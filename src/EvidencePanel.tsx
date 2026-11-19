import { useEffect, useRef, useState } from 'react';
import { ArrowDownToLine, ArrowUpRight, BookOpen, FileSearch, X } from 'lucide-react';
import { call, desktop, errorText, readMedia } from './api';
import type { Evidence } from './types';

function PdfPreview({ evidence, token }: { evidence: Evidence; token?: string }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [status, setStatus] = useState('正在加载原始页面…');
  useEffect(() => {
    const target = canvas.current;
    if (!target) return;
    let active = true;
    let close: (() => Promise<void>) | undefined;
    let cancel: (() => void) | undefined;
    void import('./pdf').then(async ({ openPdf, renderPage }) => {
      if (!active) return;
      const opened = await openPdf(evidence.sourceId, evidence.bytes, token);
      close = opened.close;
      if (!active) { await close(); return; }
      const render = await renderPage(opened.pdf, evidence.ordinal, 860, target);
      cancel = () => render.cancel();
      await render.promise;
      if (active) setStatus('');
    }).catch(error => { if (active) setStatus(errorText(error)); });
    return () => { active = false; cancel?.(); void close?.(); };
  }, [evidence, token]);
  return <div className="original">{status && <p>{status}</p>}<canvas ref={canvas} aria-label={evidence.locator} hidden={Boolean(status)} /></div>;
}

function ImagePreview({ evidence, token }: { evidence: Evidence; token?: string }) {
  const [source, setSource] = useState<string>();
  const [error, setError] = useState<string>();
  useEffect(() => {
    let active = true;
    let url: string | undefined;
    void readMedia(evidence.sourceId, evidence.bytes, token).then(blob => {
      if (!active) return;
      url = URL.createObjectURL(blob);
      setSource(url);
    }).catch(error => { if (active) setError(errorText(error)); });
    return () => { active = false; if (url) URL.revokeObjectURL(url); };
  }, [evidence, token]);
  return <div className="original">{source ? <img src={source} alt={evidence.sourceName} /> : <p>{error ?? '正在加载图像…'}</p>}</div>;
}

export function EvidencePanel({ evidence, token, onClose }: { evidence?: Evidence; token?: string; onClose: () => void }) {
  const [original, showOriginal] = useState(false);
  const [error, setError] = useState('');
  const hasPreview = desktop && evidence && (evidence.extension === 'pdf' || evidence.kind === 'image');
  return (
    <aside className={`evidence-panel ${evidence ? 'has-evidence' : ''}`} aria-label="来源证据">
      <div className="evidence-head"><span className="feature-icon small"><BookOpen size={17} /></span><h2>来源证据</h2>{evidence && <button className="icon-button" type="button" title="关闭证据" onClick={onClose}><X size={17} /></button>}</div>
      {!evidence ? <div className="evidence-empty"><FileSearch size={29} strokeWidth={1.35} /><h3>查看引用</h3><p>选择搜索结果、回答引用或图谱连线，即可查看原文片段。</p></div> :
        <div className="evidence-body">
          <span className="evidence-corpus">{evidence.corpusName}</span>
          <h3>{evidence.sourceName}</h3><p className="locator">{evidence.locator}</p>
          <div className="tags"><span>{evidence.method === 'ocr' ? 'OCR' : '原生文本'}</span>{evidence.confidence !== null && <span>识别置信度 {Math.round(evidence.confidence * 100)}%</span>}</div>
          {hasPreview && <button type="button" className="button subtle" onClick={() => showOriginal(value => !value)}>{original ? '收起原始资料' : '查看原始资料'} <ArrowUpRight size={15} /></button>}
          {original && hasPreview && (evidence.extension === 'pdf' ? <PdfPreview evidence={evidence} token={token} /> : <ImagePreview evidence={evidence} token={token} />)}
          <blockquote>{evidence.text}</blockquote>
          {desktop && <button type="button" className="button subtle" onClick={() => {
            setError('');
            void call('save_source', { sourceId: evidence.sourceId, token }).catch(error => setError(errorText(error)));
          }}><ArrowDownToLine size={15} /> 保存原始文件</button>}
          {error && <p className="error" role="alert">{error}</p>}
          {evidence.sha256 !== 'fixture' && <small className="version-hash" title={evidence.sha256}>文件版本 {evidence.sha256.slice(0, 12)}</small>}
        </div>}
    </aside>
  );
}
