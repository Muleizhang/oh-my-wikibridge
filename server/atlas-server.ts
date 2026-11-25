/**
 * Unified Atlas & Neuro-Symbolic DeepSeek Agent Server.
 * Zero external runtime dependencies — runs natively on Node.js 22+/24+:
 *   node server/atlas-server.ts --port 1422 --site data/local-kg/atlas-100/site
 */
import { existsSync, readFileSync } from 'node:fs';
import { readFile, stat } from 'node:fs/promises';
import { createServer, type IncomingMessage, type ServerResponse } from 'node:http';
import { extname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createKGReasoner } from '../src/kg-reasoner.js';

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
      description: '在知识图谱中按时代、材质、纹样、器物名、出土地进行组合查询与否定排除（FILTER NOT EXISTS），可选是否开启 RDFS 本体子类泛化。',
      parameters: {
        type: 'object',
        properties: {
          name: { type: 'string', description: '器物名关键词' },
          period: { type: 'string', description: '所属时代，如 新石器时代、商代、西周、春秋' },
          material: { type: 'string', description: '材质，如 彩陶、青铜、铜器、玉器、陶瓷类、铜器类' },
          motif: { type: 'string', description: '纹样，如 云雷纹、鸟纹、蛙纹、龙凤纹、几何纹' },
          place: { type: 'string', description: '出土地关键词' },
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
      description: '在图谱中搜索任意两个实体（时代、材质、纹样、器物）之间的多跳语义演化路径，并自动触发跨时代传承、跨材质迁移与本体闭包规则。',
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
      description: '对两个时代、两种材质或两种纹样进行集合交集（延续/共有）、差集（独有 / FILTER NOT EXISTS）与 Jaccard 相似度对比推理。',
      parameters: {
        type: 'object',
        properties: {
          kind: { type: 'string', enum: ['era', 'material', 'motif'], description: '对比维度' },
          entityA: { type: 'string', description: '实体 A 名称' },
          entityB: { type: 'string', description: '实体 B 名称' },
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
      description: '运行无 LLM 的关联规则挖掘（Confidence / Lift）与 Adamic-Adar 共同邻居链接预测，为缺失时代、材质或纹样的条目推导高置信度候选补全及证明链。',
      parameters: {
        type: 'object',
        properties: {
          targetPredicate: { type: 'string', enum: ['period', 'made_of', 'decorated_with'], description: '要推理补全的属性' },
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

const SYSTEM_PROMPT = `你是「中国纹样知识图谱」的神经-符号推理智能体（Neuro-Symbolic KG Agent）。
核心规则：
1. 必须先调用图谱符号推理工具获取事实与推论，允许多轮、多工具协同（如先 compare_entities 再 find_paths，或用 predict_missing 补全缺项，必要时可用 run_sparql）。
2. 所有实证事实必须就地标注工具返回的实证编号 [E1]、[E2] 等；所有符号路径、对比结论或缺失补全推论必须标注推论编号 [R1]、[R2] 等。
3. 严禁编造任何未在工具结果中出现的 [E#] 或 [R#] 编号，严禁使用书外常识冒充图谱实证；若图谱无相关证据，直接说明「当前图谱未载」。
4. 明确区分【原书实证】与【规则推论】（如本体泛化、关联规则置信度与提升度）。
5. 中文回答简洁精炼、分点清晰，避免冗长客套，让学者一眼看清结论、推导链与原页依据。`;

type ChatMsg = { role: string; content: string | null; tool_calls?: any[]; tool_call_id?: string };

async function runDeepSeekAgent(
  reasoner: any,
  history: { role: 'user' | 'assistant'; content: string }[],
  apiKey: string,
  model: string,
) {
  const t0 = Date.now();
  const summary = reasoner.getCatalogSummary();
  const contextHint = `当前已加载图谱：《${summary.title}》（${summary.counts.artifacts} 件条目，${summary.counts.triples} 条实证边，${summary.counts.axioms} 条本体公理）。时代：${summary.eras.map((e: any) => e.name).join('、')}；主要材质：${summary.materials.slice(0, 10).map((m: any) => m.name).join('、')}。`;

  const messages: ChatMsg[] = [
    { role: 'system', content: `${SYSTEM_PROMPT}\n\n${contextHint}` },
    ...history.slice(-8),
  ];

  const citations = new Map<string, any>(); // tripleId -> { ref: E#, ... }
  const inferences = new Map<string, any>(); // infKey -> { ref: R#, ... }
  const trace: any[] = [];
  let stageAction: any = null;

  const regCitation = (ev: any) => {
    const key = ev.id || `${ev.subjectId}:${ev.predicate}:${ev.objectLabel}`;
    if (!citations.has(key)) {
      const ref = `E${citations.size + 1}`;
      citations.set(key, {
        ref,
        id: key,
        artifactId: ev.subjectId,
        subject: ev.subjectLabel,
        predicate: ev.predicateLabel || ev.predicate,
        object: ev.objectLabel,
        page: ev.page,
        locator: ev.locator,
        quote: ev.quote,
        bbox: ev.bbox,
        pageUrl: ev.pageUrl,
        captionUrl: ev.captionUrl,
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

  const deadline = AbortSignal.timeout(60_000);

  for (let round = 0; round < 6; round++) {
    const body: Record<string, unknown> = {
      model,
      messages,
      temperature: 0.1,
      max_tokens: 1400,
    };
    if (round < 5) {
      body.tools = AGENT_TOOLS;
      body.tool_choice = round === 0 ? 'required' : 'auto';
    } else {
      body.tool_choice = 'none';
    }

    const resp = await fetch('https://api.deepseek.com/v1/chat/completions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${apiKey}` },
      signal: deadline,
      body: JSON.stringify(body),
    });

    if (!resp.ok) {
      const errBody = await resp.text().catch(() => '');
      throw new Error(`DeepSeek API 返回 HTTP ${resp.status}${errBody ? `：${errBody.slice(0, 180)}` : ''}`);
    }

    const data = await resp.json() as { choices?: { message: ChatMsg }[] };
    const msg = data.choices?.[0]?.message;
    if (!msg) throw new Error('DeepSeek 返回空消息。');

    if (!msg.tool_calls?.length) {
      const answer = (msg.content || '').trim();
      const validE = new Set([...citations.values()].map(c => c.ref));
      const validR = new Set([...inferences.values()].map(r => r.ref));
      const badE = [...answer.matchAll(/\[(E\d+)\]/g)].map(m => m[1]).filter(id => !validE.has(id));
      const badR = [...answer.matchAll(/\[(R\d+)\]/g)].map(m => m[1]).filter(id => !validR.has(id));

      if ((badE.length || badR.length) && round < 5) {
        messages.push({ role: 'assistant', content: answer });
        messages.push({
          role: 'user',
          content: `核验失败：引用 ${[...badE, ...badR].join('、')} 不在工具结果中。请仅使用已返回的合法编号（实证：${[...validE].join('、') || '无'}；推论：${[...validR].join('、') || '无'}）重写简洁回答。`,
        });
        continue;
      }

      return {
        model,
        answer: answer || '当前图谱工具返回不足以回答该问题。',
        trace,
        citations: [...citations.values()],
        inferences: [...inferences.values()],
        stageAction,
        elapsedMs: Date.now() - t0,
      };
    }

    messages.push({ role: 'assistant', content: msg.content, tool_calls: msg.tool_calls });

    for (const call of msg.tool_calls.slice(0, 4)) {
      const toolName = call.function?.name;
      let args: Record<string, any> = {};
      let toolOutput: any = { error: '参数解析失败' };
      let traceSummary = '';
      let hitCount = 0;
      let sparql = '';

      try {
        args = JSON.parse(call.function?.arguments || '{}');
        if (toolName === 'query_graph') {
          const res = reasoner.queryArtifacts(args);
          const evById = new Map(res.evidence.map((e: any) => [e.ref, e]));
          hitCount = res.count;
          traceSummary = [args.period, args.material, args.motif, args.name].filter(Boolean).join(' · ') || '全图检索';
          toolOutput = {
            count: res.count,
            useOntology: res.useOntology,
            items: res.items.slice(0, 10).map((it: any) => ({
              id: it.id, title: it.title, page: it.page,
              periods: it.periods, materials: it.materials, motifs: it.motifs,
              evidenceRefs: it.refs.slice(0, 5).map((r: string) => regCitation(evById.get(r))).filter(Boolean),
            })),
          };
          if (!stageAction && res.items.length) {
            stageAction = {
              overlay: 'highlight',
              label: traceSummary,
              artifactIds: res.items.slice(0, 30).map((i: any) => i.id),
              focusKind: args.motif ? 'motif' : (args.material ? 'material' : (args.period ? 'era' : null)),
              focusId: args.motif || args.material || args.period || null,
            };
          }
        } else if (toolName === 'find_paths') {
          const res = reasoner.findPaths(args.source, args.target, {
            maxHops: args.maxHops,
            useOntology: args.useOntology !== false,
            maxPaths: 4,
          });
          sparql = res.sparql || '';
          traceSummary = `${args.source} → ${args.target}${args.useOntology === false ? '（字面）' : '（本体）'}`;
          if (!res.ok) {
            toolOutput = { error: res.error };
          } else {
            hitCount = res.paths.length;
            const localEv = new Map(res.evidence.map((e: any) => [e.ref, e]));
            const compactPaths = res.paths.map((p: any) => {
              const stepRefs = p.steps.map((s: any) => ({
                from: s.fromLabel,
                relation: s.predicateLabel,
                to: s.toLabel,
                isInferred: s.isInferred,
                axiom: s.axiom,
                ref: s.evidenceRef ? regCitation(localEv.get(s.evidenceRef)) : null,
              }));
              const rRef = regInference(`path:${res.source.key}:${res.target.key}:${p.id}`, {
                type: 'path',
                title: `${res.source.label} → ${res.target.label}（${p.hops} 跳）`,
                summary: p.summary,
                rules: p.rulesTriggered,
                steps: p.steps,
                artifactIds: p.artifactIds,
                nodeKeys: p.nodeKeys,
              });
              return { inferenceRef: rRef, hops: p.hops, usesOntology: p.usesOntology, summary: p.summary, rules: p.rulesTriggered.map((r: any) => r.name), steps: stepRefs };
            });
            toolOutput = {
              source: res.source.label,
              target: res.target.label,
              useOntology: res.useOntology,
              literalReachable: res.literalReachable,
              ontologyUnlocked: res.ontologyUnlocked,
              paths: compactPaths,
              sparql: res.sparql,
            };
            if (res.paths.length) {
              stageAction = {
                overlay: 'path',
                source: res.source,
                target: res.target,
                useOntology: res.useOntology,
                paths: res.paths,
                sparql: res.sparql,
                artifactIds: [...new Set(res.paths.flatMap((p: any) => p.artifactIds))],
              };
            }
          }
        } else if (toolName === 'compare_entities') {
          const res = reasoner.compareEntities(args.kind, args.entityA, args.entityB, { useOntology: args.useOntology !== false });
          sparql = res.sparql || '';
          traceSummary = `${args.entityA} vs ${args.entityB}`;
          if (!res.ok) {
            toolOutput = { error: res.error };
          } else {
            hitCount = res.primary.shared.length + res.primary.onlyA.length + res.primary.onlyB.length;
            const localEv = new Map(res.evidence.map((e: any) => [e.ref, e]));
            const mapRefs = (arr: string[]) => arr.map(r => regCitation(localEv.get(r))).filter(Boolean);
            const rRef = regInference(`cmp:${res.kind}:${res.entityA}:${res.entityB}`, {
              type: 'compare',
              title: `${res.entityA} vs ${res.entityB}`,
              summary: `共有 ${res.primary.shared.length} 项（Jaccard ${res.primary.jaccard}），仅 ${res.entityA} 独有 ${res.primary.onlyA.length} 项，仅 ${res.entityB} 独有 ${res.primary.onlyB.length} 项。`,
              kind: res.kind,
              entityA: res.entityA,
              entityB: res.entityB,
              jaccard: res.primary.jaccard,
              artifactIds: [...new Set([...res.artifactIdsA, ...res.artifactIdsB])],
            });
            toolOutput = {
              inferenceRef: rRef,
              kind: res.kind,
              entityA: res.entityA, countA: res.countA,
              entityB: res.entityB, countB: res.countB,
              primaryAxis: res.primary.axis,
              jaccard: res.primary.jaccard,
              shared: res.primary.shared.slice(0, 10).map((x: any) => ({ label: x.label, countA: x.countA, countB: x.countB, refsA: mapRefs(x.refsA), refsB: mapRefs(x.refsB) })),
              onlyA: res.primary.onlyA.slice(0, 10).map((x: any) => ({ label: x.label, count: x.count, refs: mapRefs(x.refs) })),
              onlyB: res.primary.onlyB.slice(0, 10).map((x: any) => ({ label: x.label, count: x.count, refs: mapRefs(x.refs) })),
              secondaryAxis: res.secondary.axis,
              secondaryShared: res.secondary.shared.slice(0, 6).map((x: any) => x.label),
              sparql: res.sparql,
            };
            stageAction = {
              overlay: 'compare',
              comparison: res,
              artifactIds: [...new Set([...res.artifactIdsA, ...res.artifactIdsB])],
            };
          }
        } else if (toolName === 'predict_missing') {
          const res = reasoner.predictMissing({
            targetPredicate: args.targetPredicate,
            artifactId: args.artifactId,
            useOntology: args.useOntology !== false,
            limit: args.limit || 8,
          });
          sparql = res.sparql || '';
          traceSummary = `推理补全 ${args.targetPredicate}`;
          hitCount = res.predictions.length;
          const localEv = new Map(res.evidence.map((e: any) => [e.ref, e]));
          const mapped = res.predictions.slice(0, 8).map((p: any) => {
            const supMapped = p.supporters.map((s: any) => ({
              title: s.title, page: s.page,
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
          if (res.predictions.length) {
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
              locator: res.artifact.locator,
              findspot: res.artifact.findspot,
              quote: res.artifact.quote,
              facts: res.evidence.map((e: any) => ({
                ref: regCitation(e),
                predicate: e.predicateLabel,
                object: e.objectLabel,
                page: e.page,
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

      trace.push({ tool: toolName, summary: traceSummary, count: hitCount, args, sparql });
      messages.push({ role: 'tool', tool_call_id: call.id, content: JSON.stringify(toolOutput) });
    }
  }

  throw new Error('DeepSeek 推理轮次达到上限，请缩小问题范围。');
}

function parseCliArgs() {
  const args = process.argv.slice(2);
  let port = Number(process.env.PORT || 1422);
  let host = process.env.HOST || '127.0.0.1';
  let siteDir = process.env.ATLAS_SITE_DIR || resolve(ROOT, 'data/local-kg/atlas-100/site');

  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--port' && args[i + 1]) port = Number(args[++i]);
    else if (args[i] === '--host' && args[i + 1]) host = args[++i];
    else if (args[i] === '--site' && args[i + 1]) siteDir = resolve(args[++i]);
  }
  return { port, host, siteDir };
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
  const apiKey = process.env.DEEPSEEK_API_KEY?.trim() || '';
  const model = process.env.DEEPSEEK_MODEL?.trim() || 'deepseek-chat';
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
          sendJson(res, 503, { error: '服务端未配置 DEEPSEEK_API_KEY，请在 .env.local 或环境变量中设置。' });
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
        const result = await runDeepSeekAgent(reasoner, cleaned, apiKey, model);
        sendJson(res, 200, result);
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
    console.log(`[atlas-server] DeepSeek Agent: ${apiKey ? `ENABLED (${model})` : 'DISABLED (no DEEPSEEK_API_KEY)'}`);
  });
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});
