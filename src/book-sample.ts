import type { MotifRow } from './motif-data';
import type { Corpus, Evidence } from './types';

export const bookId = 'book-first-volume';
export const bookCorpus: Corpus = { id: bookId, name: '中国纹样全集 · 原书图版', description: '根据第一册扫描图版核读的课程样例', revision: 1, documentCount: 1 };
type Sample = { rows: MotifRow[]; evidence: Evidence[]; title: string };
let cached: Sample | undefined;
export async function readBook(): Promise<Sample | undefined> {
  if (cached) return cached;
  const response = await fetch('book-sample/manifest.json');
  if (response.status === 404 || !response.headers.get('content-type')?.includes('json')) return undefined;
  if (!response.ok) throw new Error('无法读取原书图版样本');
  cached = await response.json() as Sample;
  return cached;
}
