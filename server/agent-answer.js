import { COMPARISON_DIMENSIONS } from '../src/kg-reasoner.js';

export function hasToolMarkup(text) {
  return /<\/?[|｜]+DSML[|｜]+|<\/?(?:tool_calls?|function_calls?)\b|\[TOOL_CALLS\]/i.test(text || '');
}

export async function readAgentCompletion(response, onThinking, onToolName) {
  const showThinking = part => {
    const text = part.reasoning_content || part.reasoning
      || part.reasoning_details?.map(detail => detail.text || detail.summary || '').join('');
    if (text) onThinking(text);
  };
  if (!response.headers.get('content-type')?.includes('text/event-stream')) {
    const { choices, error } = await response.json();
    if (error) throw new Error(error.message || '模型接口返回错误。');
    const choice = choices?.[0];
    if (choice?.message) showThinking(choice.message);
    return choice;
  }

  const message = { role: 'assistant', content: '' };
  const calls = [];
  const reasoningDetails = new Map();
  let finishReason;
  let buffer = '';
  const readEvent = event => {
    const data = event.split(/\r?\n/).filter(line => line.startsWith('data:'))
      .map(line => line.slice(5).trimStart()).join('\n');
    if (!data || data === '[DONE]') return;
    const packet = JSON.parse(data);
    if (packet.error) throw new Error(packet.error.message || '模型流式响应出错。');
    const choice = packet.choices?.[0];
    if (!choice) return;
    const delta = choice.delta || {};
    message.content += delta.content || '';
    for (const field of ['reasoning_content', 'reasoning']) {
      if (typeof delta[field] === 'string') message[field] = (message[field] || '') + delta[field];
    }
    for (const [position, part] of (delta.reasoning_details || []).entries()) {
      const key = part.index ?? part.id ?? position;
      const previous = reasoningDetails.get(key) || {};
      const detail = { ...previous, ...part };
      for (const field of ['text', 'summary', 'data', 'signature']) {
        if (typeof part[field] === 'string') detail[field] = (previous[field] || '') + part[field];
      }
      reasoningDetails.set(key, detail);
    }
    showThinking(delta);
    for (const part of delta.tool_calls || []) {
      const call = calls[part.index] ??= { id: '', type: 'function', function: { name: '', arguments: '' } };
      call.id += part.id || '';
      call.function.name += part.function?.name || '';
      call.function.arguments += part.function?.arguments || '';
      if (part.function?.name) onToolName(call.function.name);
    }
    if (choice.finish_reason) finishReason = choice.finish_reason;
  };
  for await (const chunk of response.body.pipeThrough(new TextDecoderStream())) {
    buffer += chunk;
    const events = buffer.split(/\r?\n\r?\n/);
    buffer = events.pop();
    for (const event of events) readEvent(event);
  }
  if (buffer.trim()) readEvent(buffer);
  if (!finishReason) throw new Error('模型连接已中断，未收到完整结果。');
  if (calls.length) message.tool_calls = calls.filter(Boolean);
  if (reasoningDetails.size) message.reasoning_details = [...reasoningDetails.values()];
  return { message, finish_reason: finishReason };
}

// Some providers serialize DeepSeek calls in content. Decode only complete calls
// to known, read-only graph tools, with exactly the declared argument types.
export function recoverToolCalls(content, definitions, idPrefix = 'dsml') {
  const block = String(content || '').match(/<[|｜]DSML[|｜]function_calls>([\s\S]*?)<\/[|｜]DSML[|｜]function_calls>/);
  if (!block) return [];
  const tools = new Map(definitions.map(tool => [tool.function.name, tool.function.parameters]));
  const calls = [];
  const invoke = /<[|｜]DSML[|｜]invoke\s+name="([^"]+)"\s*>([\s\S]*?)<\/[|｜]DSML[|｜]invoke>/g;
  const parameter = /<[|｜]DSML[|｜]parameter\s+name="([^"]+)"(?:\s+string="(true|false)")?\s*>([\s\S]*?)<\/[|｜]DSML[|｜]parameter>/g;
  let match;
  let invocationCount = 0;
  while ((match = invoke.exec(block[1]))) {
    invocationCount++;
    if (invocationCount > 4) throw new Error('Too many serialized tool calls');
    const schema = tools.get(match[1]);
    if (!schema) throw new Error('Unknown serialized graph tool');
    const args = {};
    let param;
    parameter.lastIndex = 0;
    while ((param = parameter.exec(match[2]))) {
      const [name, isString, raw] = param.slice(1);
      const property = schema.properties?.[name];
      if (!property || Object.hasOwn(args, name)) throw new Error('Invalid serialized argument name');
      const text = raw.trim().replace(/&(lt|gt|amp|quot|apos);/g, (_, entity) => ({ lt: '<', gt: '>', amp: '&', quot: '"', apos: "'" })[entity]);
      const value = isString === 'false' || (isString === undefined && property.type !== 'string') ? JSON.parse(text) : text;
      if (typeof value !== property.type || (property.type === 'number' && !Number.isFinite(value))
          || (property.enum && !property.enum.includes(value))) throw new Error('Invalid serialized argument type');
      args[name] = value;
    }
    if ((schema.required || []).some(name => !Object.hasOwn(args, name))) throw new Error('Missing serialized argument');
    // Reject unparsed or malformed tags rather than partially executing a call.
    parameter.lastIndex = 0;
    if (match[2].replace(parameter, '').trim()) throw new Error('Malformed serialized arguments');
    calls.push({ id: `${idPrefix}_${calls.length}`, type: 'function', function: { name: match[1], arguments: JSON.stringify(args) } });
  }
  invoke.lastIndex = 0;
  if (block[1].replace(invoke, '').trim()) throw new Error('Malformed serialized tool block');
  return calls;
}

// Accept final prose only after graph tools have supplied valid references.
export function assessAgentAnswer(message, finishReason, { citations, inferences, toolCount }) {
  let answer = (message.content || '').trim();
  if (hasToolMarkup(answer)) {
    return { ok: false, reason: 'tool_markup' };
  }
  if (finishReason === 'length') return { ok: false, reason: 'truncated' };
  if (!answer) return { ok: false, reason: 'empty' };
  if (!toolCount) return { ok: false, reason: 'no_tools' };
  let invalidRange = false;
  answer = answer.replace(/\[([ER])(\d+)\s*[-–—]\s*([ER])?(\d+)\]/g, (match, prefix, startText, endPrefix, endText) => {
    const start = Number(startText), end = Number(endText);
    const allowed = prefix === 'E' ? citations : inferences;
    if ((endPrefix && endPrefix !== prefix) || end < start || end - start > 64) {
      invalidRange = true; return match;
    }
    const refs = Array.from({ length: end - start + 1 }, (_, index) => prefix + (start + index));
    if (refs.some(ref => !allowed.has(ref))) invalidRange = true;
    return refs.map(ref => `[${ref}]`).join('');
  });
  if (invalidRange) return { ok: false, reason: 'unknown_reference' };
  const refs = [...answer.matchAll(/\[(?:实证\s*|推论\s*)?([ER]\d+)\]/g)].map(match => match[1]);
  if (refs.some(ref => !(ref.startsWith('E') ? citations : inferences).has(ref))) {
    return { ok: false, reason: 'unknown_reference' };
  }
  if ((citations.size || inferences.size) && !refs.length) return { ok: false, reason: 'missing_reference' };
  return { ok: true, answer };
}

// If generation cannot finish, return the computed result with its registered proof.
export function comparisonSummary(result, ref, primaryOnly = false) {
  const labels = values => values.slice(0, 6).map(value => value.label).join('、') || '当前未检索到';
  const scope = result.useOntology ? '已启用本体泛化。' : '按所选字面标签对比。';
  const lines = [`当前候选图谱：${result.entityA} ${result.countA} 条，${result.entityB} ${result.countB} 条。${scope}[${ref}]`];
  for (const axis of primaryOnly ? [result.primary] : [result.primary, result.secondary]) {
    const name = COMPARISON_DIMENSIONS[axis.axis]?.label || axis.axis;
    const c = axis.coverage;
    if (c) lines.push(`${name}记录覆盖：${result.entityA} ${c.withValuesA}/${c.totalA}，${result.entityB} ${c.withValuesB}/${c.totalB}。[${ref}]`);
    if (!axis.comparable) {
      lines.push(`${name}标注不足，无法判断共有或独有。[${ref}]`);
      continue;
    }
    lines.push(`当前${name}共有 ${axis.shared.length} 项，${result.entityA}/${result.entityB}记录差集分别 ${axis.onlyA.length}/${axis.onlyB.length} 项。[${ref}]`);
    lines.push(`两边均有记录的${name}（部分）：${labels(axis.shared)}。[${ref}]`);
    lines.push(`仅在${result.entityA}检索到的${name}（部分）：${labels(axis.onlyA)}；仅在${result.entityB}检索到：${labels(axis.onlyB)}。[${ref}]`);
  }
  lines.push('这些差集仅描述当前已录入候选。未检索到不代表历史上不存在。');
  if (!primaryOnly) lines.push('共有纹样也不能单独证明传承。');
  return lines.join('\n\n');
}

export function resolveCompareIntent(hint) {
  if (hint?.type !== 'compare' || hint.axis === undefined) return null;
  const { kind, entityA, entityB, axis, useOntology } = hint;
  const validLabel = value => typeof value === 'string' && value.length <= 200 && value.trim();
  if (!Object.hasOwn(COMPARISON_DIMENSIONS, kind) || !Object.hasOwn(COMPARISON_DIMENSIONS, axis) || kind === axis
      || !validLabel(entityA) || !validLabel(entityB) || entityA.trim() === entityB.trim()) {
    throw new Error('请选择两个不同的比较对象，以及与分组不同的比较内容。');
  }
  return { kind, entityA: entityA.trim(), entityB: entityB.trim(), axis, useOntology: useOntology !== false };
}

// Suggestions carry explicit intent; free text falls back to explicit path wording
// and two quoted entities (or known catalog labels). Never use earlier chat turns.
export function resolvePathIntent(question, hint, catalog = {}) {
  const valid = value => typeof value === 'string' && value.trim().length > 0 && value.length <= 200;
  if (hint?.type === 'path' && valid(hint.source) && valid(hint.target)) {
    return { type: 'path', source: hint.source.trim(), target: hint.target.trim(),
      maxHops: Math.max(2, Math.min(8, Number(hint.maxHops) || 6)),
      maxPaths: Math.max(1, Math.min(50, Math.trunc(Number(hint.maxPaths)) || 4)) };
  }
  if (!/路径|链路/.test(question || '')) return null;
  const quoted = [...question.matchAll(/[「“"]([^」”"]{1,200})[」”"]/g)].map(m => m[1]);
  let labels = quoted;
  if (labels.length < 2) {
    const known = Object.entries(COMPARISON_DIMENSIONS).flatMap(([kind, dim]) => catalog[kind === 'era' ? 'eras' : dim.field] || []);
    const hits = [...new Set(known.map(x => x.name))].filter(valid)
      .map(label => ({ label, start: question.indexOf(label) })).filter(x => x.start >= 0)
      .sort((a, b) => a.start - b.start || b.label.length - a.label.length);
    const selected = [];
    for (const hit of hits) {
      if (!selected.some(x => hit.start < x.start + x.label.length)) selected.push(hit);
    }
    labels = selected.map(x => x.label);
  }
  return labels.length >= 2 ? { type: 'path', source: labels[0], target: labels[1], maxHops: 6 } : null;
}

export function pathSearchSummary(results) {
  const lines = ['当前候选图谱的路径搜索结果：'];
  for (const { result: r, ref } of results) {
    const mode = `本体${r.useOntology ? '开启' : '关闭'}（最多 ${r.search.maxHops} 跳）`;
    if (!r.ok) lines.push(`${mode}：${r.error}。[${ref}]`);
    else if (!r.paths.length) lines.push(`${mode}：本次搜索未找到路径${r.search.budgetExhausted ? '，搜索预算已用尽，不能据此判断不连通' : '，仅针对当前图谱和搜索约束'}。[${ref}]`);
    else {
      lines.push(`${mode}：找到 ${r.paths.length} 条关联候选路径（最多展示 ${r.search.maxPaths} 条）。[${ref}]`);
      for (const p of r.paths.slice(0, 3)) {
        lines.push(`${p.hops} 跳：${[p.steps[0].fromLabel, ...p.steps.map(s => s.toLabel)].join(' → ')}${p.usesOntology ? '（含本体泛化）' : '（字面记录连接）'}。[${ref}]`);
      }
    }
    const coverage = Object.entries(r.coverage || {}).map(([side, c]) => {
      const label = side === 'source' ? r.source.label : r.target.label;
      return `${label}关联记录 ${c.total} 条，其中纹样 ${c.withMotifs} 条、材质 ${c.withMaterials} 条`;
    }).join('；');
    if (coverage) lines.push(`${coverage}。[${ref}]`);
  }
  lines.push('本体泛化只扩展已有分类关系，不能补出未抽取的时代、纹样或材质边。未找到路径不代表历史上没有联系；找到的关联路径也不能单独证明传承或材质迁移。');
  return lines.join('\n\n');
}
