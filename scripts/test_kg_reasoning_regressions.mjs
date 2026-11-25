import assert from 'node:assert/strict';
import test from 'node:test';
import { createServer } from 'node:http';
import { once } from 'node:events';
import { setImmediate } from 'node:timers/promises';
import { createKGReasoner } from '../src/kg-reasoner.js';
import { assessAgentAnswer, comparisonSummary, recoverToolCalls, resolvePathIntent } from '../server/agent-answer.js';
import { runDeepSeekAgent } from '../server/atlas-server.ts';

function preflightResults(messages) {
  const question = messages.find(message => message.role === 'user');
  return [...question.content.matchAll(/^本轮由服务器预先核验的图谱结果.*\n(.+)$/gm)].map(match => JSON.parse(match[1]));
}

function fixture() {
  const items = [
    { artifactId: 'shang', artifact: '商代器物', page: 1, evidenceId: 'shang' },
    { artifactId: 'western', artifact: '西周器物', page: 2, evidenceId: 'western' },
    { artifactId: 'spring', artifact: '春秋器物', page: 3, evidenceId: 'spring' },
    { artifactId: 'warring', artifact: '战国器物', page: 4, evidenceId: 'warring' },
    { artifactId: 'broad', artifact: '仅标周代器物', page: 5, evidenceId: 'broad' },
  ];
  const relations = [
    ['shang', 'period', '殷代'], ['shang', 'decorated_with', '云雷纹'],
    ['western', 'period', '西周初期'], ['western', 'decorated_with', '云雷纹'],
    ['spring', 'period', '春秋晚期'], ['spring', 'decorated_with', '鸟纹'],
    ['warring', 'period', '战国中期'], ['broad', 'period', '周代'],
  ];
  return { title: '时代包含关系回归样本', items,
    evidence: items.map(item => ({ id: item.artifactId, text: item.artifact, ordinal: item.page })),
    rows: relations.map(([id, predicate, object], index) => ({
      id: `t${index}`, artifactId: id, predicate, object, evidenceId: id,
      page: items.find(item => item.artifactId === id).page,
    })),
  };
}

test('周代 contains narrower periods transitively; broad dating does not imply 西周', () => {
  const r = createKGReasoner(fixture());
  assert.equal(r.queryArtifacts({ period: '周代', useOntology: true }).count, 4);
  assert.equal(r.queryArtifacts({ period: '周代', useOntology: false }).count, 1);
  assert.equal(r.queryArtifacts({ period: '西周', useOntology: true }).count, 1);
  const springAncestors = r.inferredTriples.filter(t => t.subjectId === 'spring').map(t => t.objectLabel);
  assert.ok(springAncestors.includes('东周'));
  assert.ok(springAncestors.includes('周代'));
  assert.equal(r.kg.triples.length, fixture().rows.length);
});

test('set comparison and SPARQL agree on Zhou membership and shared motif', () => {
  const r = createKGReasoner(fixture());
  const cmp = r.compareEntities('era', '商代', '周代', { useOntology: true });
  assert.equal(cmp.countB, 4);
  assert.ok(cmp.primary.shared.some(row => row.label === '云雷纹'));
  assert.equal(cmp.primary.coverage.withValuesB, 2);
  const sparql = r.runSparql('SELECT DISTINCT ?artifact WHERE { ?artifact :period_class "周代" . }', { useOntology: true });
  assert.equal(sparql.rows.length, cmp.countB);
});

test('comparison uses the selected field without changing the two groups', () => {
  const manifest = fixture();
  for (const [artifactId, object] of [['shang', '铜'], ['western', '铜'], ['shang', '玉'], ['spring', '陶']]) {
    manifest.rows.push({ id: `t${manifest.rows.length}`, artifactId, predicate: 'made_of', object });
  }
  const r = createKGReasoner(manifest);
  const motifs = r.compareEntities('era', '商代', '周代');
  const materials = r.compareEntities('era', '商代', '周代', { axis: 'material' });
  assert.deepEqual(materials.artifactIdsA, motifs.artifactIdsA);
  assert.deepEqual(materials.artifactIdsB, motifs.artifactIdsB);
  assert.equal(motifs.primary.axis, 'motif');
  assert.equal(materials.primary.axis, 'material');
  assert.deepEqual(materials.primary.shared.map(item => item.label), ['铜器类']);
  assert.deepEqual(materials.primary.onlyA.map(item => item.label), ['玉石类']);
  assert.deepEqual(materials.primary.onlyB.map(item => item.label), ['陶瓷类']);
  assert.equal(materials.secondary.axis, 'motif');
  assert.equal(r.compareEntities('era', '商代', '周代', { axis: 'era' }).ok, false);
});

test('upstream attributes work in comparisons, path lookup and candidate completion', () => {
  const raw = fixture();
  for (const [artifactId, predicate, object] of [
    ['shang', 'artifact_type', '壶'], ['western', 'artifact_type', '罐'],
    ['shang', 'has_shape', '圆形'], ['western', 'has_shape', '圆形'],
    ['shang', 'discovered_at', '地点甲'], ['western', 'collected_at', '地点甲'],
    ['warring', 'decorated_with', '云雷纹'],
  ]) raw.rows.push({ id: `t${raw.rows.length}`, artifactId, predicate, object });
  const engine = createKGReasoner(raw);
  for (const [axis, label] of [['shape', '圆形'], ['place', '地点甲']]) {
    const result = engine.compareEntities('artifact_type', '壶', '罐', { axis, useOntology: false });
    assert.deepEqual(result.primary.shared.map(item => item.label), [label]);
  }
  assert.ok(engine.findPaths('artifact_type:壶', 'shape:圆形').paths.length);
  const prediction = engine.predictMissing({ targetPredicate: 'has_shape', artifactId: 'warring' });
  assert.equal(prediction.predictions[0]?.predictedValue, '圆形');
  assert.equal(engine.predictMissing({ targetPredicate: 'has_shape', artifactId: 'shang' }).predictions.length, 0);
  assert.equal(engine.predictMissing({ targetPredicate: 'held_by' }).ok, false);
});

test('AI comparison keeps the selected axis and displays checked choices', async (t) => {
  const manifest = fixture();
  for (const [artifactId, object] of [['shang', '铜'], ['western', '铜'], ['spring', '石']]) {
    manifest.rows.push({ id: `t${manifest.rows.length}`, artifactId, predicate: 'made_of', object });
  }
  const reasoner = createKGReasoner(manifest);
  const intent = { type: 'compare', kind: 'material', entityA: '铜', entityB: '石', axis: 'era', useOntology: false };
  const call = (name, args) => ({ id: `${name}-${++calls}`, type: 'function', function: { name, arguments: JSON.stringify(args) } });
  let calls = 0;
  let rounds = 0;
  const mock = t.mock.method(globalThis, 'fetch', async (_url, request) => {
    const { messages, tools } = JSON.parse(request.body);
    assert.deepEqual(tools.map(tool => tool.function.name), ['compare_entities', 'show_comparison']);
    const [initial] = preflightResults(messages);
    assert.equal(initial.primaryAxis, 'era');
    assert.equal(initial.secondary, undefined);
    const choice = initial.onlyB.find(item => item.label === '春秋晚期');
    assert.ok(choice);
    const last = JSON.parse(messages.filter(m => m.role === 'tool').at(-1)?.content || 'null');
    const modelReplies = [
      () => ({ tool_calls: [call('compare_entities', { ...intent, axis: 'motif', useOntology: true })] }),
      () => {
        assert.equal(last.primaryAxis, 'era');
        return { tool_calls: [call('show_comparison', { items: 'B999' })] };
      },
      () => {
        assert.match(last.error, /displayId/);
        return { tool_calls: [call('show_comparison', { items: choice.displayId })] };
      },
      () => {
        assert.deepEqual(last.displayed, ['春秋晚期']);
        return { content: `石组有春秋晚期的时代记录。[${initial.inferenceRef}]` };
      },
    ];
    return Response.json({ choices: [{ message: modelReplies[rounds++](), finish_reason: 'stop' }] });
  });
  const output = await runDeepSeekAgent(reasoner, [{ role: 'user', content: '解读铜与石的时代对比' }], {
    provider: 'deepseek', apiKey: 'test', model: 'test', completionUrl: 'http://127.0.0.1:1/test',
  }, intent);
  assert.equal(mock.mock.callCount(), 4);
  assert.equal(output.stageAction.comparison.primary.axis, 'era');
  assert.equal(output.stageAction.comparison.useOntology, false);
  assert.deepEqual(output.stageAction.displayLabels, ['春秋晚期']);
  assert.equal(output.inferences[0].axis, 'era');
  assert.match(output.answer, /春秋晚期/);
});

test('missing annotations yield insufficient coverage, never an absence claim', () => {
  const r = createKGReasoner(fixture());
  const cmp = r.compareEntities('era', '殷代', '周代', { useOntology: false });
  assert.equal(cmp.primary.comparable, false);
  assert.equal(cmp.primary.jaccard, null);
  assert.equal(cmp.primary.coverage.withValuesB, 0);
  assert.equal(cmp.absenceIsEvidence, false);
  assert.equal(cmp.secondary.comparable, false);
  const summary = comparisonSummary(cmp, 'R1');
  assert.ok(summary.includes('标注不足'));
  assert.ok(summary.includes('未检索到不代表历史上不存在'));
  assert.ok(summary.includes('[R1]'));
});

test('DSML and incomplete generations cannot be returned as a final answer', () => {
  const context = { citations: new Set(['E1']), inferences: new Set(['R1']), toolCount: 1 };
  const leaked = '<｜DSML｜function_calls><｜DSML｜invoke name="run_sparql">...</｜DSML｜invoke></｜DSML｜function_calls>';
  assert.equal(assessAgentAnswer({ content: leaked }, 'stop', context).reason, 'tool_markup');
  assert.equal(assessAgentAnswer({ content: '根据记录[E1]，尚需' }, 'length', context).reason, 'truncated');
  assert.equal(assessAgentAnswer({ content: '根据记录[E9]' }, 'stop', context).reason, 'unknown_reference');
  assert.equal(assessAgentAnswer({ content: '有共同纹样' }, 'stop', context).reason, 'missing_reference');
  assert.equal(assessAgentAnswer({ content: '当前记录共有云雷纹[R1]。' }, 'stop', context).ok, true);
});

test('reference ranges expand to clickable IDs and every ID must be registered', () => {
  const context = { citations: new Set(['E1', 'E2', 'E3']), inferences: new Set(['R1']), toolCount: 1 };
  const accepted = assessAgentAnswer({ content: '来源[E1-E3]，对比[R1]。' }, 'stop', context);
  assert.equal(accepted.answer, '来源[E1][E2][E3]，对比[R1]。');
  assert.equal(assessAgentAnswer({ content: '来源[E1-E4]' }, 'stop', context).reason, 'unknown_reference');
  assert.equal(assessAgentAnswer({ content: '来源[E1-R1]' }, 'stop', context).reason, 'unknown_reference');
});

test('serialized tool arguments enforce the declared schema and tool allowlist', () => {
  const definitions = [{ function: { name: 'run_sparql', parameters: { properties: {
    query: { type: 'string' }, useOntology: { type: 'boolean' },
  }, required: ['query'] } } }];
  const call = '<｜DSML｜function_calls><｜DSML｜invoke name="run_sparql"><｜DSML｜parameter name="query" string="true">SELECT * WHERE { ?s :period "商代" . }</｜DSML｜parameter><｜DSML｜parameter name="useOntology" string="false">true</｜DSML｜parameter></｜DSML｜invoke></｜DSML｜function_calls>';
  const calls = recoverToolCalls(call, definitions);
  assert.equal(calls.length, 1);
  assert.equal(JSON.parse(calls[0].function.arguments).useOntology, true);
  assert.throws(() => recoverToolCalls(call.replace('name="run_sparql"', 'name="unknown_tool"'), definitions));
  assert.throws(() => recoverToolCalls(call.replace('>true</', '>"true"</'), definitions));
  assert.equal(recoverToolCalls(call.replace('</｜DSML｜function_calls>', ''), definitions).length, 0);
});

test('the agent executes serialized calls and returns a cited final answer', async () => {
  let requests = 0;
  const provider = createServer(async (req, res) => {
    let body = '';
    for await (const chunk of req) body += chunk;
    const payload = JSON.parse(body);
    requests++;
    const content = requests === 1
      ? '<｜DSML｜function_calls><｜DSML｜invoke name="compare_entities"><｜DSML｜parameter name="kind" string="true">era</｜DSML｜parameter><｜DSML｜parameter name="entityA" string="true">商代</｜DSML｜parameter><｜DSML｜parameter name="entityB" string="true">周代</｜DSML｜parameter></｜DSML｜invoke></｜DSML｜function_calls>'
      : '当前两边都有云雷纹记录[R1]，共有纹样不能单独证明传承。';
    if (requests > 1) {
      const toolResult = JSON.parse(payload.messages.find(m => m.role === 'tool').content);
      assert.equal(toolResult.totals.shared, 1);
      assert.equal(toolResult.examplesArePartial, true);
    }
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ choices: [{ message: { role: 'assistant', content }, finish_reason: 'stop' }] }));
  });
  provider.listen(0, '127.0.0.1');
  await once(provider, 'listening');
  try {
    const output = await runDeepSeekAgent(createKGReasoner(fixture()), [{ role: 'user', content: '对比商代与周代' }], {
      provider: 'deepseek', apiKey: 'local-test-placeholder', model: 'local-test',
      completionUrl: `http://127.0.0.1:${provider.address().port}/chat/completions`,
    });
    assert.equal(requests, 2);
    assert.equal(output.trace[0].tool, 'compare_entities');
    assert.ok(output.answer.includes('[R1]'));
    assert.ok(!output.answer.includes('DSML'));
    assert.equal(output.stageAction.comparison.countB, 4);
  } finally {
    provider.closeAllConnections();
    await new Promise(resolve => provider.close(resolve));
  }
});

test('path intent survives both suggestion clicks and free text without using older turns', () => {
  const q = '请推导「新石器时代」与「商代」之间的多跳纹样传承或材质迁移路径，并说明开启本体泛化前后的差异。';
  assert.equal(resolvePathIntent(q).source, '新石器时代');
  assert.equal(resolvePathIntent(q).target, '商代');
  assert.equal(resolvePathIntent('继续', { type: 'path', source: '鸟纹', target: '鱼纹' }).source, '鸟纹');
  assert.equal(resolvePathIntent(q, { type: 'path', source: '新石器时代', target: '商代', maxPaths: 50 }).maxPaths, 50);
  assert.equal(resolvePathIntent('对比「商代」与「周代」的差集'), null);
});

test('missing literal nodes and empty ontology paths return distinct results without a model call', async () => {
  const raw = fixture();
  raw.items.push({ artifactId: 'early', artifact: '缺纹样标注器物', page: 6, evidenceId: 'early' });
  raw.evidence.push({ id: 'early', text: '原始社会器物', ordinal: 6 });
  raw.rows.push({ id: 'early-period', artifactId: 'early', predicate: 'period', object: '原始社会', evidenceId: 'early', page: 6 });
  const output = await runDeepSeekAgent(createKGReasoner(raw), [{ role: 'user', content: '检索「新石器时代」与「商代」的多跳路径' }], {
    provider: 'deepseek', apiKey: 'local-test-placeholder', model: 'local-test',
    completionUrl: 'http://127.0.0.1:1/must-not-be-called',
  });
  assert.equal(output.responseMode, 'symbolic');
  assert.deepEqual(output.trace.map(step => step.tool), ['find_paths', 'find_paths']);
  assert.equal(output.stageAction.overlay, 'path');
  assert.equal(output.stageAction.paths.length, 0);
  const [literal, ontology] = output.stageAction.searchResults;
  assert.equal(literal.search.stoppedReason, 'missing_node');
  assert.equal(ontology.ok, true);
  assert.equal(ontology.pathCount, 0);
  assert.deepEqual(ontology.coverage.source, { total: 1, withMotifs: 0, withMaterials: 0 });
  assert.match(output.answer, /本体关闭/);
  assert.match(output.answer, /本体开启/);
  assert.match(output.answer, /未在图谱中找到起点/);
  assert.match(output.answer, /未找到路径不代表历史上没有联系/);
});

test('exhausting the path search budget leaves reachability unknown', () => {
  const r = createKGReasoner(fixture());
  const res = r.findPaths('殷代', '西周初期', { useOntology: false, maxExpansions: 1 });
  assert.equal(res.paths.length, 0);
  assert.equal(res.search.budgetExhausted, true);
  assert.equal(res.search.completeWithinConstraints, false);
  assert.equal(res.literalReachable, null);
});

test('path search returns 50 unique paths and surfaces rare bridges before repeating common ones', async (t) => {
  const items = [];
  const rows = [];
  for (const era of ['新石器时代', '商代']) {
    for (let i = 0; i < 12; i++) {
      const artifactId = `${era}-${i}`;
      items.push({ artifactId });
      const row = (predicate, object) => rows.push({ id: `t${rows.length}`, artifactId, predicate, object });
      row('period', era);
      row('made_of', '陶');
      if (i === 11) row('decorated_with', '几何纹');
      if (i === 10) row('decorated_with', '绳纹');
    }
  }
  const r = createKGReasoner({ items, rows });
  const options = { useOntology: false, maxHops: 4 };
  const bridges = result => result.paths.slice(0, 3).map(path => path.steps[1].toLabel).sort();
  const result = r.findPaths('新石器时代', '商代', { ...options, maxPaths: 50 });
  assert.equal(result.paths.length, 50);
  assert.equal(new Set(result.paths.map(path => JSON.stringify(path.nodeKeys))).size, 50);
  assert.ok(result.paths.every(path => path.hops === 4));
  assert.deepEqual(bridges(result), ['几何纹', '绳纹', '陶']);
  assert.deepEqual(bridges(r.findPaths('新石器时代', '商代', options)), ['几何纹', '绳纹', '陶']);
  assert.equal(r.findPaths('新石器时代', '商代', { ...options, maxHops: 3 }).paths.length, 0);

  const mock = t.mock.method(globalThis, 'fetch', async (_url, request) => {
    const messages = JSON.parse(request.body).messages;
    const searches = preflightResults(messages);
    assert.deepEqual(searches.map(search => search.pathCount), [50, 50]);
    assert.ok(searches.every(search => search.paths.length === 6 && search.search.maxHops === 4));
    return Response.json({ choices: [{ message: { content: `找到 50 条关联候选。[${searches[0].inferenceRef}]` }, finish_reason: 'stop' }] });
  });
  const output = await runDeepSeekAgent(r, [{ role: 'user', content: 'AI 解读' }], {
    provider: 'deepseek', apiKey: 'test', model: 'test', completionUrl: 'http://127.0.0.1:1/test',
  }, { type: 'path', source: '新石器时代', target: '商代', maxHops: 4, maxPaths: 50 });
  assert.equal(mock.mock.callCount(), 1);
  assert.equal(output.stageAction.paths.length, 50);
  assert.deepEqual(output.stageAction.searchResults.map(search => search.pathCount), [50, 50]);
});

test('path rules describe associations rather than proving historical transmission', () => {
  const r = createKGReasoner(fixture());
  const res = r.findPaths('殷代', '西周初期', { useOntology: false });
  assert.ok(res.paths.length > 0);
  const rules = res.paths[0].rulesTriggered;
  assert.ok(rules.some(rule => rule.code === 'R3_CO_MOTIF'));
  assert.ok(rules.some(rule => rule.code === 'R1_TEMPORAL_ASSOCIATION'));
  assert.ok(rules.every(rule => !/persists\(|transfers_material/.test(rule.formula)));

  const family = fixture();
  family.rows.find(row => row.artifactId === 'western' && row.predicate === 'decorated_with').object = '雷纹';
  const generalized = createKGReasoner(family).findPaths('殷代', '西周初期', { useOntology: true, maxHops: 6 });
  assert.ok(generalized.paths.length > 0);
  assert.ok(generalized.paths.every(path => !path.rulesTriggered.some(rule => rule.code === 'R3_CO_MOTIF')));
});

test('path card analysis streams verified evidence for the selected route only', async (t) => {
  const data = fixture();
  data.rows.push(
    { id: 'west-copper', artifactId: 'western', predicate: 'made_of', object: '铜' },
    { id: 'shang-copper', artifactId: 'shang', predicate: 'made_of', object: '铜' },
  );
  const reasoner = createKGReasoner(data);
  const paths = reasoner.findPaths('云雷纹', '铜', { useOntology: false }).paths;
  assert.ok(paths.length >= 2);
  const path = paths[1];
  const other = paths[0].artifactIds[0];
  const intent = { type: 'selected_path', index: 2, useOntology: false,
    nodeKeys: path.nodeKeys, edgeIds: path.steps.map(step => step.edgeId) };
  const events = [];
  const config = { provider: 'deepseek', apiKey: 'test', model: 'test', completionUrl: 'http://127.0.0.1:1/test' };
  const mock = t.mock.method(globalThis, 'fetch', async (_url, request) => {
    assert.deepEqual(events.map(event => event.type), ['tool_start', 'tool_result', 'model_wait']);
    const { messages, tool_choice } = JSON.parse(request.body);
    assert.equal(tool_choice, 'none');
    const [tool] = preflightResults(messages);
    assert.equal(tool.path, '路径 2');
    assert.deepEqual(tool.steps.map(step => [step.from, step.to]), path.steps.map(step => [step.fromLabel, step.toLabel]));
    return Response.json({ choices: [{ message: { content: `考察这件器物的纹样和材质关联。[${tool.inferenceRef}]` }, finish_reason: 'stop' }] });
  });
  const answer = await runDeepSeekAgent(reasoner, [{ role: 'user', content: '解读这条路径' }], config, intent, event => events.push(event));
  assert.equal(answer.stageAction.pathLabel, '路径 2');
  assert.deepEqual(answer.stageAction.paths.map(result => result.nodeKeys), [path.nodeKeys]);
  assert.deepEqual(answer.stageAction.artifactIds, path.artifactIds);
  assert.ok(answer.citations.length && answer.citations.every(citation => citation.artifactId !== other));
  assert.equal(answer.trace[0].preview, events[1].step.preview);
  const stale = await runDeepSeekAgent(reasoner, [], config, { ...intent, edgeIds: ['missing', ...intent.edgeIds.slice(1)] });
  assert.equal(stale.responseMode, 'symbolic');
  assert.equal(stale.stageAction, null);
  assert.equal(mock.mock.callCount(), 1);
});

test('thinking and tool preparation stream before the answer and continue across tool rounds', async (t) => {
  const firstReasoning = '先核对商代器物。';
  const secondReasoning = '再依据资料回答。';
  const events = [];
  let upstream;
  let round = 0;
  const encode = new TextEncoder();
  const chunk = (delta, finish_reason = null) => encode.encode(`data: ${JSON.stringify({ choices: [{ delta, finish_reason }] })}\r\n\r\n`);
  t.mock.method(globalThis, 'fetch', async (_url, request) => {
    const { thinking, stream, messages, tool_choice } = JSON.parse(request.body);
    assert.deepEqual(thinking, { type: 'enabled' });
    assert.equal(stream, true);
    assert.equal(tool_choice, 'auto');
    if (++round === 1) {
      return new Response(new ReadableStream({ start(controller) { upstream = controller; } }), {
        headers: { 'Content-Type': 'text/event-stream' },
      });
    }
    const assistant = messages.find(message => message.role === 'assistant');
    assert.equal(assistant.reasoning_content, firstReasoning);
    assert.equal(assistant.tool_calls[0].function.arguments, '{"period":"殷代"}');
    const result = JSON.parse(messages.at(-1).content);
    assert.equal(result.count, 1);
    assert.deepEqual(events.map(event => event.type), ['model_wait', 'thinking', 'tool_pending', 'tool_start', 'tool_result', 'model_wait']);
    return new Response(new ReadableStream({ start(controller) {
      controller.enqueue(chunk({ reasoning_content: secondReasoning }));
      controller.enqueue(chunk({ content: `图谱记录了云雷纹。[${result.items[0].evidenceRefs[0]}]` }));
      controller.enqueue(chunk({}, 'stop'));
      controller.close();
    } }), { headers: { 'Content-Type': 'text/event-stream' } });
  });

  const history = [{ role: 'user', content: '先看商代。' }, { role: 'assistant', content: '可以。' },
    { role: 'user', content: '商代器物有哪些纹样？' }];
  const pending = runDeepSeekAgent(createKGReasoner(fixture()), history, {
    provider: 'deepseek', apiKey: 'test', model: 'test', completionUrl: 'http://127.0.0.1:1/test',
  }, null, event => events.push(event));
  const thinking = chunk({ reasoning_content: firstReasoning });
  const split = thinking.indexOf(encode.encode('先')[0]) + 1;
  upstream.enqueue(thinking.slice(0, split));
  upstream.enqueue(thinking.slice(split));
  upstream.enqueue(chunk({ tool_calls: [{ index: 0, id: 'call_1', function: { name: 'query_graph', arguments: '{"period":' } }] }));
  await setImmediate();
  assert.deepEqual(events.map(event => event.type), ['model_wait', 'thinking', 'tool_pending']);
  upstream.enqueue(chunk({ tool_calls: [{ index: 0, function: { arguments: '"殷代"}' } }] }));
  upstream.enqueue(chunk({}, 'tool_calls'));
  upstream.close();
  const result = await pending;
  assert.equal(result.thinking, `${firstReasoning}\n\n${secondReasoning}`);
  assert.match(result.answer, /云雷纹/);
  assert.equal(result.trace[0].tool, 'query_graph');
});

test('a comparison tool attempt cannot replace a bound path result or its fallback', async () => {
  let requests = 0;
  const provider = createServer(async (req, res) => {
    let body = '';
    for await (const chunk of req) body += chunk;
    const payload = JSON.parse(body);
    requests++;
    assert.ok(payload.tools.every(t => t.function.name !== 'compare_entities'));
    if (requests === 2) assert.match(payload.messages.at(-1).content, /不属于本轮路径任务/);
    const message = requests === 1 ? { role: 'assistant', content: null, tool_calls: [{
      id: 'rogue-comparison', type: 'function', function: { name: 'compare_entities', arguments: JSON.stringify({
        kind: 'era', entityA: '殷代', entityB: '西周初期',
      }) },
    }] } : { role: 'assistant', content: '未完成的结论' };
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ choices: [{ message, finish_reason: requests === 1 ? 'tool_calls' : 'length' }] }));
  });
  provider.listen(0, '127.0.0.1');
  await once(provider, 'listening');
  try {
    const output = await runDeepSeekAgent(createKGReasoner(fixture()), [{ role: 'user', content: '检索「殷代」与「西周初期」的多跳纹样路径，说明本体开关差异' }], {
      provider: 'deepseek', apiKey: 'local-test-placeholder', model: 'local-test',
      completionUrl: `http://127.0.0.1:${provider.address().port}/chat/completions`,
    });
    assert.equal(requests, 2);
    assert.equal(output.stageAction.overlay, 'path');
    assert.equal(output.stageAction.searchResults.length, 2);
    assert.ok(output.stageAction.paths.length > 0);
    assert.equal(output.stageAction.comparison, undefined);
    assert.equal(output.responseMode, 'tool_summary');
    assert.match(output.answer, /本体关闭/);
    assert.match(output.answer, /本体开启/);
    assert.ok(!output.answer.includes('记录差集'));
  } finally {
    provider.closeAllConnections();
    await new Promise(resolve => provider.close(resolve));
  }
});
