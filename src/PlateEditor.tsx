import { useState } from 'react';
import { call, errorText } from './api';
import type { Box, Regions } from './motif-data';

type Corner = [number, number];
export function PlateEditor({ image, token, runId, assertionId, initial }: {
  image: string; token: string; runId: string; assertionId: string; initial?: Regions;
}) {
  const [boxes, setBoxes] = useState<Partial<Regions>>(initial ?? {});
  const [target, setTarget] = useState<keyof Regions>('artifact');
  const [first, setFirst] = useState<Corner>();
  const [status, setStatus] = useState('');
  const [saving, setSaving] = useState(false);
  function pick(point: Corner) {
    setStatus('');
    if (!first) { setFirst(point); return; }
    const box: Box = [Math.min(first[0],point[0]), Math.min(first[1],point[1]),
      Math.max(first[0],point[0]), Math.max(first[1],point[1])];
    setFirst(undefined);
    if (box[0] === box[2] || box[1] === box[3]) { setStatus('请选取有面积的区域。'); return; }
    setBoxes(prev => ({ ...prev, [target]: box }));
    if (target === 'artifact') setTarget('motif');
  }
  async function save() {
    setSaving(true);
    try { await call('save_plate_regions', { token, runId, assertionId, regions: boxes }); setStatus('图版选区已保存。'); }
    catch (e) { setStatus(errorText(e)); }
    finally { setSaving(false); }
  }
  return <details className="plate-editor"><summary>标注器物全图与纹样局部</summary>
    <p>选中区域类型，再依次点击原页上矩形的两个对角。</p>
    <select aria-label="区域类型" value={target} onChange={e => { setTarget(e.target.value as keyof Regions); setFirst(undefined); }}>
      <option value="artifact">器物全图</option><option value="motif">纹样局部</option></select>
    <div className="plate-sheet" onClick={e => {
      const b = e.currentTarget.getBoundingClientRect();
      pick([(e.clientX - b.left) / b.width, (e.clientY - b.top) / b.height]);
    }}><img src={image} alt="用于选取图版区域的原始书页" />
      <svg aria-hidden="true" viewBox="0 0 100 100" preserveAspectRatio="none">
        {(['artifact','motif'] as const).map(k => {
          const b = boxes[k];
          return b && <rect key={k} x={100*b[0]} y={100*b[1]} width={100*(b[2]-b[0])}
            height={100*(b[3]-b[1])} fill="none" stroke={k === 'motif' ? '#af452e' : '#328065'} strokeWidth="3" vectorEffect="non-scaling-stroke" />;
        })}
        {first && <circle cx={100*first[0]} cy={100*first[1]} r=".6" fill="#af452e" />}
      </svg></div>
    <button type="button" className="button subtle" disabled={!boxes.artifact || !boxes.motif || saving} onClick={() => void save()}>保存两处选区</button>
    <span role="status">{status}</span></details>;
}
