import { bookCorpus, bookId, readBook } from './book-sample';
import { asksForArtifacts, relations, specimens } from './motif-data';
import type { Answer, Corpus, Evidence, Fact, SearchResult, Source } from './types';

const corpus: Corpus = { id: 'sample', name: '纹样演示样本', description: '浏览器调试用的示例条目', revision: 1, documentCount: 3 };
const samples = [
  { source: '纹样观察笔记.md', locator: '第 12 行', title: '云气纹', text: '云气纹常以弧线和卷旋组织画面。样本将汉代漆器中的云气纹与同一件器物上的几何边饰一并记录，便于观察主题纹样与边饰的关系。', age: '汉代', material: '漆器' },
  { source: '纹样示例图录.md', locator: '第 24 行', title: '莲花纹', text: '本样本记录了一件带莲花纹的唐代铜镜。花瓣绕中心排列，可用于观察辐射对称构成。', age: '唐代', material: '铜镜' },
  { source: '装饰构成课堂笔记.md', locator: '第 8 行', title: '几何纹', text: '编者把早期陶器上的几何纹整理为连续纹样示例。重复单元沿带状区域排列。', age: '新石器时代', material: '陶器' },
];
const entries: Evidence[] = samples.map((entry, index) => ({
  id: `sample:${index}`, sourceId: `sample-source:${index}`, corpusId: corpus.id,
  corpusName: corpus.name, sourceName: entry.source, extension: 'md', bytes: 0, sha256: 'fixture',
  kind: 'line', ordinal: index + 1, locator: entry.locator, text: entry.text, method: 'native', confidence: null,
}));
const facts: Fact[] = samples.flatMap((item, index) => [item.age, item.material].map(value => ({
  subject: item.title, relation: '同句提及', object: value, evidenceId: entries[index].id,
})));
const files: Source[] = entries.map(entry => ({
  id: entry.sourceId, name: entry.sourceName, extension: 'md', bytes: 0, sha256: 'fixture',
  status: 'published', error: null, unitCount: 1, createdAt: '2026-11-20',
}));

export async function fixture(command: string, args: Record<string, unknown>): Promise<unknown> {
  const scope = (args.corpusIds ?? []) as string[];
  const usesBook = scope.includes(bookId) || args.corpusId === bookId || String(args.id ?? '').startsWith('book1:');
  const book = (command === 'list_corpora' || usesBook) ? await readBook() : undefined;
  switch (command) {
    case 'list_corpora': return book ? [bookCorpus, corpus] : [corpus];
    case 'published_motifs': return book?.rows ?? [];
    case 'list_sources': if (book && args.corpusId === bookId) return [{
      id:bookId, name:book.title, extension:'pdf', sha256:book.evidence[0].sha256, bytes:book.evidence[0].bytes,
      status:'published', unitCount:new Set(book.evidence.map(e=>e.ordinal)).size, createdAt:'',
    }]; return args.corpusId === corpus.id ? files : [];
    case 'admin_exists': return false;
    case 'backend_status': return { detected: false, version: null, model: 'homo/gpt-6.1-terra', installUrl: 'https://opencode.ai/docs/', remoteAllowed: false };
    case 'evidence': return [...entries, ...(book?.evidence ?? [])].find(entry => entry.id === args.id);
    case 'graph_library': return [...(scope.includes(corpus.id) ? facts : []), ...(book?.rows ?? []).map(r => ({
      subject: r.artifact + '（' + r.locator + '）', relation: relations[r.predicate],
      object: r.object, evidenceId: r.evidenceId,
    }))].filter(fact => !(args.evidenceIds as string[]).length || (args.evidenceIds as string[]).includes(fact.evidenceId));
    case 'analyze_library': if (!scope.includes(corpus.id)) return { sampleSize:0,topTerms:[],pairs:[],projection:[],neighbors:[] }; return {
      sampleSize: entries.length, topTerms: [['纹样', 4], ['云气纹', 2], ['几何纹', 2], ['构成', 2]],
      pairs: [['云气纹', '漆器', 2], ['莲花纹', '铜镜', 1]],
      projection: [['纹样', 0.2, 0.1], ['云气纹', 0.6, 0.3], ['几何纹', 0.1, 0.7], ['构成', -0.3, 0.2]],
      neighbors: [],
    };
    case 'search_library':
    case 'ask_library': {
      const query = String(args.query ?? args.question);
      const links = book?.rows.filter(r => r.predicate === 'decorated_with' && (args.motifId ? r.objectId === args.motifId : query.includes(r.object))) ?? [];
      const groups = specimens(book?.rows ?? [], links);
      if (book && command === 'ask_library' && links.some(link => asksForArtifacts(query,link.object))) {
        const ids = [...new Set(groups.flat().map(r => r.evidenceId))];
        const evidence = ids.map(id => book.evidence.find(e => e.id === id)!);
        const answer = groups.map(g => '- ' + g[0].artifact + '（' + g[0].locator + '） · ' +
          g.map(r => relations[r.predicate] + '：' + r.object + ' ['+(ids.indexOf(r.evidenceId)+1)+']').join('，')).join('\n');
        return { answer, model:null, error:null, evidence, trace:[{tool:'book_relations',
          detail:'由原书图版核读样本的实体和陈述生成', evidenceIds:ids}] } satisfies Answer;
      }
      const selected = (scope.includes(corpus.id) ? entries : []).filter((_, index) => query.includes(samples[index].title) || query.includes(samples[index].age)
        || query.includes(samples[index].material) || query.includes('纹样') || query.includes('比较'));
      if (book) selected.push(...book.evidence.filter(e => groups.some(g=>g.some(r=>r.evidenceId===e.id))
        || e.text.includes(query)));
      const hits = selected.map((evidence, index) => ({ evidence, score: 0.82 - index * 0.14 }));
      const trace = [{ tool: 'search_fts', detail: `测试数据返回 ${selected.length} 条证据`, evidenceIds: selected.map(x => x.id) }];
      if (command === 'search_library') return { hits, trace } satisfies SearchResult;
      return { answer: null, error: '浏览器演示使用测试数据。OpenCode 问答在桌面应用中可用。', evidence: selected, trace, model: null } satisfies Answer;
    }
    default: throw new Error('此操作需要桌面应用。');
  }
}
