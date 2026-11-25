export type Box = [number, number, number, number];
export type Regions = { artifact: Box; motif: Box };
export type MotifRow = {
  id: string; sourceId: string; sourceName: string; bytes: number;
  artifactId: string; artifact: string; item: number; page: number;
  predicate: 'decorated_with' | 'period' | 'made_of' | 'uses_technique';
  objectId: string; object: string; quote: string; evidenceId: string;
  findspot?: string; observation?: string; proofLocator?: string; locator?: string; imageUrl?: string; detailUrl?: string; detailLabel?: string;
  qualifiers: { text: string }[]; regions: Regions | null;
};
export const relations = { decorated_with: '饰有纹样', period: '所属时代', made_of: '材质', uses_technique: '制作工艺' };
export function motifQuestion(name: string) {
  return '哪些器物饰有' + name + '？请列出书中已确认的时代、材质、工艺和出处。';
}
export function asksForArtifacts(question: string, name: string) {
  const text = question.trim().replace(/[？?。]+$/u, '');
  return [motifQuestion(name).slice(0,-1), name+'出现在哪些器物上', '哪些器物饰有'+name,
    '哪些器物上有'+name, name+'装饰在哪些器物上'].includes(text);
}
export function catalog(rows: MotifRow[]) {
  const motifs = new Map<string, { id: string; name: string; source: string; links: MotifRow[] }>();
  for (const row of rows) {
    if (row.predicate !== 'decorated_with') continue;
    const motif = motifs.get(row.objectId) ?? { id: row.objectId, name: row.object, source: row.sourceName, links: [] };
    motif.links.push(row);
    motifs.set(row.objectId, motif);
  }
  return [...motifs.values()].sort((a, b) => a.name.localeCompare(b.name, 'zh'));
}
export function specimens(rows: MotifRow[], links: MotifRow[]) {
  const artifacts = new Map<string, MotifRow[]>();
  for (const link of links) {
    const occurrences = artifacts.get(link.artifactId) ?? [];
    occurrences.push(link);
    artifacts.set(link.artifactId, occurrences);
  }
  for (const row of rows) {
    if (row.predicate !== 'decorated_with') artifacts.get(row.artifactId)?.push(row);
  }
  return [...artifacts.values()];
}
