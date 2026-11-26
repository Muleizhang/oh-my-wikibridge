/**
 * Unified Atlas & Neuro-Symbolic DeepSeek Agent Server.
 * Zero external runtime dependencies — runs natively on Node.js 22+/24+:
 *   node server/atlas-server.ts --port 1422
 */
import { existsSync, readFileSync } from 'node:fs';
import { readFile, stat } from 'node:fs/promises';
import { createServer, type IncomingMessage, type ServerResponse } from 'node:http';
import { extname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { COMPARISON_DIMENSIONS, EXTRA_DIMENSIONS, PREDICTION_DIMENSIONS, createKGReasoner } from '../src/kg-reasoner.js';
import { assessAgentAnswer, comparisonSummary, hasToolMarkup, readAgentCompletion, recoverToolCalls, resolveCompareIntent, resolvePathIntent, pathSearchSummary } from './agent-answer.js';
import { defaultAtlasSite, resolveAtlasSite } from './atlas-site.js';

const ROOT = resolve(fileURLToPath(new URL('..', import.meta.url)));

function loadEnvFiles() {
  for (const fname of ['.env.local', '.env']) {
    const p = resolve(ROOT, fname);
    if (!existsSync(p)) continue;
    for (const rawLine of readFileSync(p, 'utf8').split(/\r?\n/)) {
      const line = rawLine.trim();
      if (!line || line.startsWith('#')) continue;
      const eq = line.indexOf('=');
      if (eq <= 0) continue;
      const key = line.slice(0, eq).trim();
      const val = line.slice(eq + 1).trim().replace(/^(['"])(.*)\1$/, '$2');
      if (key && !(key in process.env)) process.env[key] = val;
    }
  }
}

loadEnvFiles();

type AgentConfig = {
  provider: 'openrouter' | 'deepseek';
  apiKey: string;
  model: string;
  completionUrl: string;
};

function agentConfig(): AgentConfig {
  const provider = process.env.ATLAS_AGENT_PROVIDER?.trim()
    || (process.env.OPENROUTER_API_KEY?.trim() ? 'openrouter' : 'deepseek');
  if (provider === 'openrouter') {
    return {
      provider,
      apiKey: process.env.OPENROUTER_API_KEY?.trim() || '',
      model: process.env.OPENROUTER_MODEL?.trim() || 'deepseek/deepseek-v3.2',
      completionUrl: 'https://openrouter.ai/api/v1/chat/completions',
    };
  }
  if (provider !== 'deepseek') throw new Error('ATLAS_AGENT_PROVIDER 须为 openrouter 或 deepseek。');
  const model = process.env.DEEPSEEK_MODEL?.trim();
  return {
    provider,
    apiKey: process.env.DEEPSEEK_API_KEY?.trim() || '',
    model: !model || ['deepseek-chat', 'deepseek-reasoner'].includes(model) ? 'deepseek-flash' : model,
    completionUrl: 'https://api.deepseek.com/v1/chat/completions',
  };
}

const MIME: Record<string, string> = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.png': 'image/png',
  '.webp': 'image/webp',
  '.svg': 'image/svg+xml',
};

const AGENT_TOOLS = [
  {
    type: 'function',
    function: {
      name: 'query_graph',
      description: '在知识图谱中按时代、材质、纹样、器类、工艺、器物名、出土地进行组合查询与否定排除（FILTER NOT EXISTS），可选是否开启 RDFS 本体子类泛化。',
      parameters: {
        type: 'object',
        properties: {
          name: { type: 'string', description: '器物名关键词' },
          period: { type: 'string', description: '所属时代，如 新石器时代、商代、西周、春秋' },
          material: { type: 'string', description: '材质，如 彩陶、青铜、铜器、玉器、陶瓷类、铜器类' },
          motif: { type: 'string', description: '纹样，如 云雷纹、鸟纹、蛙纹、龙凤纹、几何纹' },
          place: { type: 'string', description: '出土地关键词' },
          artifactType: { type: 'string', description: '器类，如盆、壶、镜、瓦当、画像石' },
          technique: { type: 'string', description: '制作工艺关键词，如模印、鎏金、镶嵌' },
          decoration_material: { type: 'string', description: '装饰材料' },
          shape: { type: 'string', description: '造型' },
          culture: { type: 'string', description: '原文明示的文化归属' },
          composition: { type: 'string', description: '构图形式，如二方连续、左右对称' },
          decoration_part: { type: 'string', description: '装饰部位，如口沿、腹部、镜背' },
          decoration_role: { type: 'string', description: '装饰角色，如主纹、地纹、边饰' },
          organization: { type: 'string', description: '原文记载的收藏单位' },
          excavationPlace: { type: 'string', description: '出土地点，区别于制作地点和收藏单位' },
          discoveryPlace: { type: 'string', description: '发现地点' },
          collectionPlace: { type: 'string', description: '采集地点' },
          excludePeriod: { type: 'string', description: '排除此时代的条目' },
          excludeMaterial: { type: 'string', description: '排除此材质的条目' },
          excludeMotif: { type: 'string', description: '排除此纹样的条目' },
          useOntology: { type: 'boolean', description: '是否启用 RDFS 本体泛化（默认 true）' },
        },
        additionalProperties: false,
      },
    },
  },
  {
    type: 'function',
    function: {
      name: 'find_paths',
      description: '在候选图谱中搜索任意两个实体之间的多跳关联路径，返回搜索条件、预算与标注覆盖率。本体泛化和图上连通不能单独证明历史传承或材质迁移。',
      parameters: {
        type: 'object',
        properties: {
          source: { type: 'string', description: '起点实体名，如 新石器时代、彩陶、云雷纹' },
          target: { type: 'string', description: '终点实体名，如 商代、青铜、龙凤纹' },
          maxHops: { type: 'number', description: '最大跳数（2-8，默认 6）' },
          useOntology: { type: 'boolean', description: '是否启用 RDFS 本体闭包（默认 true）' },
        },
        required: ['source', 'target'],
        additionalProperties: false,
      },
    },
  },
  {
    type: 'function',
    function: {
      name: 'compare_entities',
      description: '按指定维度分组，计算所选属性在两组器物中的交集、差集与标注覆盖率。启用本体时，周代包含西周、东周及其下位时期。差集不代表历史独有，共有不证明传承。',
      parameters: {
        type: 'object',
        properties: {
          kind: { type: 'string', enum: Object.keys(COMPARISON_DIMENSIONS), description: '对比维度' },
          entityA: { type: 'string', description: '实体 A 名称' },
          entityB: { type: 'string', description: '实体 B 名称' },
          axis: { type: 'string', enum: Object.keys(COMPARISON_DIMENSIONS), description: '比较这两组器物的哪个属性' },
          useOntology: { type: 'boolean', description: '是否启用 RDFS 本体归类（默认 true）' },
        },
        required: ['kind', 'entityA', 'entityB'],
        additionalProperties: false,
      },
    },
  },
  {
    type: 'function',
    function: {
      name: 'predict_missing',
      description: '根据器物间的共现关系，为所选缺失属性提出候选值及其证据链。',
      parameters: {
        type: 'object',
        properties: {
          targetPredicate: { type: 'string', enum: Object.keys(PREDICTION_DIMENSIONS), description: '要推理补全的属性' },
          artifactId: { type: 'string', description: '可选：仅对指定器物 ID 推理补全' },
          useOntology: { type: 'boolean', description: '是否启用本体泛化特征（默认 true）' },
          limit: { type: 'number', description: '返回前 N 条高置信度预测（默认 10）' },
        },
        required: ['targetPredicate'],
        additionalProperties: false,
      },
    },
  },
  {
    type: 'function',
    function: {
      name: 'run_sparql',
      description: '直接执行 SPARQL-lite 查询（支持 SELECT DISTINCT、WHERE 三元组连接、FILTER、FILTER NOT EXISTS、ORDER BY、LIMIT）。可用谓词：:period :made_of :decorated_with :period_class :made_of_class :motif_family :page :findspot rdfs:subClassOf。',
      parameters: {
        type: 'object',
        properties: {
          query: { type: 'string', description: '标准 SPARQL-lite 查询字符串' },
          useOntology: { type: 'boolean', description: '是否包含本体闭包三元组（默认 true）' },
        },
        required: ['query'],
        additionalProperties: false,
      },
    },
  },
  {
    type: 'function',
    function: {
      name: 'inspect_evidence',
      description: '查看单件器物的完整原书图注、页码出处、所有实证三元组以及缺项推导候选。',
      parameters: {
        type: 'object',
        properties: {
          artifact: { type: 'string', description: '器物 ID 或名称' },
        },
        required: ['artifact'],
        additionalProperties: false,
      },
    },
  },
];

const SYSTEM_PROMPT = `你是「中国纹样全集」的器物史与纹样史研究助手。先利用图谱工具核对器物、年代、材质或纹样，再用自然的中文直接回答问题。
按历史时期或器物用途提问时，用组合条件分别检索两组器物，再核对代表器物的图注。材质或纹样检索为空时，可以用器类、器名或原书使用的纹样异名查找。只有问题需要集合差异或路径时才使用对应工具。
选一两件最能说明问题的器物。把主要篇幅用在解释：器物用在哪里，工艺如何影响纹样，礼仪、观看场景或文化交流能否解释变化。可运用你的历史知识交代背景。用「从历史背景看」「一种可能是」等自然措辞标出背景和假说，并说明什么发现可以检验它们。图谱材料较少时，仍可提供有条件的历史解释，并说明目前能核对到哪里。
避免逐条复述数据和重复结论。通常用二至四个短段落，标题和列表按需使用。图谱事实就地用工具提供的 [E1] 等编号，图谱推论用 [R1] 等编号。背景知识可直接交代，引用编号只用于它实际对应的图谱结果。引用逐个书写，馆藏、出土信息和书目须有依据。
图谱收录的是待核对的候选记录。比较时交代标注覆盖率，从 totals 读取总数。路径的每一段有不同意义，例如共同年代只表明年代标签相同，共有题材只能提出关联线索。讨论传承和方向时，指出还需要怎样的年代、形态或交流证据。
通过 API 的 tool_calls 调用工具，最终回答只包含正文和引用。收到最终回答要求后结束调用。`;

const INSPECT_PATH_TOOL = {
  type: 'function',
  function: {
    name: 'inspect_selected_path',
    description: '返回用户选中的单条路径及其图谱证据。',
    parameters: { type: 'object', properties: {}, additionalProperties: false },
  },
};

const SHOW_COMPARISON_TOOL = {
  type: 'function',
  function: {
    name: 'show_comparison',
    description: '在星图展示本轮比较中最值得解读的记录。只能选择比较结果中给出的 displayId。',
    parameters: {
      type: 'object',
      properties: {
        items: { type: 'string', description: '1 至 8 个 displayId，用英文逗号分隔，例如 S2,A1,B3' },
      },
      required: ['items'],
      additionalProperties: false,
    },
  },
};
const COMPARE_LABELS = Object.fromEntries(Object.entries(COMPARISON_DIMENSIONS).map(([kind, dim]) => [kind, dim.label]));

type ChatMsg = { role: string; content: string | null; tool_calls?: any[]; tool_call_id?: string;
  reasoning_content?: string; reasoning?: string; reasoning_details?: unknown[] };
type AgentProgress = (event: Record<string, unknown>) => void;

export async function runDeepSeekAgent(
  reasoner: any,
  history: { role: 'user' | 'assistant'; content: string }[],
  config: AgentConfig,
  intentHint?: unknown,
  onProgress?: AgentProgress,
  signal?: AbortSignal,
) {
  const { apiKey, model, completionUrl, provider } = config;
  const t0 = Date.now();
  const summary = reasoner.getCatalogSummary();
  const selectedPath = intentHint && typeof intentHint === 'object' && 'type' in intentHint && intentHint.type === 'selected_path'
    ? intentHint as { nodeKeys?: string[]; edgeIds?: string[]; useOntology?: boolean; index?: number }
    : null;
  const compareIntent = resolveCompareIntent(intentHint);
  const pathIntent = compareIntent || selectedPath ? null : resolvePathIntent(history.at(-1)?.content || '', intentHint, summary);
  const allowedTools = selectedPath ? [INSPECT_PATH_TOOL] : compareIntent
    ? [...AGENT_TOOLS.filter(t => t.function.name === 'compare_entities'), SHOW_COMPARISON_TOOL]
    : pathIntent ? AGENT_TOOLS.filter(t => !['compare_entities', 'predict_missing'].includes(t.function.name)) : AGENT_TOOLS;
  const contextHint = `当前已加载图谱：《${summary.title}》（${summary.counts.artifacts} 件条目，${summary.counts.triples} 条来源候选边，${summary.counts.axioms} 条本体规则）。时代：${summary.eras.map((e: any) => e.name).join('、')}；主要材质：${summary.materials.slice(0, 10).map((m: any) => m.name).join('、')}。`;

  const recent = history.slice(-8);
  const prior = recent.slice(0, -1);
  const question: ChatMsg = { role: 'user', content: recent.at(-1)?.content || '' };
  // The browser retains a transcript. Only send assistant tool messages generated in this request.
  if (prior.length) question.content = `先前对话摘录（供理解上下文）\n${JSON.stringify(prior)}\n\n当前提问\n${question.content}`;
  const guidance = [`${SYSTEM_PROMPT}\n\n${contextHint}`];
  const messages: ChatMsg[] = [
    question,
  ];

  const citations = new Map<string, any>(); // tripleId -> { ref: E#, ... }
  const inferences = new Map<string, any>(); // infKey -> { ref: R#, ... }
  const trace: any[] = [];
  let thinking = '';
  let stageAction: any = null;
  let fallbackAnswer = '';
  const comparisonDisplayItems = new Map<string, string>();
  const pathSearches = new Map<string, { result: any; ref: string }>();
  const completed = (answer: string, responseMode = 'model') => ({
    model, answer, thinking, trace, citations: [...citations.values()], inferences: [...inferences.values()],
    stageAction, elapsedMs: Date.now() - t0, responseMode,
  });

  const startTool = (tool: string, args: unknown) => onProgress?.({ type: 'tool_start', tool, args });
  const finishTool = (step: any, output: any) => {
    const preview = JSON.stringify(output, null, 2);
    const result = { ...step, error: output?.error, preview: preview.length > 2400 ? `${preview.slice(0, 2400)}\n…（节选）` : preview };
    trace.push(result);
    onProgress?.({ type: 'tool_result', step: result });
  };
  const providePreflight = (tool: string, result: unknown) => {
    question.content += `\n\n本轮由服务器预先核验的图谱结果（${tool}）\n${JSON.stringify(result)}`;
  };

  const regCitation = (ev: any) => {
    const key = ev.id || `${ev.subjectId}:${ev.predicate}:${ev.objectLabel}`;
    if (!citations.has(key)) {
      const ref = `E${citations.size + 1}`;
      citations.set(key, {
        ref,
        id: key,
        artifactId: ev.subjectId,
        sourceRecordId: ev.sourceRecordId || ev.sources?.find((source: any) => source.page === ev.page)?.sourceRecordId,
        interpretationId: ev.interpretationId,
        subject: ev.subjectLabel,
        predicate: ev.predicateLabel || ev.predicate,
        object: ev.objectLabel,
        page: ev.page,
        volume: ev.volume,
        volumePage: ev.volumePage,
        sourceName: ev.sourceName,
        locator: ev.locator,
        quote: ev.quote,
        bbox: ev.bbox,
        pageUrl: ev.pageUrl,
        captionUrl: ev.captionUrl,
        origin: ev.origin,
        binding: ev.binding,
        supportingEvidence: ev.supportingEvidence,
      });
    }
    return citations.get(key).ref;
  };

  const regInference = (key: string, payload: any) => {
    if (!inferences.has(key)) {
      const ref = `R${inferences.size + 1}`;
      inferences.set(key, { ref, ...payload });
    }
    return inferences.get(key).ref;
  };

  const runCompareTool = (args: Record<string, any>) => {
    const res = reasoner.compareEntities(args.kind, args.entityA, args.entityB, {
      axis: args.axis, useOntology: args.useOntology !== false,
    });
    if (!res.ok) return { error: res.error };

    const localEv = new Map(res.evidence.map((e: any) => [e.ref, e]));
    const mapRefs = (refs: string[]) => refs.map(ref => localEv.get(ref)).filter(Boolean).map(regCitation);
    const { primary, secondary } = res;
    const axisLabel = COMPARE_LABELS[primary.axis as keyof typeof COMPARE_LABELS];
    const artifactIds = [...new Set([...res.artifactIdsA, ...res.artifactIdsB])];
    const rRef = regInference(JSON.stringify(['compare', res.kind, res.entityA, res.entityB, primary.axis, res.useOntology]), {
      type: 'compare', title: `${res.entityA} 与 ${res.entityB} · ${axisLabel}对比`,
      summary: `当前记录共有 ${primary.shared.length} 项，差集 ${primary.onlyA.length}/${primary.onlyB.length} 项。`,
      kind: res.kind, entityA: res.entityA, entityB: res.entityB, axis: primary.axis, useOntology: res.useOntology,
      jaccard: primary.jaccard, coverage: { primary: primary.coverage, secondary: secondary.coverage },
      interpretation: res.interpretation, artifactIds,
    });
    const totalsFor = (axis: any) => ({ shared: axis.shared.length, onlyA: axis.onlyA.length, onlyB: axis.onlyB.length });
    const examples = (rows: any[], limit: number, prefix?: string) => rows.slice(0, limit).map((item, i) => {
      const sample: Record<string, unknown> = { label: item.label };
      if (item.refsA) Object.assign(sample, { countA: item.countA, countB: item.countB, refsA: mapRefs(item.refsA), refsB: mapRefs(item.refsB) });
      else Object.assign(sample, { count: item.count, refs: mapRefs(item.refs) });
      if (prefix) {
        const displayId = `${prefix}${i + 1}`;
        comparisonDisplayItems.set(displayId, item.label);
        sample.displayId = displayId;
      }
      return sample;
    });
    fallbackAnswer = comparisonSummary(res, rRef, Boolean(compareIntent));
    stageAction = { overlay: 'compare', comparison: res, artifactIds };
    const limit = compareIntent ? 16 : 10;
    return {
      inferenceRef: rRef,
      kind: res.kind, entityA: res.entityA, countA: res.countA, entityB: res.entityB, countB: res.countB,
      primaryAxis: primary.axis, totals: totalsFor(primary), examplesArePartial: true,
      coverage: compareIntent ? { primary: primary.coverage } : { primary: primary.coverage, secondary: secondary.coverage },
      interpretation: res.interpretation, comparisonScope: res.comparisonScope, jaccard: primary.jaccard,
      shared: examples(primary.shared, limit, compareIntent ? 'S' : undefined),
      onlyA: examples(primary.onlyA, limit, compareIntent ? 'A' : undefined),
      onlyB: examples(primary.onlyB, limit, compareIntent ? 'B' : undefined),
      ...(!compareIntent && {
        secondaryAxis: secondary.axis,
        secondaryShared: secondary.shared.slice(0, 6).map((item: any) => item.label),
        secondary: {
          axis: secondary.axis, comparable: secondary.comparable, totals: totalsFor(secondary),
          shared: examples(secondary.shared, 6),
          onlyA: examples(secondary.onlyA, 6),
          onlyB: examples(secondary.onlyB, 6),
        },
      }),
      sparql: res.sparql,
    };
  };

  const runPathTool = (args: Record<string, any>) => {
    const boundPath = pathIntent && args.source === pathIntent.source && args.target === pathIntent.target;
    const res = reasoner.findPaths(args.source, args.target, {
      maxHops: boundPath ? pathIntent.maxHops : args.maxHops,
      useOntology: args.useOntology !== false,
      maxPaths: boundPath ? pathIntent.maxPaths : undefined,
    });
    const key = `${args.source}:${args.target}:${res.useOntology}:${res.search.maxHops}`;
    const localEv = new Map(res.evidence.map((e: any) => [e.ref, e]));
    const compactPaths = res.paths.slice(0, 6).map((p: any) => {
      const steps = p.steps.map((s: any) => ({
        from: s.fromLabel, relation: s.predicateLabel, to: s.toLabel,
        isInferred: s.isInferred, axiom: s.axiom,
        ref: s.evidenceRef ? regCitation(localEv.get(s.evidenceRef)) : null,
      }));
      const ref = regInference(`path:${key}:${p.id}`, {
        type: 'path', title: `${res.source.label} → ${res.target.label}（${p.hops} 跳关联候选）`,
        summary: p.summary, rules: p.rulesTriggered, steps: p.steps,
        artifactIds: p.artifactIds, nodeKeys: p.nodeKeys,
      });
      return { inferenceRef: ref, hops: p.hops, usesOntology: p.usesOntology,
        summary: p.summary, rules: p.rulesTriggered.map((r: any) => r.name), steps };
    });
    // A failed/empty search is a computed result too, with its own reference.
    const searchRef = regInference(`path-search:${key}`, {
      type: 'path_search', title: `${args.source} → ${args.target}（本体${res.useOntology ? '开启' : '关闭'}）`,
      summary: res.error || `本次最多 ${res.search.maxHops} 跳，找到 ${res.paths.length} 条关联候选路径。`,
      search: res.search, coverage: res.coverage, useOntology: res.useOntology,
      ok: res.ok, error: res.error, source: res.source, target: res.target, paths: res.paths,
      artifactIds: [...new Set(res.paths.flatMap((p: any) => p.artifactIds))],
    });
    if (!pathIntent || boundPath) {
      pathSearches.set(String(res.useOntology), { result: res, ref: searchRef });
      fallbackAnswer = pathSearchSummary([...pathSearches.values()]);
      const selected = [...pathSearches.values()].sort((a, b) =>
        Number(Boolean(b.result.paths.length)) - Number(Boolean(a.result.paths.length))
        || Number(b.result.useOntology) - Number(a.result.useOntology))[0].result;
      stageAction = {
        overlay: 'path', source: selected.source, target: selected.target,
        useOntology: selected.useOntology, paths: selected.paths, sparql: selected.sparql,
        artifactIds: [...new Set(selected.paths.flatMap((p: any) => p.artifactIds))],
        searchResults: [...pathSearches.values()].map(({ result: r, ref }) => ({
          ref, ok: r.ok, error: r.error, source: r.source, target: r.target,
          useOntology: r.useOntology, pathCount: r.paths.length, search: r.search, coverage: r.coverage,
        })),
      };
    }
    return {
      ok: res.ok, error: res.error, inferenceRef: searchRef,
      source: res.source.label, target: res.target.label, useOntology: res.useOntology,
      search: res.search, coverage: res.coverage, literalReachable: res.literalReachable,
      ontologyUnlocked: res.ontologyUnlocked, pathCount: res.paths.length, paths: compactPaths, sparql: res.sparql,
    };
  };

  // Bind an explicit path task before asking the model to interpret the results.
  // This also preserves a useful answer when generation fails or chooses another tool.
  let selectedPathOutput: any = null;
  if (selectedPath) {
    const tool = INSPECT_PATH_TOOL.function.name;
    const args = { nodeKeys: selectedPath.nodeKeys, edgeIds: selectedPath.edgeIds, useOntology: selectedPath.useOntology !== false };
    startTool(tool, args);
    const result = reasoner.inspectPath(args.nodeKeys, args.edgeIds, args.useOntology);
    if (!result.ok) {
      finishTool({ tool, args, count: 0, summary: '核验所选路径' }, result);
      return completed(result.error, 'symbolic');
    }
    const [path] = result.paths;
    const label = Number.isInteger(selectedPath.index) && selectedPath.index! >= 1 && selectedPath.index! <= 50
      ? `路径 ${selectedPath.index}` : '所选路径';
    const localEv = new Map(result.evidence.map((e: any) => [e.ref, e]));
    const steps = path.steps.map((step: any) => {
      const evidence = localEv.get(step.evidenceRef) as any;
      return { from: step.fromLabel, to: step.toLabel, relation: step.predicateLabel,
        reversed: step.reversed, inferred: step.isInferred, axiom: step.axiom,
        ref: evidence ? regCitation(evidence) : null, quote: evidence?.quote?.slice(0, 400) || undefined };
    });
    const ref = regInference('selected-path', { type: 'path', title: label, summary: path.summary,
      steps: path.steps, artifactIds: path.artifactIds });
    selectedPathOutput = { inferenceRef: ref, path: label, hops: path.hops, steps,
      rules: path.rulesTriggered.map((rule: any) => rule.name) };
    providePreflight(tool, selectedPathOutput);
    guidance.push('本轮只解读当前卡片选中的这条路径。说明中间器物或时代为何相连，指出哪几段有图注依据、哪几段只是共标签或归类。可以补充历史语境和其他解释，但无需搜索其他路径或泛泛解释起点和终点。');
    finishTool({ tool, args, count: 1, summary: `${label} · ${path.hops} 跳` }, selectedPathOutput);
    fallbackAnswer = `${label}（${path.hops} 跳）[${ref}]\n\n` + steps.map((step: any) =>
      `${step.from} — ${step.relation} — ${step.to}${step.ref ? `[${step.ref}]` : ''}`).join('\n\n');
    stageAction = { overlay: 'path', source: result.source, target: result.target, paths: result.paths,
      useOntology: result.useOntology, artifactIds: path.artifactIds, pathLabel: label };
  }

  if (pathIntent) {
    for (const useOntology of [false, true]) {
      const args = { source: pathIntent.source, target: pathIntent.target, maxHops: pathIntent.maxHops, useOntology };
      startTool('find_paths', args);
      const output = runPathTool(args);
      finishTool({ tool: 'find_paths', args, sparql: output.sparql, count: output.pathCount,
        summary: `${args.source} → ${args.target}（本体${args.useOntology ? '开启' : '关闭'}）` }, output);
      providePreflight('find_paths', output);
    }
    if (![...pathSearches.values()].some(x => x.result.paths.length)) {
      return completed(fallbackAnswer, 'symbolic');
    }
    guidance.push('本轮主任务已绑定为路径搜索，已计算本体关闭和开启两种模式。pathCount 是实际结果数，paths 仅供举例。解释这些结果及标注覆盖率，明确关联候选不能证明传承；不得改为集合对比或预测补全。');
  }

  if (compareIntent) startTool('compare_entities', compareIntent);
  const boundComparison = compareIntent ? runCompareTool(compareIntent) : null;
  if (compareIntent && boundComparison) {
    if (boundComparison.error) {
      finishTool({ tool: 'compare_entities', args: compareIntent, count: 0 }, boundComparison);
      return completed(boundComparison.error, 'symbolic');
    }
    providePreflight('compare_entities', boundComparison);
    finishTool({ tool: 'compare_entities', args: compareIntent, sparql: boundComparison.sparql,
      summary: `${compareIntent.entityA} 与 ${compareIntent.entityB} · ${COMPARE_LABELS[compareIntent.axis as keyof typeof COMPARE_LABELS]}`,
      count: boundComparison.totals.shared + boundComparison.totals.onlyA + boundComparison.totals.onlyB }, boundComparison);
    guidance.push('本轮比较对象、比较内容和本体设置已由页面选定。只解读 primaryAxis；有可展示的记录时，先调用 show_comparison，自主挑选最能支持解读的 displayId，然后撰写带引用的结论。展示项应与解读对应。');
  }

  const timeout = AbortSignal.timeout(120_000);
  const deadline = signal ? AbortSignal.any([timeout, signal]) : timeout;
  let retryWithResults = false;

  for (let round = 0; round < 6; round++) {
    signal?.throwIfAborted();
    const synthesisOnly = retryWithResults || round >= 4 && trace.length > 0;
    const finalize = Boolean(selectedPath) || synthesisOnly;
    const finalInstruction = finalize ? '\n\n请依据已有结果直接回答当前问题。引用实际结果中的编号，例如 [E1] 或 [R1]。结束工具调用，不输出任何工具标记。' : '';
    // A fresh turn prevents DeepSeek from continuing the preceding tool protocol.
    const input = synthesisOnly ? [{
      role: 'user',
      content: question.content + '\n\n本轮已执行的工具结果（每行一条）\n'
        + messages.filter(message => message.role === 'tool').map(message => message.content).join('\n'),
    }] : messages;
    const body: Record<string, unknown> = {
      model,
      messages: [{ role: 'system', content: guidance.join('\n\n') + finalInstruction }, ...input],
      stream: true,
      max_tokens: 8192,
    };
    if (!synthesisOnly) {
      body.tools = allowedTools;
      body.tool_choice = finalize ? 'none' : 'auto';
    }
    if (provider === 'openrouter') {
      body.provider = { require_parameters: true };
      body.reasoning = { enabled: true, effort: 'medium' };
    } else {
      body.thinking = { type: 'enabled' };
      body.reasoning_effort = 'high';
    }

    onProgress?.({ type: 'model_wait' });
    let choice;
    let firstThinking = true;
    try {
      const resp = await fetch(completionUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${apiKey}` },
        signal: deadline,
        body: JSON.stringify(body),
      });
      if (!resp.ok) {
        const errBody = await resp.text().catch(() => '');
        throw new Error(`${provider === 'openrouter' ? 'OpenRouter' : 'DeepSeek'} API 返回 HTTP ${resp.status}${errBody ? `：${errBody.slice(0, 180)}` : ''}`);
      }
      choice = await readAgentCompletion(resp, (text: string) => {
        const delta = firstThinking && thinking ? `\n\n${text}` : text;
        firstThinking = false;
        thinking += delta;
        onProgress?.({ type: 'thinking', delta });
      }, (name: string) => {
        if (allowedTools.some(tool => tool.function.name === name)) onProgress?.({ type: 'tool_pending', tool: name });
      });
    } catch (error) {
      if (fallbackAnswer && timeout.aborted) return completed(fallbackAnswer, 'tool_summary');
      throw error;
    }

    const msg: ChatMsg | undefined = choice?.message;
    if (!msg) throw new Error('DeepSeek 返回空消息。');
    if (!finalize && !msg.tool_calls?.length && hasToolMarkup(msg.content)) {
      try {
        const recovered = recoverToolCalls(msg.content, allowedTools, `dsml_${round}`);
        if (recovered.length) {
          msg.tool_calls = recovered;
          msg.content = null;
        }
      } catch {
        // Invalid or incomplete protocol content is handled by the final-answer guard.
      }
    }

    if (synthesisOnly || !msg.tool_calls?.length) {
      const validE = new Set([...citations.values()].map(c => c.ref));
      const validR = new Set([...inferences.values()].map(r => r.ref));
      const verdict = assessAgentAnswer(msg, choice.finish_reason, {
        citations: validE, inferences: validR, toolCount: trace.length,
      });
      if (!verdict.ok) {
        console.warn('[atlas-agent] Answer rejected:', { round, reason: verdict.reason, tools: trace.map(step => step.tool) });
        if (round === 5) {
          if (fallbackAnswer) return completed(fallbackAnswer, 'tool_summary');
          throw new Error('模型未生成完整且引用有效的结论，请使用符号推演查看已计算结果。');
        }
        retryWithResults = validE.size > 0 || validR.size > 0 || trace.some(step => !step.error);
        guidance.push(retryWithResults
          ? `上一次回答未通过核验（${verdict.reason}）。依据下方工具结果重写，引用须逐个写成 [E编号] 或 [R编号]，只能使用结果中出现的编号。`
          : '请先使用 API tool_calls 检索相关图谱证据，再回答问题。');
        continue;
      }
      if (comparisonDisplayItems.size && !stageAction?.displayLabels && !finalize) {
        guidance.push('请先调用 show_comparison 选择要展示的记录，再提交解读。');
        continue;
      }
      return completed(verdict.answer);
    }

    const toolCalls = msg.tool_calls.slice(0, 4);
    messages.push({ ...msg, role: 'assistant', content: msg.content || null, tool_calls: toolCalls });

    for (const call of toolCalls) {
      const toolName = call.function?.name;
      let args: Record<string, any> = {};
      let toolOutput: any = { error: '参数解析失败' };
      let traceSummary = '';
      let hitCount = 0;
      let sparql = '';
      let started = false;

      try {
        args = JSON.parse(call.function?.arguments || '{}');
        if (toolName === 'compare_entities' && compareIntent) args = { ...args, ...compareIntent };
        startTool(toolName, args);
        started = true;
        if (!allowedTools.some(t => t.function.name === toolName)) {
          throw new Error(pathIntent || selectedPath ? '该工具不属于本轮路径任务，请解释已计算的路径结果。' : '该工具不适用于本轮比较，请解读已计算的结果。');
        }
        if (toolName === INSPECT_PATH_TOOL.function.name && selectedPathOutput) {
          toolOutput = selectedPathOutput;
          traceSummary = '核验所选路径';
          hitCount = 1;
        } else if (toolName === 'query_graph') {
          const res = reasoner.queryArtifacts(args);
          const evById = new Map(res.evidence.map((e: any) => [e.ref, e]));
          hitCount = res.count;
          const queryDimensions = { era: args.period, material: args.material, motif: args.motif, artifact_type: args.artifactType,
            ...Object.fromEntries(Object.keys(EXTRA_DIMENSIONS).map(kind => [kind, args[kind]])) };
          traceSummary = [...Object.values(queryDimensions), args.name].filter(Boolean).join(' · ') || '全图检索';
          toolOutput = {
            count: res.count,
            useOntology: res.useOntology,
            items: res.items.slice(0, 10).map((it: any) => ({
              id: it.id, title: it.title, page: it.page,
              volume: it.volume, volumePage: it.volumePage, sourceName: it.sourceName,
              periods: it.periods, materials: it.materials, motifs: it.motifs, artifactTypes: it.artifactTypes,
              ...Object.fromEntries(Object.values(EXTRA_DIMENSIONS).map(dim => [dim.field, it[dim.field]])),
              evidenceRefs: it.refs.slice(0, 5).map((r: string) => regCitation(evById.get(r))).filter(Boolean),
            })),
          };
          if (!stageAction && res.items.length) {
            const focus = Object.entries(queryDimensions).find(([, value]) => value);
            stageAction = {
              overlay: 'highlight',
              label: traceSummary,
              artifactIds: res.items.slice(0, 30).map((i: any) => i.id),
              focusKind: focus?.[0] || null,
              focusId: focus?.[1] || null,
            };
          }
        } else if (toolName === 'find_paths') {
          toolOutput = runPathTool(args);
          sparql = toolOutput.sparql || '';
          hitCount = toolOutput.pathCount;
          traceSummary = `${args.source} → ${args.target}${args.useOntology === false ? '（字面）' : '（本体）'}`;
        } else if (toolName === 'compare_entities') {
          toolOutput = boundComparison ?? runCompareTool(args);
          sparql = toolOutput.sparql || '';
          traceSummary = `${args.entityA} 与 ${args.entityB}`;
          const totals = toolOutput.totals;
          if (totals) hitCount = totals.shared + totals.onlyA + totals.onlyB;
        } else if (toolName === 'show_comparison') {
          const ids = typeof args?.items === 'string' && args.items.length <= 80
            ? [...new Set(args.items.split(',').map(id => id.trim()))] : [];
          if (!ids.length || ids.length > 8 || ids.some(id => !comparisonDisplayItems.has(id))) {
            throw new Error('请选择比较结果中给出的 1 至 8 个 displayId。');
          }
          const displayLabels = ids.map(id => comparisonDisplayItems.get(id));
          stageAction = { ...stageAction, displayLabels };
          toolOutput = { displayed: displayLabels };
          traceSummary = displayLabels.join('、');
          hitCount = ids.length;
        } else if (toolName === 'predict_missing') {
          const res = reasoner.predictMissing({
            targetPredicate: args.targetPredicate,
            artifactId: args.artifactId,
            useOntology: args.useOntology !== false,
            limit: args.limit || 8,
          });
          if (!res.ok) throw new Error(res.error);
          sparql = res.sparql || '';
          traceSummary = `推理补全 ${args.targetPredicate}`;
          hitCount = res.predictions.length;
          const localEv = new Map(res.evidence.map((e: any) => [e.ref, e]));
          const mapped = res.predictions.slice(0, 8).map((p: any) => {
            const supMapped = p.supporters.map((s: any) => ({
              title: s.title, page: s.page,
              volume: s.volume, volumePage: s.volumePage, sourceName: s.sourceName,
              ref: s.ref && localEv.has(s.ref) ? regCitation(localEv.get(s.ref)) : null,
            }));
            const rRef = regInference(`pred:${p.artifactId}:${p.predicate}:${p.predictedValue}`, {
              type: 'prediction',
              title: `${p.artifactTitle} ⇒ ${p.predictedValue}`,
              summary: p.explanation,
              artifactId: p.artifactId,
              artifactIds: [p.artifactId],
              predicate: p.predicate,
              predictedValue: p.predictedValue,
              confidence: p.confidence,
              lift: p.lift,
              ruleFormula: p.ruleFormula,
              supporters: supMapped,
            });
            return {
              inferenceRef: rRef,
              artifactId: p.artifactId,
              artifactTitle: p.artifactTitle,
              page: p.page,
              volume: p.volume, volumePage: p.volumePage, sourceName: p.sourceName,
              predictedValue: p.predictedValue,
              confidence: p.confidence,
              lift: p.lift,
              ruleFormula: p.ruleFormula,
              supporters: supMapped,
            };
          });
          toolOutput = {
            targetPredicate: res.targetPredicate,
            totalMissing: res.totalMissing,
            predictions: mapped,
          };
          if (!pathIntent && res.predictions.length) {
            stageAction = {
              overlay: 'predict',
              targetPredicate: res.targetPredicate,
              predictions: res.predictions.slice(0, 12),
              artifactIds: res.predictions.slice(0, 12).map((p: any) => p.artifactId),
            };
          }
        } else if (toolName === 'run_sparql') {
          const res = reasoner.runSparql(args.query, { useOntology: args.useOntology !== false });
          sparql = args.query || '';
          traceSummary = 'SPARQL 执行';
          if (!res.ok) {
            toolOutput = { error: res.error };
          } else {
            hitCount = res.rows.length;
            const refs = res.evidence.slice(0, 12).map((e: any) => regCitation(e));
            toolOutput = {
              variables: res.variables,
              rowCount: res.rows.length,
              rows: res.rows.slice(0, 18),
              plan: res.plan,
              evidenceRefs: refs,
            };
            if (!stageAction && res.matchedArtifactIds.length) {
              stageAction = {
                overlay: 'highlight',
                label: 'SPARQL 查询命中',
                artifactIds: res.matchedArtifactIds.slice(0, 30),
                sparql: args.query,
              };
            }
          }
        } else if (toolName === 'inspect_evidence') {
          const res = reasoner.inspectEvidence(args.artifact);
          traceSummary = `核验 ${args.artifact}`;
          if (!res.ok) {
            toolOutput = { error: res.error };
          } else {
            hitCount = res.evidence.length;
            toolOutput = {
              id: res.artifact.id,
              title: res.artifact.title,
              page: res.artifact.page,
              volume: res.artifact.volume,
              volumePage: res.artifact.volumePage,
              sourceName: res.artifact.sourceName,
              locator: res.artifact.locator,
              findspot: res.artifact.findspot,
              quote: res.artifact.quote,
              facts: res.evidence.map((e: any) => ({
                ref: regCitation(e),
                predicate: e.predicateLabel,
                object: e.objectLabel,
                page: e.page,
                volume: e.volume, volumePage: e.volumePage, sourceName: e.sourceName,
              })),
              predictions: res.predictions.map((p: any) => ({
                inferenceRef: regInference(`pred:${p.artifactId}:${p.predicate}:${p.predictedValue}`, {
                  type: 'prediction', title: `${p.artifactTitle} ⇒ ${p.predictedValue}`,
                  summary: p.explanation, artifactId: p.artifactId, artifactIds: [p.artifactId],
                  confidence: p.confidence, lift: p.lift, ruleFormula: p.ruleFormula,
                }),
                predicate: p.predicateLabel,
                predictedValue: p.predictedValue,
                confidence: p.confidence,
                ruleFormula: p.ruleFormula,
              })),
            };
          }
        } else {
          toolOutput = { error: `未知工具：${toolName}` };
        }
      } catch (e: any) {
        toolOutput = { error: e?.message || '工具执行异常' };
      }

      if (!started) startTool(toolName, args);
      finishTool({ tool: toolName, summary: traceSummary, count: hitCount, args, sparql }, toolOutput);
      messages.push({ role: 'tool', tool_call_id: call.id, content: JSON.stringify(toolOutput) });
    }
  }

  if (fallbackAnswer) return completed(fallbackAnswer, 'tool_summary');
  throw new Error('DeepSeek 推理轮次达到上限，请缩小问题范围。');
}

function parseCliArgs() {
  const args = process.argv.slice(2);
  let port = Number(process.env.PORT || 1422);
  let host = process.env.HOST || '127.0.0.1';
  let siteDir = process.env.ATLAS_SITE_DIR || defaultAtlasSite(ROOT);

  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--port' && args[i + 1]) port = Number(args[++i]);
    else if (args[i] === '--host' && args[i + 1]) host = args[++i];
    else if (args[i] === '--site' && args[i + 1]) siteDir = resolve(args[++i]);
  }
  return { port, host, siteDir: resolveAtlasSite(siteDir) };
}

async function readJsonBody(req: IncomingMessage, maxBytes = 64_000): Promise<any> {
  let body = '';
  for await (const chunk of req) {
    body += chunk.toString('utf8');
    if (body.length > maxBytes) throw new Error('请求体过大');
  }
  return body ? JSON.parse(body) : {};
}

function sendJson(res: ServerResponse, status: number, payload: unknown) {
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'no-store',
  });
  res.end(JSON.stringify(payload));
}

function loadSiteKG(siteDir: string) {
  const manifestPath = resolve(siteDir, 'manifest.json');
  const graphPath = resolve(siteDir, 'graph.json');
  const dataPath = existsSync(manifestPath) ? manifestPath : (existsSync(graphPath) ? graphPath : null);
  if (!dataPath) throw new Error(`目录 ${siteDir} 中未找到 manifest.json 或 graph.json`);
  const rawText = readFileSync(dataPath, 'utf8');
  const parsed = JSON.parse(rawText);
  const reasoner = createKGReasoner(parsed);
  return { dataPath, rawText, parsed, reasoner };
}

async function main() {
  const { port, host, siteDir } = parseCliArgs();
  const config = agentConfig();
  const { apiKey, model, provider } = config;
  const templatePath = resolve(ROOT, 'scripts/atlas_viewer.html');
  const reasonerJsPath = resolve(ROOT, 'src/kg-reasoner.js');

  const { dataPath, rawText, reasoner } = loadSiteKG(siteDir);
  const summary = reasoner.getCatalogSummary();

  const server = createServer((req, res) => {
    void (async () => {
      const url = new URL(req.url || '/', `http://${host}:${port}`);
      const pathname = decodeURIComponent(url.pathname);

      // 1) Status & dynamic metadata API
      if (req.method === 'GET' && pathname === '/api/kg/status') {
        sendJson(res, 200, {
          ready: true,
          deepseekReady: Boolean(apiKey),
          agentProvider: provider,
          thinkingEnabled: true,
          model,
          ...summary,
        });
        return;
      }

      // 2) Mode A: Symbolic Reasoning API (also runs locally in browser)
      if (req.method === 'POST' && pathname === '/api/kg/reason') {
        const body = await readJsonBody(req);
        const action = body.action;
        if (action === 'path') {
          sendJson(res, 200, reasoner.findPaths(body.source, body.target, body));
        } else if (action === 'compare') {
          sendJson(res, 200, reasoner.compareEntities(body.kind, body.entityA, body.entityB, body));
        } else if (action === 'predict') {
          sendJson(res, 200, reasoner.predictMissing(body));
        } else if (action === 'sparql') {
          sendJson(res, 200, reasoner.runSparql(body.query, body));
        } else if (action === 'interpretations') {
          sendJson(res, 200, reasoner.queryInterpretations(body));
        } else if (action === 'query') {
          sendJson(res, 200, reasoner.queryArtifacts(body));
        } else if (action === 'evidence') {
          sendJson(res, 200, reasoner.inspectEvidence(body.artifact));
        } else {
          sendJson(res, 400, { ok: false, error: '未知推理动作' });
        }
        return;
      }

      // 3) Mode B: DeepSeek Neuro-Symbolic Agent API
      if (req.method === 'POST' && pathname === '/api/kg/agent') {
        if (!apiKey) {
          const keyName = provider === 'openrouter' ? 'OPENROUTER_API_KEY' : 'DEEPSEEK_API_KEY';
          sendJson(res, 503, { error: `服务端未配置 ${keyName}，请在 .env.local 或环境变量中设置。` });
          return;
        }
        const body = await readJsonBody(req);
        const msgs = body.messages;
        if (!Array.isArray(msgs) || !msgs.length || msgs.at(-1)?.role !== 'user') {
          sendJson(res, 400, { error: '请提供有效的对话消息数组。' });
          return;
        }
        const cleaned = msgs.slice(-8).map((m: any) => ({
          role: m.role === 'assistant' ? 'assistant' as const : 'user' as const,
          content: String(m.content || '').slice(0, 2000),
        }));
        if (req.headers.accept?.includes('application/x-ndjson')) {
          const controller = new AbortController();
          res.once('close', () => controller.abort());
          res.writeHead(200, { 'Content-Type': 'application/x-ndjson; charset=utf-8', 'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no' });
          res.flushHeaders();
          const emit: AgentProgress = event => {
            if (!res.destroyed) res.write(`${JSON.stringify(event)}\n`);
          };
          try {
            const result = await runDeepSeekAgent(reasoner, cleaned, config, body.intent, emit, controller.signal);
            emit({ type: 'done', result });
          } catch (error) {
            if (!controller.signal.aborted) {
              emit({ type: 'error', error: error instanceof Error ? error.message : '服务端处理异常' });
            }
          } finally {
            res.end();
          }
        } else {
          const result = await runDeepSeekAgent(reasoner, cleaned, config, body.intent);
          sendJson(res, 200, result);
        }
        return;
      }

      // 4) Dynamic live HTML assembly (re-reads template on each request so updates apply instantly!)
      if (req.method === 'GET' && (pathname === '/' || pathname === '/index.html')) {
        const [template, reasonerSrc] = await Promise.all([
          readFile(templatePath, 'utf8'),
          readFile(reasonerJsPath, 'utf8'),
        ]);
        const inlineReasoner = reasonerSrc.replace(/^export\s+/gm, '');
        const html = template
          .replace('__REASONER_JS__', () => inlineReasoner)
          .replace('__MANIFEST_JSON__', () => rawText.replace(/</g, '\\u003c'));
        res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-cache' });
        res.end(html);
        return;
      }

      // 4b) Serve page scan images when running directly against a raw graph.json directory
      const pageRoute = pathname.match(/^\/api\/reasoning\/page\/(\d{1,5})$/);
      if (req.method === 'GET' && pageRoute) {
        const pnum = pageRoute[1];
        const padded = pnum.padStart(4, '0');
        const candidates = [
          resolve(siteDir, 'images', `v1-p${padded}.source.jpg`),
          resolve(siteDir, 'images', `v1-p${padded}.source.png`),
          resolve(siteDir, 'images', `v1-p${padded}.source.jpeg`),
          resolve(siteDir, 'images', `v1-p${padded}.png`),
          resolve(siteDir, 'assets', `p${pnum}.jpg`),
        ];
        for (const full of candidates) {
          const st = await stat(full).catch(() => null);
          if (st?.isFile()) {
            const data = await readFile(full);
            res.writeHead(200, { 'Content-Type': MIME[extname(full).toLowerCase()] || 'image/png', 'Cache-Control': 'public, max-age=300' });
            res.end(data);
            return;
          }
        }
        res.writeHead(404); res.end('Page image not found'); return;
      }

      // 5) Static assets inside siteDir (strict path containment)
      if (req.method === 'GET') {
        const rel = pathname.replace(/^\/+/, '');
        const full = resolve(siteDir, rel);
        if (!full.startsWith(siteDir + '/') && full !== siteDir) {
          res.writeHead(403); res.end('Forbidden'); return;
        }
        const st = await stat(full).catch(() => null);
        if (st?.isFile()) {
          const data = await readFile(full);
          const mime = MIME[extname(full).toLowerCase()] || 'application/octet-stream';
          res.writeHead(200, { 'Content-Type': mime, 'Cache-Control': 'public, max-age=300' });
          res.end(data);
          return;
        }
      }

      res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
      res.end('Not Found');
    })().catch((err: any) => {
      console.error('[atlas-server]', err);
      sendJson(res, 502, { error: err?.message || '服务端处理异常' });
    });
  });

  server.listen(port, host, () => {
    console.log(`[atlas-server] Listening on http://${host}:${port}/`);
    console.log(`[atlas-server] Data: ${dataPath} (${summary.counts.artifacts} items, ${summary.counts.triples} triples, ${summary.counts.axioms} axioms)`);
    console.log(`[atlas-server] Agent: ${apiKey ? `ENABLED (${provider} / ${model})` : `DISABLED (${provider} API key missing)`}`);
  });
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch(err => {
    console.error(err);
    process.exit(1);
  });
}
