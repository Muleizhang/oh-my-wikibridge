// Generic, book-agnostic Symbolic & Graph-Algorithmic Knowledge Reasoning Engine.
// Supports both manifest.json (atlas pipeline) and graph.json (local-kg pipeline).
// Zero external dependencies; runs identically in Node.js (server/tests) and Browser.

export const PREDICATE_LABELS = {
  period: '所属时代',
  made_of: '材质',
  decorated_with: '饰有纹样',
  uses_technique: '工艺',
  period_class: '时代大类',
  made_of_class: '材质大类',
  motif_family: '纹样谱系',
};

export const DYNASTY_TABLE = [
  { group: '新石器时代', order: 10, re: /新石器|原始社会|仰韶|半坡|庙底沟|马家窑|半山|马厂|河姆渡|良渚|龙山|大汶口|红山|裴李岗|磁山|屈家岭|马家浜|大溪/ },
  { group: '夏代', order: 20, re: /夏代|二里头|夏文化/ },
  { group: '商代', order: 30, re: /商|殷/ },
  { group: '周代', order: 35, re: /周代|周朝/ },
  { group: '西周', order: 40, re: /西周/ },
  { group: '东周', order: 45, re: /东周/ },
  { group: '春秋', order: 50, re: /春秋/ },
  { group: '战国', order: 60, re: /战国/ },
  { group: '秦代', order: 70, re: /秦/ },
  { group: '汉代', order: 80, re: /西汉|东汉|两汉|汉/ },
  { group: '三国', order: 90, re: /三国|曹魏|蜀汉|孙吴/ },
  { group: '魏晋南北朝', order: 100, re: /魏晋|两晋|西晋|东晋|南北朝|北朝|南朝|十六国|北魏|东魏|西魏|北齐|北周/ },
  { group: '隋代', order: 110, re: /隋/ },
  { group: '唐代', order: 120, re: /唐/ },
  { group: '五代', order: 130, re: /五代|十国/ },
  { group: '宋代', order: 140, re: /北宋|南宋|宋|辽|金|西夏/ },
  { group: '元代', order: 150, re: /元/ },
  { group: '明代', order: 160, re: /明/ },
  { group: '清代', order: 170, re: /清/ },
  { group: '近现代', order: 180, re: /民国|近代|现代|当代/ },
];

// Containment is directional: a broad period does not establish a narrower date.
const ERA_PARENTS = { 西周: '周代', 东周: '周代', 春秋: '东周', 战国: '东周' };

export const MATERIAL_ONTOLOGY = [
  { cls: '陶瓷类', re: /彩陶|红陶|白陶|黑陶|灰陶|印纹陶|陶器|陶|瓷|青瓷|釉陶/ },
  { cls: '铜器类', re: /青铜|铜器|铜|黄铜|红铜/ },
  { cls: '玉石类', re: /玉器|玉饰|玉|翡翠|玛瑙|石雕|石磬|石器|石/ },
  { cls: '漆木类', re: /漆器|漆|木雕|木|竹/ },
  { cls: '织绣类', re: /丝织|织绣|绣绢|织锦|丝|锦|绸|帛|罗|绫|麻|棉|布/ },
  { cls: '骨牙类', re: /象牙|骨雕|骨器|骨|角|牙|贝|蚌/ },
  { cls: '金银金属类', re: /金器|金|银器|银|铁器|铁|锡/ },
  { cls: '建筑彩绘类', re: /壁画|砖|瓦|泥塑|彩塑/ },
];

export const MOTIF_ONTOLOGY = [
  { cls: '禽鸟纹系', re: /凤|鸟|鹤|孔雀|朱雀|雁|雀|鹰/ },
  { cls: '龙虎神兽纹系', re: /龙|虎|夔|螭|虺|饕餮|兽面|麒麟|玄武|辟邪|狮|兽/ },
  { cls: '水生与动物纹系', re: /鱼|蛙|龟|蝉|蚕|蛇|蜥|鹿|马|牛|羊|猪|象|蝶|动物/ },
  { cls: '云气雷纹系', re: /云雷|云气|流云|卷云|雷纹|云纹|涡纹/ },
  { cls: '植物花卉纹系', re: /花|莲|荷|牡丹|卷草|忍冬|宝相|缠枝|枝叶|稻|树|植物|叶纹/ },
  { cls: '人物神话纹系', re: /人面|人形|人物|舞蹈|神人|飞天|仕女|狩猎|宴乐/ },
  { cls: '天象星日纹系', re: /太阳|拟日|八角星|星纹|日纹|月纹|火焰/ },
  { cls: '几何与纹饰带系', re: /几何|圆圈|同心圆|圆点|旋纹|绳纹|网纹|菱形|方格|三角|锯齿|连弧|折线|回纹|弦纹|波浪|水波|波曲|垂鳞|鱼鳞|鳞纹|环带|窃曲|重环|乳丁|乳钉|谷纹|刻划|划纹|布纹|编织|线纹/ },
  { cls: '构图范式', re: /四方连续|二方连续|边缘纹样|适合纹样|单独纹样/ },
];

export function eraInfo(label) {
  if (!label) return { group: '未标时代', order: 9999, sub: 5 };
  const hit = DYNASTY_TABLE.find(d => d.re.test(label));
  let sub = 4;
  if (/初|早|前/.test(label)) sub = 1;
  else if (/中/.test(label)) sub = 4;
  else if (/后/.test(label)) sub = 7;
  else if (/晚|末/.test(label)) sub = 9;
  if (hit) return { group: hit.group, order: hit.order + sub * 0.1, sub };
  return { group: label, order: 5000, sub };
}

export function materialClass(label) {
  if (!label) return null;
  const hit = MATERIAL_ONTOLOGY.find(m => m.re.test(label));
  return hit ? hit.cls : null;
}

export function motifFamily(label) {
  if (!label) return null;
  const hit = MOTIF_ONTOLOGY.find(m => m.re.test(label));
  return hit ? hit.cls : null;
}

function normText(s) {
  return String(s ?? '').normalize('NFKC').replace(/\s+/g, '').toLowerCase();
}

function predToKind(predicate) {
  if (predicate === 'period' || predicate === 'period_class') return 'era';
  if (predicate === 'made_of' || predicate === 'made_of_class') return 'material';
  if (predicate === 'decorated_with' || predicate === 'motif_family') return 'motif';
  return 'concept';
}

/**
 * Normalize either manifest.json or graph.json into one canonical KG representation.
 */
export function normalizeKG(raw) {
  if (!raw || typeof raw !== 'object') throw new Error('无效的知识图谱数据。');
  if (Array.isArray(raw.rows) || Array.isArray(raw.items)) return normalizeManifest(raw);
  if (Array.isArray(raw.records) && Array.isArray(raw.assertions)) return normalizeLocalGraph(raw);
  throw new Error('不支持的图谱数据格式（需要 manifest.json 或 graph.json）。');
}

function normalizeManifest(manifest) {
  const evMap = new Map((manifest.evidence || []).map(e => [e.id, e]));
  const artifacts = new Map();
  const triples = [];

  const rawItems = (manifest.items && manifest.items.length)
    ? manifest.items
    : [...new Map((manifest.rows || []).map(r => [r.artifactId, r])).values()];

  for (const it of rawItems) {
    const ev = evMap.get(it.evidenceId) || {};
    artifacts.set(it.artifactId, {
      id: it.artifactId,
      title: it.artifact || String(it.item || it.artifactId),
      page: Number(it.page || ev.ordinal || 1),
      volume: it.volume || ev.volume || '',
      volumePage: Number(it.volumePage || ev.volumePage || it.page || ev.ordinal || 1),
      sourceName: it.sourceName || ev.sourceName || '',
      locator: it.locator || ev.locator || '',
      status: it.status || '',
      findspot: it.findspot || '',
      observation: it.observation || '',
      quote: it.quote || ev.text || '',
      thumbUrl: it.detailUrl || it.imageUrl || ev.previewUrl || '',
      plateUrl: it.imageUrl || it.detailUrl || ev.previewUrl || '',
      captionUrl: it.captionUrl || ev.captionUrl || '',
      pageUrl: ev.previewUrl || '',
      bbox: ev.bbox || null,
      periods: [],
      materials: [],
      motifs: [],
      techniques: [],
      tripleIds: [],
    });
  }

  for (const r of (manifest.rows || [])) {
    const art = artifacts.get(r.artifactId);
    if (!art) continue;
    const ev = evMap.get(r.evidenceId) || {};
    const kind = predToKind(r.predicate);
    const objKey = `${kind}:${r.object}`;
    const triple = {
      id: r.id,
      subjectId: art.id,
      subjectLabel: art.title,
      predicate: r.predicate,
      predicateLabel: PREDICATE_LABELS[r.predicate] || r.predicate,
      objectKey: objKey,
      objectLabel: r.object,
      objectKind: kind,
      page: Number(r.page || ev.ordinal || art.page || 1),
      volume: r.volume || ev.volume || art.volume,
      volumePage: Number(r.volumePage || ev.volumePage || art.volumePage),
      sourceName: r.sourceName || ev.sourceName || art.sourceName,
      locator: r.proofLocator || r.locator || ev.locator || art.locator,
      quote: ev.text || r.quote || art.quote,
      evidenceId: r.evidenceId || art.id,
      bbox: ev.bbox || art.bbox,
      pageUrl: ev.previewUrl || art.pageUrl,
      captionUrl: ev.captionUrl || r.captionUrl || art.captionUrl,
      isInferred: false,
      origin: r.origin || '',
      binding: r.binding || null,
      supportingEvidence: r.supportingEvidence || [],
    };
    triples.push(triple);
    art.tripleIds.push(triple.id);
    if (r.predicate === 'period' && !art.periods.includes(r.object)) art.periods.push(r.object);
    else if (r.predicate === 'made_of' && !art.materials.includes(r.object)) art.materials.push(r.object);
    else if (r.predicate === 'decorated_with' && !art.motifs.includes(r.object)) art.motifs.push(r.object);
    else if (r.predicate === 'uses_technique' && !art.techniques.includes(r.object)) art.techniques.push(r.object);
  }

  return {
    title: manifest.title || '纹样知识图谱',
    format: 'manifest',
    artifacts,
    triples,
    tripleById: new Map(triples.map(t => [t.id, t])),
    pages: manifest.pages || [],
    volumes: manifest.volumes || [],
  };
}

function normalizeLocalGraph(graph) {
  const entities = new Map((graph.entities || []).map(e => [e.id, e]));
  const events = new Map((graph.events || []).map(e => [e.id, e]));
  const artifactOwners = new Map(
    (graph.entities || []).filter(e => e.kind === 'artifact' && e.recordId).map(e => [e.id, e.recordId]),
  );
  const motifConcepts = new Map(
    (graph.identityReview?.concepts || [])
      .filter(c => c.kind === 'motif')
      .flatMap(c => c.memberIds.map(id => [id, c])),
  );

  const artifacts = new Map();
  for (const rec of (graph.records || [])) {
    artifacts.set(rec.id, {
      id: rec.id,
      title: rec.label,
      page: Number(rec.page || 1),
      locator: `第 ${rec.page} 页 · 图 ${rec.item}`,
      status: '本地图谱',
      findspot: '',
      observation: '',
      quote: rec.text || '',
      thumbUrl: `/api/reasoning/page/${rec.page}`,
      plateUrl: `/api/reasoning/page/${rec.page}`,
      captionUrl: '',
      pageUrl: `/api/reasoning/page/${rec.page}`,
      bbox: rec.bbox || null,
      periods: [],
      materials: [],
      motifs: [],
      techniques: [],
      tripleIds: [],
    });
  }

  const triples = [];
  for (const fact of (graph.assertions || [])) {
    const owner = fact.subject && artifactOwners.get(fact.subject);
    if (!owner || !artifacts.has(owner) || !fact.evidence?.length || fact.reviewStatus === 'rejected') continue;
    const art = artifacts.get(owner);
    let val = '';
    if (fact.object?.kind === 'entity') {
      const concept = fact.predicate === 'decorated_with' ? motifConcepts.get(fact.object.id) : null;
      val = concept?.name || entities.get(fact.object.id)?.label || '';
    } else if (fact.object?.kind === 'event') {
      val = (events.get(fact.object.id)?.participants || [])
        .filter(p => p.role !== 'object')
        .map(p => entities.get(p.entityId)?.label || '')
        .filter(Boolean)
        .join('、');
    } else {
      val = fact.object?.raw || fact.object?.value || '';
    }
    if (!val) continue;
    const ev = fact.evidence[0];
    if (['出土', '出土地点'].includes(fact.label) && !art.findspot) art.findspot = val;
    if (!['period', 'made_of', 'decorated_with', 'uses_technique'].includes(fact.predicate)) continue;
    const kind = predToKind(fact.predicate);
    const triple = {
      id: fact.id,
      subjectId: art.id,
      subjectLabel: art.title,
      predicate: fact.predicate,
      predicateLabel: PREDICATE_LABELS[fact.predicate] || fact.label || fact.predicate,
      objectKey: `${kind}:${val}`,
      objectLabel: val,
      objectKind: kind,
      page: Number(ev.page || art.page || 1),
      locator: `第 ${ev.page || art.page} 页`,
      quote: ev.text || art.quote,
      evidenceId: fact.id,
      bbox: ev.bbox || art.bbox,
      pageUrl: `/api/reasoning/page/${ev.page || art.page}`,
      captionUrl: '',
      isInferred: false,
    };
    triples.push(triple);
    art.tripleIds.push(triple.id);
    if (fact.predicate === 'period' && !art.periods.includes(val)) art.periods.push(val);
    else if (fact.predicate === 'made_of' && !art.materials.includes(val)) art.materials.push(val);
    else if (fact.predicate === 'decorated_with' && !art.motifs.includes(val)) art.motifs.push(val);
    else if (fact.predicate === 'uses_technique' && !art.techniques.includes(val)) art.techniques.push(val);
  }

  return {
    title: graph.sourceContext?.title || '本地知识图谱',
    format: 'graph',
    artifacts,
    triples,
    tripleById: new Map(triples.map(t => [t.id, t])),
    pages: (graph.documents || []).map(d => ({ page: d.page, previewUrl: `/api/reasoning/page/${d.page}`, entries: 0 })),
  };
}

/**
 * Create the complete symbolic reasoning engine over any normalized KG.
 */
export function createKGReasoner(rawData) {
  const kg = normalizeKG(rawData);
  const allArtifacts = [...kg.artifacts.values()];

  // Build Ontology Axioms (TBox) dynamically from observed entities
  const axioms = [];
  const subclassMap = new Map(); // childKey -> parentKey
  const superclassChildren = new Map(); // parentKey -> Set<childKey>

  function registerSubClass(childKey, childLabel, parentKey, parentLabel, kind) {
    if (childKey === parentKey) return;
    if (subclassMap.has(childKey)) return;
    subclassMap.set(childKey, { parentKey, parentLabel, kind });
    if (!superclassChildren.has(parentKey)) superclassChildren.set(parentKey, new Set());
    superclassChildren.get(parentKey).add(childKey);
    axioms.push({
      id: `axiom:${childKey}->${parentKey}`,
      childKey, childLabel, parentKey, parentLabel, kind,
      formula: `${childLabel} ⊑ ${parentLabel}`,
      triple: [childLabel, 'rdfs:subClassOf', parentLabel],
    });
  }

  const observedEras = new Set();
  const observedMaterials = new Set();
  const observedMotifs = new Set();
  for (const t of kg.triples) {
    if (t.predicate === 'period') observedEras.add(t.objectLabel);
    if (t.predicate === 'made_of') observedMaterials.add(t.objectLabel);
    if (t.predicate === 'decorated_with') observedMotifs.add(t.objectLabel);
  }

  for (const p of observedEras) {
    const info = eraInfo(p);
    if (info.group && info.group !== p) {
      registerSubClass(`era:${p}`, p, `era:${info.group}`, info.group, 'era');
    }
    let child = info.group;
    while (ERA_PARENTS[child]) {
      const parent = ERA_PARENTS[child];
      registerSubClass(`era:${child}`, child, `era:${parent}`, parent, 'era');
      child = parent;
    }
  }
  for (const m of observedMaterials) {
    const cls = materialClass(m);
    if (cls) registerSubClass(`material:${m}`, m, `ont_material:${cls}`, cls, 'material');
  }
  for (const mo of observedMotifs) {
    const fam = motifFamily(mo);
    if (fam) registerSubClass(`motif:${mo}`, mo, `ont_motif:${fam}`, fam, 'motif');
  }

  // Forward-chaining RDFS materialized triples
  const inferredTriples = [];
  for (const t of kg.triples) {
    let key = t.objectKey;
    const visited = new Set([key]);
    const chain = [t.objectLabel];
    while (subclassMap.has(key)) {
      const sub = subclassMap.get(key);
      if (visited.has(sub.parentKey)) break;
      visited.add(sub.parentKey);
      chain.push(sub.parentLabel);
      const infPred = t.predicate === 'period' ? 'period_class'
        : (t.predicate === 'made_of' ? 'made_of_class' : 'motif_family');
      inferredTriples.push({
        id: `inf:${t.id}:${sub.parentKey}`,
        subjectId: t.subjectId,
        subjectLabel: t.subjectLabel,
        predicate: infPred,
        predicateLabel: PREDICATE_LABELS[infPred] || infPred,
        objectKey: sub.parentKey,
        objectLabel: sub.parentLabel,
        objectKind: sub.kind,
        page: t.page,
        locator: t.locator,
        quote: t.quote,
        evidenceId: t.evidenceId,
        bbox: t.bbox,
        pageUrl: t.pageUrl,
        captionUrl: t.captionUrl,
        isInferred: true,
        rule: 'RDFS_SUBCLASS',
        premiseTripleId: t.id,
        axiom: chain.join(' ⊑ '),
      });
      key = sub.parentKey;
    }
  }

  // Build entity lookup index (literal + ontology classes)
  function buildAdjacency(useOntology) {
    const adj = new Map(); // nodeKey -> Array<Edge>
    const nodes = new Map(); // nodeKey -> { key, kind, label, isOntology }

    const ensureNode = (key, kind, label, isOntology = false) => {
      if (!nodes.has(key)) nodes.set(key, { key, kind, label, isOntology });
      if (!adj.has(key)) adj.set(key, []);
    };

    const addEdge = (from, to, edge) => {
      adj.get(from).push({ ...edge, from, to });
      adj.get(to).push({ ...edge, from: to, to: from, reversed: !edge.reversed });
    };

    for (const art of allArtifacts) {
      ensureNode(`artifact:${art.id}`, 'artifact', art.title, false);
    }
    for (const t of kg.triples) {
      const sKey = `artifact:${t.subjectId}`;
      ensureNode(sKey, 'artifact', t.subjectLabel, false);
      ensureNode(t.objectKey, t.objectKind, t.objectLabel, false);
      addEdge(sKey, t.objectKey, {
        id: t.id,
        predicate: t.predicate,
        predicateLabel: t.predicateLabel,
        cost: 1.0,
        isInferred: false,
        triple: t,
        reversed: false,
      });
    }

    if (useOntology) {
      for (const ax of axioms) {
        ensureNode(ax.childKey, ax.kind, ax.childLabel, false);
        ensureNode(ax.parentKey, ax.kind, ax.parentLabel, true);
        addEdge(ax.childKey, ax.parentKey, {
          id: ax.id,
          predicate: 'rdfs:subClassOf',
          predicateLabel: '本体归类 ⊑',
          cost: 1.35, // Slightly higher than factual edge so direct factual paths always rank first
          isInferred: true,
          axiom: ax,
          reversed: false,
        });
      }
    }

    return { adj, nodes };
  }

  const graphLiteral = buildAdjacency(false);
  const graphOntology = buildAdjacency(true);

  /**
   * Resolve a user-supplied node query (key or label) into a canonical node key.
   */
  function resolveNode(input, useOntology = true) {
    const g = useOntology ? graphOntology : graphLiteral;
    if (!input) return null;
    const raw = String(input).trim();
    if (g.nodes.has(raw)) return g.nodes.get(raw);
    const nq = normText(raw);
    // Exact label match (prefer non-artifact concepts first, then artifacts)
    let artifactExact = null;
    for (const n of g.nodes.values()) {
      if (normText(n.label) === nq) {
        if (n.kind !== 'artifact') return n;
        artifactExact = n;
      }
    }
    if (artifactExact) return artifactExact;
    // Fuzzy contains fallback
    for (const n of g.nodes.values()) {
      if (n.kind !== 'artifact' && normText(n.label).includes(nq)) return n;
    }
    for (const n of g.nodes.values()) {
      if (normText(n.label).includes(nq)) return n;
    }
    return null;
  }

  /**
   * Expand an entity key to all matching literal values when useOntology is enabled.
   */
  function expandValues(kind, label, useOntology) {
    const out = new Set([label]);
    if (!useOntology) return out;
    if (kind === 'era') {
      const targetGrp = eraInfo(label).group;
      for (const p of observedEras) {
        let key = `era:${p}`;
        const visited = new Set();
        while (!visited.has(key)) {
          if (key === `era:${targetGrp}`) { out.add(p); break; }
          visited.add(key);
          const parent = subclassMap.get(key);
          if (!parent) break;
          key = parent.parentKey;
        }
      }
    } else if (kind === 'material') {
      const cls = MATERIAL_ONTOLOGY.some(m => m.cls === label) ? label : materialClass(label);
      if (cls) {
        for (const m of observedMaterials) {
          if (materialClass(m) === cls) out.add(m);
        }
      }
    } else if (kind === 'motif') {
      const fam = MOTIF_ONTOLOGY.some(m => m.cls === label) ? label : motifFamily(label);
      if (fam) {
        for (const mo of observedMotifs) {
          if (motifFamily(mo) === fam) out.add(mo);
        }
      }
    }
    return out;
  }

  function matchingArtifacts(kind, label, useOntology) {
    const accepted = expandValues(kind, label, useOntology);
    const pred = kind === 'era' ? 'period' : (kind === 'material' ? 'made_of' : 'decorated_with');
    return allArtifacts.filter(art => {
      const vals = pred === 'period' ? art.periods : (pred === 'made_of' ? art.materials : art.motifs);
      return vals.some(v => accepted.has(v));
    });
  }

  /**
   * ENGINE 1: Multi-Hop Semantic Path Discovery + Horn Rule Proof Trees
   */
  function findPaths(sourceInput, targetInput, opts = {}) {
    const useOntology = opts.useOntology !== false;
    const maxHops = Math.max(2, Math.min(8, Number(opts.maxHops) || 6));
    const maxPaths = Math.max(1, Math.min(8, Number(opts.maxPaths) || 4));
    const maxExpansions = Math.max(1, Math.min(14000, Number(opts.maxExpansions) || 14000));
    const g = useOntology ? graphOntology : graphLiteral;
    const src = resolveNode(sourceInput, useOntology);
    const dst = resolveNode(targetInput, useOntology);
    const endpointCoverage = node => {
      const arts = !node ? [] : node.kind === 'artifact'
        ? allArtifacts.filter(a => `artifact:${a.id}` === node.key)
        : ['era', 'material', 'motif'].includes(node.kind) ? matchingArtifacts(node.kind, node.label, useOntology) : [];
      return { total: arts.length, withMotifs: arts.filter(a => a.motifs.length).length,
        withMaterials: arts.filter(a => a.materials.length).length };
    };
    const context = {
      source: src || { label: String(sourceInput || ''), missing: true },
      target: dst || { label: String(targetInput || ''), missing: true },
      useOntology, coverage: { source: endpointCoverage(src), target: endpointCoverage(dst) },
    };
    const search = { maxHops, maxPaths, maxExpansions, expansions: 0,
      budgetExhausted: false, completeWithinConstraints: false, stoppedReason: 'missing_node' };

    if (!src || !dst) {
      return {
        ...context, search,
        ok: false,
        error: !src ? `未在图谱中找到起点「${sourceInput}」` : `未在图谱中找到终点「${targetInput}」`,
        paths: [], evidence: [], sparql: '',
      };
    }
    if (src.key === dst.key) {
      return { ...context, search: { ...search, stoppedReason: 'same_node' }, ok: false,
        error: '起点与终点相同，请选择两个不同节点。', paths: [], evidence: [], sparql: '' };
    }

    // Priority-BFS discovering diverse simple paths up to maxHops
    const queue = [{ node: src.key, cost: 0, edges: [], visited: new Set([src.key]) }];
    const found = [];
    const bridgeUsage = new Map();
    let expansions = 0;

    while (queue.length && found.length < maxPaths * 4 && expansions < maxExpansions) {
      // Pop lowest cost state
      let bestIdx = 0;
      for (let i = 1; i < queue.length; i++) {
        if (queue[i].cost < queue[bestIdx].cost) bestIdx = i;
      }
      const cur = queue.splice(bestIdx, 1)[0];
      expansions++;

      if (cur.edges.length >= maxHops) continue;
      const neighbors = g.adj.get(cur.node) || [];
      for (const edge of neighbors) {
        if (cur.visited.has(edge.to)) continue;
        // Avoid trivial back-and-forth across two ontology edges in a row
        const prevEdge = cur.edges[cur.edges.length - 1];
        if (prevEdge?.isInferred && edge.isInferred && prevEdge.from.startsWith('ont_')) continue;

        const nextEdges = [...cur.edges, edge];
        const penalty = (bridgeUsage.get(edge.to) || 0) * 0.45;
        const nextCost = cur.cost + edge.cost + penalty;

        if (edge.to === dst.key) {
          found.push({ cost: nextCost, edges: nextEdges });
          for (const e of nextEdges) {
            if (e.to !== dst.key) bridgeUsage.set(e.to, (bridgeUsage.get(e.to) || 0) + 1);
          }
          continue;
        }
        if (nextEdges.length < maxHops) {
          const nextVisited = new Set(cur.visited);
          nextVisited.add(edge.to);
          queue.push({ node: edge.to, cost: nextCost, edges: nextEdges, visited: nextVisited });
        }
      }
    }

    // Deduplicate & rank diverse paths (prefer shorter, factual-first, distinct bridge concepts)
    const seenSig = new Set();
    const ranked = [];
    found.sort((a, b) => a.edges.length - b.edges.length || a.cost - b.cost);
    for (const p of found) {
      const sig = p.edges.map(e => `${e.from}->${e.to}`).join('|');
      if (seenSig.has(sig)) continue;
      seenSig.add(sig);
      ranked.push(p);
      if (ranked.length >= maxPaths) break;
    }

    // Build formal proof trees & Horn rule annotations for each path
    const evidenceMap = new Map();
    const registerEv = triple => {
      if (!triple) return null;
      if (!evidenceMap.has(triple.id)) {
        evidenceMap.set(triple.id, { ref: `E${evidenceMap.size + 1}`, ...triple });
      }
      return evidenceMap.get(triple.id).ref;
    };

    const annotatedPaths = ranked.map((p, idx) => {
      const steps = p.edges.map(edge => {
        const fromNode = g.nodes.get(edge.from);
        const toNode = g.nodes.get(edge.to);
        const evRef = edge.triple ? registerEv(edge.triple) : null;
        return {
          fromKey: fromNode.key,
          fromLabel: fromNode.label,
          fromKind: fromNode.kind,
          fromIsOntology: fromNode.isOntology,
          toKey: toNode.key,
          toLabel: toNode.label,
          toKind: toNode.kind,
          toIsOntology: toNode.isOntology,
          predicate: edge.predicate,
          predicateLabel: edge.predicateLabel,
          reversed: Boolean(edge.reversed),
          isInferred: Boolean(edge.isInferred),
          axiom: edge.axiom?.formula || null,
          evidenceRef: evRef,
          tripleId: edge.triple?.id || null,
          artifactId: edge.triple?.subjectId || null,
          page: edge.triple?.page || null,
        };
      });

      const rulesTriggered = analyzePathRules(steps, g.nodes);
      const nodeKeys = [steps[0].fromKey, ...steps.map(s => s.toKey)];
      const artifactIds = [...new Set(nodeKeys.filter(k => k.startsWith('artifact:')).map(k => k.slice(9)))];

      return {
        id: `P${idx + 1}`,
        hops: steps.length,
        usesOntology: steps.some(s => s.isInferred),
        steps,
        nodeKeys,
        artifactIds,
        rulesTriggered,
        summary: buildPathSummary(src, dst, steps, rulesTriggered),
      };
    });

    search.expansions = expansions;
    search.completeWithinConstraints = queue.length === 0;
    search.budgetExhausted = queue.length > 0 && expansions >= maxExpansions;
    search.stoppedReason = search.completeWithinConstraints ? 'exhausted'
      : search.budgetExhausted ? 'expansion_budget' : 'candidate_limit';

    // Unknown reachability stays unknown when the bounded search stops early.
    let literalReachable = annotatedPaths.length > 0 ? true : search.completeWithinConstraints ? false : null;
    if (useOntology) {
      const litSrc = resolveNode(sourceInput, false);
      const litDst = resolveNode(targetInput, false);
      if (!litSrc || !litDst) literalReachable = false;
      else {
        const litRes = findPaths(litSrc.key, litDst.key, { useOntology: false, maxHops, maxPaths: 1, maxExpansions });
        literalReachable = litRes.paths.length > 0 ? true : litRes.search.completeWithinConstraints ? false : null;
      }
    }

    const sparql = buildPathSparql(src, dst, annotatedPaths[0], useOntology);

    return {
      ok: true,
      mode: 'path',
      ...context, search,
      literalReachable,
      ontologyUnlocked: useOntology && literalReachable === false && annotatedPaths.length > 0,
      paths: annotatedPaths,
      evidence: [...evidenceMap.values()],
      sparql,
    };
  }

  function analyzePathRules(steps, nodes) {
    const rules = [];
    const stepNodes = [nodes.get(steps[0].fromKey), ...steps.map(s => nodes.get(s.toKey))];
    const eras = stepNodes.filter(n => n.kind === 'era');
    const mats = stepNodes.filter(n => n.kind === 'material');
    const motifs = stepNodes.filter(n => n.kind === 'motif');
    const arts = stepNodes.filter(n => n.kind === 'artifact');

    if (steps.some(s => s.isInferred)) {
      const axs = [...new Set(steps.filter(s => s.axiom).map(s => s.axiom))];
      rules.push({
        code: 'RDFS_SUBCLASS',
        name: '本体子类泛化闭包',
        formula: axs.join(' ∧ '),
        detail: `通过 RDFS 本体层级（${axs.join('；')}）打通跨术语边界。`,
      });
    }
    const sharedMotif = motifs.find(m => steps.filter(s => !s.isInferred && s.predicate === 'decorated_with'
      && (s.fromKey === m.key || s.toKey === m.key)).length >= 2);
    if (sharedMotif) {
      rules.push({
        code: 'R3_CO_MOTIF',
        name: '同名纹样关联',
        formula: `decorated_with(A1, ${sharedMotif.label}) ∧ decorated_with(A2, ${sharedMotif.label}) ⇒ shares_recorded_motif(A1, A2)`,
        detail: `两件器物均标注「${sharedMotif.label}」。这只表示记录共现，不证明历史传播。`,
      });
    }
    if (eras.length >= 2 && motifs.length >= 1 && arts.length >= 2) {
      const e1 = eras[0], e2 = eras[eras.length - 1];
      const o1 = eraInfo(e1.label).order, o2 = eraInfo(e2.label).order;
      if (o1 !== o2) {
        const [early, late] = o1 < o2 ? [e1.label, e2.label] : [e2.label, e1.label];
        rules.push({
          code: 'R1_TEMPORAL_ASSOCIATION',
          name: '跨时代纹样关联候选',
          formula: `connected_via_motif(${early}, ${late}) ⇒ temporal_association_candidate(${early}, ${late})`,
          detail: `当前图谱通过纹样节点连接「${early}」与「${late}」。连通性不能单独证明传承，类别泛化也不意味着纹样相同。`,
        });
      }
    }
    if (mats.length >= 2 && motifs.length >= 1 && mats[0].label !== mats[mats.length - 1].label) {
      rules.push({
        code: 'R2_MATERIAL_ASSOCIATION',
        name: '跨材质纹样关联候选',
        formula: `connected_via_motif(${mats[0].label}, ${mats[mats.length - 1].label}) ⇒ material_association_candidate`,
        detail: `路径连接「${mats[0].label}」与「${mats[mats.length - 1].label}」，仅构成跨材质关联候选，不能证明纹样迁移或迁移方向。`,
      });
    }
    return rules;
  }

  function buildPathSummary(src, dst, steps, rules) {
    const chain = [steps[0].fromLabel, ...steps.map(s => s.toLabel)].join(' — ');
    const ruleNames = rules.map(r => r.name).join(' · ');
    return ruleNames ? `${chain}（触发：${ruleNames}）` : chain;
  }

  function buildPathSparql(src, dst, topPath, useOntology) {
    if (!topPath) {
      return `SELECT ?a1 ?a2 WHERE {\n  # ${src.label} 到 ${dst.label} 之间在当前约束下无连通路径\n  ?a1 ?p1 "${src.label}" .\n  ?a2 ?p2 "${dst.label}" .\n}`;
    }
    const artVars = new Map();
    const getVar = key => {
      if (!artVars.has(key)) artVars.set(key, `?artifact${artVars.size + 1}`);
      return artVars.get(key);
    };
    const body = [];
    for (const s of topPath.steps) {
      if (s.isInferred) {
        body.push(`  "${s.fromLabel}" rdfs:subClassOf "${s.toLabel}" .`);
      } else if (s.fromKind === 'artifact') {
        body.push(`  ${getVar(s.fromKey)} :${s.predicate} "${s.toLabel}" .`);
      } else if (s.toKind === 'artifact') {
        body.push(`  ${getVar(s.toKey)} :${s.predicate} "${s.fromLabel}" .`);
      }
    }
    const vars = [...artVars.values()];
    const lines = [];
    if (useOntology) lines.push('# 启用 RDFS 本体闭包 (rdfs:subClassOf)');
    lines.push(`SELECT DISTINCT ${vars.length ? vars.join(' ') : '*'} WHERE {`);
    lines.push(...body);
    lines.push('}');
    lines.push('LIMIT 30');
    return lines.join('\n');
  }

  /**
   * ENGINE 2: Dual-Entity Set Comparison & Negation Reasoning (Intersection / Difference / NOT EXISTS)
   */
  function compareEntities(kind, entityA, entityB, opts = {}) {
    const useOntology = opts.useOntology !== false;
    if (!['era', 'material', 'motif'].includes(kind)) {
      return { ok: false, error: '对比维度必须是 era、material 或 motif。' };
    }
    const artsA = matchingArtifacts(kind, entityA, useOntology);
    const artsB = matchingArtifacts(kind, entityB, useOntology);
    if (!artsA.length || !artsB.length) {
      return {
        ok: false,
        error: !artsA.length ? `未找到与「${entityA}」关联的图谱条目` : `未找到与「${entityB}」关联的图谱条目`,
      };
    }

    // Target comparison axis: Era/Material -> compare Motifs (+ secondary axis); Motif -> compare Materials + Eras
    const primaryAxis = kind === 'motif' ? 'material' : 'motif';
    const secondaryAxis = kind === 'era' ? 'material' : 'era';

    const collectAxis = (arts, axis) => {
      const map = new Map(); // label -> { label, count, artifacts, triples }
      const pred = axis === 'era' ? 'period' : (axis === 'material' ? 'made_of' : 'decorated_with');
      for (const art of arts) {
        for (const tid of art.tripleIds) {
          const t = kg.tripleById.get(tid);
          if (!t || t.predicate !== pred) continue;
          const label = (useOntology && axis === 'era') ? eraInfo(t.objectLabel).group
            : ((useOntology && axis === 'material' && materialClass(t.objectLabel)) ? materialClass(t.objectLabel) : t.objectLabel);
          if (!map.has(label)) map.set(label, { label, count: 0, artifactIds: [], triples: [] });
          const rec = map.get(label);
          if (!rec.artifactIds.includes(art.id)) {
            rec.artifactIds.push(art.id);
            rec.count++;
          }
          rec.triples.push(t);
        }
      }
      return map;
    };

    const evidenceMap = new Map();
    const regEv = t => {
      if (!evidenceMap.has(t.id)) evidenceMap.set(t.id, { ref: `E${evidenceMap.size + 1}`, ...t });
      return evidenceMap.get(t.id).ref;
    };

    const diffAxis = axis => {
      const mA = collectAxis(artsA, axis);
      const mB = collectAxis(artsB, axis);
      const keys = new Set([...mA.keys(), ...mB.keys()]);
      const shared = [], onlyA = [], onlyB = [];
      for (const k of keys) {
        const a = mA.get(k), b = mB.get(k);
        if (a && b) {
          shared.push({
            label: k, kind: axis, countA: a.count, countB: b.count,
            artifactIdsA: a.artifactIds, artifactIdsB: b.artifactIds,
            refsA: a.triples.slice(0, 3).map(regEv),
            refsB: b.triples.slice(0, 3).map(regEv),
          });
        } else if (a) {
          onlyA.push({
            label: k, kind: axis, count: a.count, artifactIds: a.artifactIds,
            refs: a.triples.slice(0, 3).map(regEv),
          });
        } else if (b) {
          onlyB.push({
            label: k, kind: axis, count: b.count, artifactIds: b.artifactIds,
            refs: b.triples.slice(0, 3).map(regEv),
          });
        }
      }
      shared.sort((x, y) => (y.countA + y.countB) - (x.countA + x.countB));
      onlyA.sort((x, y) => y.count - x.count);
      onlyB.sort((x, y) => y.count - x.count);
      const union = keys.size;
      const coveredA = new Set([...mA.values()].flatMap(value => value.artifactIds)).size;
      const coveredB = new Set([...mB.values()].flatMap(value => value.artifactIds)).size;
      const comparable = coveredA > 0 && coveredB > 0;
      const jaccard = comparable && union ? Number((shared.length / union).toFixed(3)) : null;
      return { axis, shared, onlyA, onlyB, jaccard, comparable,
        coverage: { withValuesA: coveredA, totalA: artsA.length, withValuesB: coveredB, totalB: artsB.length },
        interpretation: 'Current recorded candidates only. Missing annotations are not evidence of historical absence; shared labels do not prove transmission.' };
    };

    const primary = diffAxis(primaryAxis);
    const secondary = diffAxis(secondaryAxis);

    const predA = kind === 'era' ? (useOntology ? ':period_class' : ':period')
      : (kind === 'material' ? (useOntology ? ':made_of_class' : ':made_of') : ':decorated_with');
    const targetPred = primaryAxis === 'motif' ? ':decorated_with' : (primaryAxis === 'material' ? ':made_of' : ':period');
    const valA = (useOntology && kind === 'material' && materialClass(entityA)) ? materialClass(entityA) : entityA;
    const valB = (useOntology && kind === 'material' && materialClass(entityB)) ? materialClass(entityB) : entityB;

    const sparql = [
      `# 当前图谱差集：找出「${entityA}」已录入而「${entityB}」未检索到的${PREDICATE_LABELS[targetPred.slice(1)]}；不代表历史独有`,
      `SELECT DISTINCT ?target ?artifact WHERE {`,
      `  ?artifact ${predA} "${valA}" .`,
      `  ?artifact ${targetPred} ?target .`,
      `  FILTER NOT EXISTS {`,
      `    ?other ${predA} "${valB}" .`,
      `    ?other ${targetPred} ?target .`,
      `  }`,
      `}`,
      `LIMIT 30`,
    ].join('\n');

    return {
      ok: true,
      mode: 'compare',
      kind,
      entityA,
      entityB,
      useOntology,
      countA: artsA.length,
      countB: artsB.length,
      artifactIdsA: artsA.map(a => a.id),
      artifactIdsB: artsB.map(a => a.id),
      primary,
      secondary,
      comparisonScope: useOntology && kind === 'era' ? 'Era subclasses and their transitive parents are included.' : 'Literal labels or selected ontology expansion.',
      absenceIsEvidence: false,
      interpretation: '候选记录的共有与差集；缺少标注不等于历史不存在，共有纹样也不能单独证明传承。',
      evidence: [...evidenceMap.values()],
      sparql,
    };
  }

  /**
   * ENGINE 2B: Real SPARQL-lite Query Execution Engine (HW3)
   * Supports SELECT [DISTINCT], WHERE { triple patterns + ; shorthand },
   * FILTER (=, !=, CONTAINS, REGEX), FILTER NOT EXISTS { ... }, ORDER BY, LIMIT.
   */
  function runSparql(queryText, opts = {}) {
    const t0 = performance.now ? performance.now() : Date.now();
    const useOntology = opts.useOntology !== false;
    const cleaned = String(queryText || '')
      .replace(/#[^\n]*/g, '')
      .trim();
    if (!cleaned) return { ok: false, error: 'SPARQL 查询语句为空。' };

    const headMatch = cleaned.match(/SELECT\s+(DISTINCT\s+)?([\s\S]+?)\s+WHERE\s*\{([\s\S]+)\}([\s\S]*)$/i);
    if (!headMatch) {
      return { ok: false, error: '语法错误：请使用标准 SELECT ?var WHERE { ... } 格式。' };
    }
    const isDistinct = Boolean(headMatch[1]);
    const selectClause = headMatch[2].trim();
    const whereBody = headMatch[3].trim();
    const tailClause = headMatch[4].trim();

    // Parse SELECT variables
    const selectVars = selectClause === '*'
      ? null
      : [...selectClause.matchAll(/\?[A-Za-z_]\w*/g)].map(m => m[0]);
    if (selectVars && !selectVars.length) {
      return { ok: false, error: 'SELECT 子句中未检测到变量（如 ?motif ?artifact）。' };
    }

    // Parse LIMIT and ORDER BY
    const limitMatch = tailClause.match(/LIMIT\s+(\d+)/i);
    const limit = limitMatch ? Math.max(1, Math.min(200, Number(limitMatch[1]))) : 50;
    const orderMatch = tailClause.match(/ORDER\s+BY\s+(DESC|ASC)?\s*\(?(\?[A-Za-z_]\w*)\)?/i);

    // Extract FILTER NOT EXISTS { ... } blocks and scalar FILTER ( ... ) clauses
    const notExistsBlocks = [];
    let bodyNoNot = whereBody.replace(/FILTER\s+NOT\s+EXISTS\s*\{([\s\S]*?)\}/gi, (_, inner) => {
      notExistsBlocks.push(parseTriplePatterns(inner));
      return '';
    });

    const scalarFilters = [];
    bodyNoNot = bodyNoNot.replace(/FILTER\s*\(([\s\S]*?)\)/gi, (_, expr) => {
      scalarFilters.push(expr.trim());
      return '';
    });

    const patterns = parseTriplePatterns(bodyNoNot);
    if (!patterns.length) {
      return { ok: false, error: 'WHERE 子句中未解析到有效的三元组模式（例如 ?a :decorated_with ?m .）。' };
    }

    // Build unified triple table for SPARQL evaluation
    const allTriples = buildSparqlTriples(useOntology);

    // Execute nested-loop join over BGP patterns
    let bindings = [{}];
    const plan = [];
    for (const pat of patterns) {
      const next = [];
      let matched = 0;
      for (const env of bindings) {
        for (const tr of allTriples) {
          const merged = matchPattern(pat, tr, env);
          if (merged) {
            merged.__triples = [...(env.__triples || []), ...(tr.rawTriple ? [tr.rawTriple] : [])];
            merged.__artifacts = [...(env.__artifacts || []), ...(tr.artifactId ? [tr.artifactId] : [])];
            next.push(merged);
            matched++;
            if (next.length > 6000) break;
          }
        }
        if (next.length > 6000) break;
      }
      plan.push(`BGP(${pat.s} ${pat.p} ${pat.o}) → ${matched} 匹配`);
      bindings = next;
      if (!bindings.length) break;
    }

    // Apply scalar FILTERs
    for (const expr of scalarFilters) {
      bindings = bindings.filter(env => evalFilter(expr, env));
      plan.push(`FILTER(${expr}) → ${bindings.length}`);
    }

    // Apply FILTER NOT EXISTS blocks (negation-as-failure!)
    for (const negPats of notExistsBlocks) {
      if (!negPats.length) continue;
      bindings = bindings.filter(env => {
        let sub = [env];
        for (const pat of negPats) {
          const next = [];
          for (const se of sub) {
            for (const tr of allTriples) {
              const m = matchPattern(pat, tr, se);
              if (m) { next.push(m); break; } // existence check needs only 1 witness
            }
            if (next.length) break;
          }
          sub = next;
          if (!sub.length) return true; // NOT EXISTS satisfied!
        }
        return false; // witness exists -> exclude row
      });
      plan.push(`FILTER NOT EXISTS(${negPats.length} 模式) → ${bindings.length}`);
    }

    // Determine output columns
    const vars = selectVars || [...new Set(bindings.flatMap(b => Object.keys(b).filter(k => k.startsWith('?'))))];

    // ORDER BY
    if (orderMatch) {
      const dir = (orderMatch[1] || 'ASC').toUpperCase() === 'DESC' ? -1 : 1;
      const oVar = orderMatch[2];
      bindings.sort((a, b) => String(a[oVar] ?? '').localeCompare(String(b[oVar] ?? ''), 'zh-Hans') * dir);
    }

    // DISTINCT & projection
    const rows = [];
    const seen = new Set();
    const matchedArtifactIds = new Set();
    const evidenceMap = new Map();
    for (const env of bindings) {
      const proj = {};
      for (const v of vars) proj[v] = env[v] ?? '';
      if (isDistinct) {
        const key = JSON.stringify(proj);
        if (seen.has(key)) continue;
        seen.add(key);
      }
      rows.push(proj);
      for (const aid of (env.__artifacts || [])) matchedArtifactIds.add(aid);
      for (const rt of (env.__triples || [])) {
        if (!evidenceMap.has(rt.id)) evidenceMap.set(rt.id, { ref: `E${evidenceMap.size + 1}`, ...rt });
      }
      if (rows.length >= limit) break;
    }

    const elapsedMs = Number(((performance.now ? performance.now() : Date.now()) - t0).toFixed(1));
    return {
      ok: true,
      mode: 'sparql',
      useOntology,
      variables: vars,
      rows,
      totalBindings: bindings.length,
      matchedArtifactIds: [...matchedArtifactIds],
      evidence: [...evidenceMap.values()].slice(0, 40),
      plan,
      elapsedMs,
      sparql: queryText,
    };
  }

  function parseTriplePatterns(block) {
    const out = [];
    // Split on '.' outside quotes
    const statements = [];
    let cur = '', inQ = false;
    for (let i = 0; i < block.length; i++) {
      const ch = block[i];
      if (ch === '"' && block[i - 1] !== '\\') inQ = !inQ;
      if (ch === '.' && !inQ) {
        if (cur.trim()) statements.push(cur.trim());
        cur = '';
      } else {
        cur += ch;
      }
    }
    if (cur.trim()) statements.push(cur.trim());

    for (const stmt of statements) {
      // Support ';' shorthand: ?s :p1 ?o1 ; :p2 ?o2
      const parts = [];
      let seg = '', q = false;
      for (let i = 0; i < stmt.length; i++) {
        const ch = stmt[i];
        if (ch === '"' && stmt[i - 1] !== '\\') q = !q;
        if (ch === ';' && !q) { parts.push(seg.trim()); seg = ''; }
        else seg += ch;
      }
      if (seg.trim()) parts.push(seg.trim());

      let subject = null;
      for (const part of parts) {
        const toks = tokenizeTriple(part);
        if (toks.length >= 3) {
          subject = toks[0];
          out.push({ s: toks[0], p: toks[1], o: toks[2] });
        } else if (toks.length === 2 && subject) {
          out.push({ s: subject, p: toks[0], o: toks[1] });
        }
      }
    }
    return out;
  }

  function tokenizeTriple(str) {
    const toks = [];
    const re = /"([^"]*)"|\S+/g;
    let m;
    while ((m = re.exec(str))) {
      toks.push(m[1] !== undefined ? `"${m[1]}"` : m[0]);
    }
    return toks;
  }

  function buildSparqlTriples(useOntology) {
    const list = [];
    for (const art of allArtifacts) {
      list.push({ s: art.title, p: ':label', o: art.title, artifactId: art.id });
      list.push({ s: art.title, p: ':page', o: String(art.page), artifactId: art.id });
      if (art.findspot) list.push({ s: art.title, p: ':findspot', o: art.findspot, artifactId: art.id });
    }
    for (const t of kg.triples) {
      list.push({ s: t.subjectLabel, p: ':' + t.predicate, o: t.objectLabel, artifactId: t.subjectId, rawTriple: t });
    }
    if (useOntology) {
      for (const inf of inferredTriples) {
        list.push({ s: inf.subjectLabel, p: ':' + inf.predicate, o: inf.objectLabel, artifactId: inf.subjectId, rawTriple: kg.tripleById.get(inf.premiseTripleId) });
      }
      for (const ax of axioms) {
        list.push({ s: ax.childLabel, p: 'rdfs:subClassOf', o: ax.parentLabel });
      }
      // Also expose era macro-class on direct :period_class even for already-canonical eras
      for (const t of kg.triples) {
        if (t.predicate === 'period') {
          const grp = eraInfo(t.objectLabel).group;
          list.push({ s: t.subjectLabel, p: ':period_class', o: grp, artifactId: t.subjectId, rawTriple: t });
        } else if (t.predicate === 'made_of') {
          const cls = materialClass(t.objectLabel) || t.objectLabel;
          list.push({ s: t.subjectLabel, p: ':made_of_class', o: cls, artifactId: t.subjectId, rawTriple: t });
        } else if (t.predicate === 'decorated_with') {
          const fam = motifFamily(t.objectLabel) || t.objectLabel;
          list.push({ s: t.subjectLabel, p: ':motif_family', o: fam, artifactId: t.subjectId, rawTriple: t });
        }
      }
    }
    return list;
  }

  function matchTerm(term, actual, env) {
    if (term.startsWith('?')) {
      if (term in env) return env[term] === actual ? env : null;
      return { ...env, [term]: actual };
    }
    const lit = term.startsWith('"') && term.endsWith('"') ? term.slice(1, -1) : term;
    return lit === actual ? env : null;
  }

  function matchPattern(pat, tr, env) {
    const e1 = matchTerm(pat.p, tr.p, env);
    if (!e1) return null;
    const e2 = matchTerm(pat.s, tr.s, e1);
    if (!e2) return null;
    return matchTerm(pat.o, tr.o, e2);
  }

  function evalFilter(expr, env) {
    const resolveVal = tok => {
      const t = tok.trim();
      if (t.startsWith('?')) return env[t] ?? '';
      if ((t.startsWith('"') && t.endsWith('"')) || (t.startsWith("'") && t.endsWith("'"))) return t.slice(1, -1);
      return t;
    };
    const mContains = expr.match(/^CONTAINS\s*\(([^,]+),([^)]+)\)$/i);
    if (mContains) return String(resolveVal(mContains[1])).includes(String(resolveVal(mContains[2])));
    const mRegex = expr.match(/^REGEX\s*\(([^,]+),([^)]+)\)$/i);
    if (mRegex) {
      try { return new RegExp(String(resolveVal(mRegex[2])), 'i').test(String(resolveVal(mRegex[1]))); }
      catch { return false; }
    }
    const mCmp = expr.match(/^(.+?)\s*(!=|>=|<=|=|>|<)\s*(.+)$/);
    if (mCmp) {
      const l = resolveVal(mCmp[1]), op = mCmp[2], r = resolveVal(mCmp[3]);
      if (op === '=') return String(l) === String(r);
      if (op === '!=') return String(l) !== String(r);
      const ln = Number(l), rn = Number(r);
      if (Number.isFinite(ln) && Number.isFinite(rn)) {
        if (op === '>') return ln > rn;
        if (op === '<') return ln < rn;
        if (op === '>=') return ln >= rn;
        if (op === '<=') return ln <= rn;
      }
      return op === '>' ? String(l) > String(r) : String(l) < String(r);
    }
    return true;
  }

  /**
   * ENGINE 3: Zero-LLM Missing Knowledge Completion (Association Rules + Adamic-Adar Link Prediction)
   */
  function predictMissing(opts = {}) {
    const targetPredicate = ['period', 'made_of', 'decorated_with'].includes(opts.targetPredicate)
      ? opts.targetPredicate : 'period';
    const useOntology = opts.useOntology !== false;
    const limit = Math.max(1, Math.min(40, Number(opts.limit) || 18));
    const filterArtifactId = opts.artifactId || null;

    const getTargetVals = art => {
      if (targetPredicate === 'period') {
        return useOntology ? [...new Set(art.periods.map(p => eraInfo(p).group))] : art.periods;
      }
      if (targetPredicate === 'made_of') {
        return useOntology ? [...new Set(art.materials.map(m => materialClass(m) || m))] : art.materials;
      }
      return art.motifs;
    };

    const getFeatures = art => {
      const feats = [];
      if (targetPredicate !== 'period') {
        for (const p of art.periods) {
          const val = useOntology ? eraInfo(p).group : p;
          feats.push({ key: `era:${val}`, kind: 'era', label: val });
        }
      }
      if (targetPredicate !== 'made_of') {
        for (const m of art.materials) {
          feats.push({ key: `material:${m}`, kind: 'material', label: m });
          if (useOntology) {
            const cls = materialClass(m);
            if (cls && cls !== m) feats.push({ key: `ont_material:${cls}`, kind: 'material', label: cls });
          }
        }
      }
      if (targetPredicate !== 'decorated_with') {
        for (const mo of art.motifs) {
          feats.push({ key: `motif:${mo}`, kind: 'motif', label: mo });
          if (useOntology) {
            const fam = motifFamily(mo);
            if (fam && fam !== mo) feats.push({ key: `ont_motif:${fam}`, kind: 'motif', label: fam });
          }
        }
      }
      // Deduplicate by key
      return [...new Map(feats.map(f => [f.key, f])).values()];
    };

    // 1) Mine exact empirical distributions & association rules on observed artifacts
    const observed = allArtifacts.filter(a => getTargetVals(a).length > 0);
    const totalObs = Math.max(1, observed.length);
    const priorCounts = new Map(); // targetVal -> count
    const featTotal = new Map();   // featKey -> count among observed
    const featTarget = new Map();  // featKey -> Map<targetVal, Artifact[]>
    const pairTotal = new Map();   // f1|f2 -> count
    const pairTarget = new Map();  // f1|f2 -> Map<targetVal, Artifact[]>

    for (const art of observed) {
      const tVals = getTargetVals(art);
      const feats = getFeatures(art);
      for (const tv of tVals) priorCounts.set(tv, (priorCounts.get(tv) || 0) + 1);

      for (const f of feats) {
        featTotal.set(f.key, (featTotal.get(f.key) || 0) + 1);
        if (!featTarget.has(f.key)) featTarget.set(f.key, new Map());
        const tm = featTarget.get(f.key);
        for (const tv of tVals) {
          if (!tm.has(tv)) tm.set(tv, []);
          tm.get(tv).push(art);
        }
      }
      // 2-premise conjunctions (e.g. material + motif -> era)
      for (let i = 0; i < feats.length; i++) {
        for (let j = i + 1; j < feats.length; j++) {
          if (feats[i].kind === feats[j].kind) continue;
          const pk = [feats[i].key, feats[j].key].sort().join('+');
          pairTotal.set(pk, (pairTotal.get(pk) || 0) + 1);
          if (!pairTarget.has(pk)) pairTarget.set(pk, new Map());
          const tm = pairTarget.get(pk);
          for (const tv of tVals) {
            if (!tm.has(tv)) tm.set(tv, []);
            tm.get(tv).push(art);
          }
        }
      }
    }

    // 2) Score candidate missing predictions for artifacts lacking targetPredicate
    const candidates = allArtifacts.filter(a => {
      if (filterArtifactId) return a.id === filterArtifactId;
      return getTargetVals(a).length === 0;
    });

    const predictions = [];
    const evidenceMap = new Map();
    const regArtEv = (art, pred) => {
      const tr = art.tripleIds.map(id => kg.tripleById.get(id)).find(t => t && t.predicate === pred)
        || art.tripleIds.map(id => kg.tripleById.get(id)).find(Boolean);
      if (!tr) return null;
      if (!evidenceMap.has(tr.id)) evidenceMap.set(tr.id, { ref: `E${evidenceMap.size + 1}`, ...tr });
      return evidenceMap.get(tr.id).ref;
    };

    for (const art of candidates) {
      const feats = getFeatures(art);
      if (!feats.length) continue;

      const scoreByTarget = new Map(); // targetVal -> { aaScore, bestRule, supporters: Map<artId, art> }

      // Adamic-Adar weighted feature voting + 1-premise association rule stats
      for (const f of feats) {
        const deg = featTotal.get(f.key) || 0;
        if (deg < 1) continue;
        const aaWeight = 1 / Math.log2(deg + 2.2);
        const tm = featTarget.get(f.key);
        if (!tm) continue;
        for (const [tv, supArts] of tm.entries()) {
          const conf = supArts.length / deg;
          const prior = (priorCounts.get(tv) || 1) / totalObs;
          const lift = conf / Math.max(0.01, prior);
          // Skip uninformative rules when lift < 1.02 and conf < 0.55
          if (conf < 0.45 && lift < 1.15) continue;
          if (!scoreByTarget.has(tv)) {
            scoreByTarget.set(tv, { aaScore: 0, maxConf: 0, maxLift: 0, bestRule: null, supporters: new Map() });
          }
          const entry = scoreByTarget.get(tv);
          // Concrete features weigh slightly more than broad ontology fallback
          const specificityBoost = f.key.startsWith('ont_') ? 0.65 : 1.0;
          entry.aaScore += aaWeight * conf * Math.min(3.0, lift) * specificityBoost;
          for (const sa of supArts) entry.supporters.set(sa.id, sa);
          if (conf * Math.log2(supArts.length + 1.5) * specificityBoost > (entry.bestRule?.rank || 0)) {
            entry.maxConf = conf;
            entry.maxLift = lift;
            entry.bestRule = {
              rank: conf * Math.log2(supArts.length + 1.5) * specificityBoost,
              premises: [f.label],
              support: supArts.length,
              premiseTotal: deg,
              confidence: conf,
              lift,
              formula: `{${f.label}} ⇒ ${PREDICATE_LABELS[targetPredicate]}=${tv}`,
            };
          }
        }
      }

      // 2-premise conjunction rules (high precision!)
      for (let i = 0; i < feats.length; i++) {
        for (let j = i + 1; j < feats.length; j++) {
          if (feats[i].kind === feats[j].kind) continue;
          const pk = [feats[i].key, feats[j].key].sort().join('+');
          const deg = pairTotal.get(pk) || 0;
          if (deg < 1) continue;
          const tm = pairTarget.get(pk);
          if (!tm) continue;
          for (const [tv, supArts] of tm.entries()) {
            const conf = supArts.length / deg;
            const prior = (priorCounts.get(tv) || 1) / totalObs;
            const lift = conf / Math.max(0.01, prior);
            if (conf < 0.5) continue;
            if (!scoreByTarget.has(tv)) {
              scoreByTarget.set(tv, { aaScore: 0, maxConf: 0, maxLift: 0, bestRule: null, supporters: new Map() });
            }
            const entry = scoreByTarget.get(tv);
            entry.aaScore += 1.35 * conf * Math.min(3.5, lift);
            for (const sa of supArts) entry.supporters.set(sa.id, sa);
            const rank = conf * Math.log2(supArts.length + 2.0) * 1.45;
            if (rank > (entry.bestRule?.rank || 0)) {
              entry.maxConf = conf;
              entry.maxLift = lift;
              entry.bestRule = {
                rank,
                premises: [feats[i].label, feats[j].label],
                support: supArts.length,
                premiseTotal: deg,
                confidence: conf,
                lift,
                formula: `{${feats[i].label} ∧ ${feats[j].label}} ⇒ ${PREDICATE_LABELS[targetPredicate]}=${tv}`,
              };
            }
          }
        }
      }

      // Pick top predicted target value for this artifact
      const rankedTargets = [...scoreByTarget.entries()]
        .filter(([, v]) => v.bestRule)
        .sort((a, b) => b[1].aaScore - a[1].aaScore);
      if (!rankedTargets.length) continue;

      const [bestVal, info] = rankedTargets[0];
      const totalScore = rankedTargets.reduce((s, [, v]) => s + v.aaScore, 0);
      const posterior = info.aaScore / Math.max(0.001, totalScore);
      // Calibrated confidence combining empirical rule confidence, posterior dominance, and sample size damping
      const sampleFactor = info.supporters.size / (info.supporters.size + 1.4);
      const calibrated = Math.max(0.38, Math.min(0.96,
        (0.50 * info.bestRule.confidence + 0.35 * posterior + 0.15 * Math.min(1, info.bestRule.lift / 2.5)) * (0.68 + 0.32 * sampleFactor),
      ));

      const supList = [...info.supporters.values()].slice(0, 4);
      const supRefs = supList.map(sa => ({
        artifactId: sa.id,
        title: sa.title,
        page: sa.page,
        volume: sa.volume,
        volumePage: sa.volumePage,
        sourceName: sa.sourceName,
        ref: regArtEv(sa, targetPredicate),
      }));

      predictions.push({
        id: `R${predictions.length + 1}`,
        artifactId: art.id,
        artifactTitle: art.title,
        page: art.page,
        volume: art.volume,
        volumePage: art.volumePage,
        sourceName: art.sourceName,
        predicate: targetPredicate,
        predicateLabel: PREDICATE_LABELS[targetPredicate],
        predictedValue: bestVal,
        predictedKind: predToKind(targetPredicate),
        confidence: Number(calibrated.toFixed(2)),
        ruleConfidence: Number(info.bestRule.confidence.toFixed(2)),
        lift: Number(info.bestRule.lift.toFixed(2)),
        supportCount: info.supporters.size,
        ruleFormula: info.bestRule.formula,
        premises: info.bestRule.premises,
        supporters: supRefs,
        explanation: `依据关联规则 ${info.bestRule.formula}（条件置信度 ${Math.round(info.bestRule.confidence * 100)}%，提升度 ${info.bestRule.lift.toFixed(2)}×，${info.supporters.size} 条同邻域实证支撑）推导出候选${PREDICATE_LABELS[targetPredicate]}「${bestVal}」。`,
      });
    }

    predictions.sort((a, b) => b.confidence - a.confidence || b.supportCount - a.supportCount || b.lift - a.lift);
    const top = predictions.slice(0, limit).map((p, i) => ({ ...p, id: `R${i + 1}` }));

    const sparql = [
      `# 关联规则与共同邻居补全目标：检索缺失 :${targetPredicate} 的候选条目`,
      `SELECT DISTINCT ?artifact ?feature WHERE {`,
      `  ?artifact :${targetPredicate === 'decorated_with' ? 'made_of' : 'decorated_with'} ?feature .`,
      `  FILTER NOT EXISTS { ?artifact :${targetPredicate} ?existing . }`,
      `}`,
      `LIMIT ${limit}`,
    ].join('\n');

    return {
      ok: true,
      mode: 'predict',
      targetPredicate,
      useOntology,
      totalMissing: candidates.length,
      predictions: top,
      evidence: [...evidenceMap.values()],
      sparql,
    };
  }

  /**
   * Structured filter query (supports Ontology expansion + Exclusion/Negation)
   */
  function queryArtifacts(filters = {}) {
    const useOntology = filters.useOntology !== false;
    const eraSet = filters.period ? expandValues('era', filters.period, useOntology) : null;
    const matSet = filters.material ? expandValues('material', filters.material, useOntology) : null;
    const motifSet = filters.motif ? expandValues('motif', filters.motif, useOntology) : null;
    const exclEra = filters.excludePeriod ? expandValues('era', filters.excludePeriod, useOntology) : null;
    const exclMat = filters.excludeMaterial ? expandValues('material', filters.excludeMaterial, useOntology) : null;
    const exclMotif = filters.excludeMotif ? expandValues('motif', filters.excludeMotif, useOntology) : null;

    const matchSet = (actuals, targetSet, rawQuery) => {
      if (actuals.some(v => targetSet.has(v))) return true;
      const nq = normText(rawQuery);
      return actuals.some(v => normText(v).includes(nq));
    };

    const hits = [];
    const evidenceMap = new Map();
    const reg = t => {
      if (!evidenceMap.has(t.id)) evidenceMap.set(t.id, { ref: `E${evidenceMap.size + 1}`, ...t });
      return evidenceMap.get(t.id).ref;
    };

    for (const art of allArtifacts) {
      if (filters.name && !normText(art.title).includes(normText(filters.name))) continue;
      if (filters.place && !normText(art.findspot + ' ' + art.quote).includes(normText(filters.place))) continue;
      if (eraSet && !matchSet(art.periods, eraSet, filters.period)) continue;
      if (matSet && !matchSet(art.materials, matSet, filters.material)) continue;
      if (motifSet && !matchSet(art.motifs, motifSet, filters.motif)) continue;
      if (exclEra && matchSet(art.periods, exclEra, filters.excludePeriod)) continue;
      if (exclMat && matchSet(art.materials, exclMat, filters.excludeMaterial)) continue;
      if (exclMotif && matchSet(art.motifs, exclMotif, filters.excludeMotif)) continue;

      const triples = art.tripleIds.map(id => kg.tripleById.get(id)).filter(Boolean);
      const refs = triples.map(reg);
      hits.push({
        id: art.id,
        title: art.title,
        page: art.page,
        volume: art.volume,
        volumePage: art.volumePage,
        sourceName: art.sourceName,
        locator: art.locator,
        findspot: art.findspot,
        periods: art.periods,
        materials: art.materials,
        motifs: art.motifs,
        quote: art.quote,
        refs,
      });
    }

    return {
      ok: true,
      mode: 'query',
      useOntology,
      count: hits.length,
      items: hits,
      evidence: [...evidenceMap.values()],
    };
  }

  /**
   * Inspect full evidence of one artifact by ID or title.
   */
  function inspectEvidence(query) {
    const raw = String(query || '').trim();
    const art = kg.artifacts.get(raw)
      || allArtifacts.find(a => normText(a.title) === normText(raw))
      || allArtifacts.find(a => normText(a.title).includes(normText(raw)));
    if (!art) return { ok: false, error: `未找到器物「${query}」` };
    const triples = art.tripleIds.map(id => kg.tripleById.get(id)).filter(Boolean);
    const evidence = triples.map((t, i) => ({ ref: `E${i + 1}`, ...t }));
    const predPeriod = !art.periods.length ? predictMissing({ targetPredicate: 'period', artifactId: art.id, limit: 1 }).predictions[0] : null;
    const predMotif = !art.motifs.length ? predictMissing({ targetPredicate: 'decorated_with', artifactId: art.id, limit: 1 }).predictions[0] : null;
    return {
      ok: true,
      artifact: art,
      evidence,
      predictions: [predPeriod, predMotif].filter(Boolean),
    };
  }

  /**
   * Dynamic, book-agnostic summary + suggested reasoning showcase prompts derived from actual data.
   */
  function getCatalogSummary() {
    const eraCounts = new Map();
    const matCounts = new Map();
    const motifCounts = new Map();
    for (const art of allArtifacts) {
      for (const p of new Set(art.periods.map(x => eraInfo(x).group))) eraCounts.set(p, (eraCounts.get(p) || 0) + 1);
      for (const m of art.materials) matCounts.set(m, (matCounts.get(m) || 0) + 1);
      for (const mo of art.motifs) motifCounts.set(mo, (motifCounts.get(mo) || 0) + 1);
    }
    const eras = [...eraCounts.entries()].sort((a, b) => eraInfo(a[0]).order - eraInfo(b[0]).order).map(([name, count]) => ({ name, count }));
    const materials = [...matCounts.entries()].sort((a, b) => b[1] - a[1]).map(([name, count]) => ({ name, count }));
    const motifs = [...motifCounts.entries()].sort((a, b) => b[1] - a[1]).map(([name, count]) => ({ name, count }));

    // Pick observed labels; this does not guarantee a connecting path or enough annotations.
    const e1 = eras[0]?.name, e2 = eras[1]?.name, eLast = eras[eras.length - 1]?.name;
    const m1 = materials[0]?.name, m2 = materials[1]?.name;
    const mo1 = motifs.find(m => !/连续|边缘/.test(m.name))?.name || motifs[0]?.name;
    const mo2 = motifs.find(m => m.name !== mo1 && !/连续|边缘/.test(m.name))?.name || motifs[1]?.name;

    const suggestions = [];
    if (e1 && e2) {
      suggestions.push({
        type: 'path',
        label: `${e1} → ${e2} 关联路径检索`,
        source: e1, target: e2,
        question: `请检索「${e1}」与「${e2}」之间的多跳纹样或材质关联路径，说明本体泛化前后的差异与标注缺口，并判断这些证据是否足以支持传承或迁移。`,
      });
    }
    if (e2 && eLast && e2 !== eLast) {
      suggestions.push({
        type: 'compare',
        label: `对比 ${e2} vs ${eLast}`,
        kind: 'era', entityA: e2, entityB: eLast,
        question: `对比「${e2}」与「${eLast}」的纹样与材质记录：当前共有、差集与标注覆盖率分别是多少？不要把差集解释为历史独有。`,
      });
    }
    if (m1 && m2) {
      suggestions.push({
        type: 'compare',
        label: `对比 ${m1} vs ${m2}`,
        kind: 'material', entityA: m1, entityB: m2,
        question: `对比材质「${m1}」与「${m2}」所承载的纹样有哪些交集与差异？是否存在跨材质迁移的纹样？`,
      });
    }
    if (mo1 && mo2) {
      suggestions.push({
        type: 'path',
        label: `${mo1} ↔ ${mo2} 语义关联`,
        source: mo1, target: mo2,
        question: `在当前知识图谱中，「${mo1}」和「${mo2}」之间有哪些语义关联路径？`,
      });
    }
    suggestions.push({
      type: 'predict',
      label: '缺失时代推理补全',
      targetPredicate: 'period',
      question: '当前图谱中有哪些未标注时代的器物可以通过关联规则和邻域证据高置信度推导出所属时代？给出规则和支撑证据。',
    });

    return {
      title: kg.title,
      format: kg.format,
      volumes: kg.volumes || [],
      counts: {
        artifacts: allArtifacts.length,
        triples: kg.triples.length,
        inferredTriples: inferredTriples.length,
        axioms: axioms.length,
        eras: eras.length,
        materials: materials.length,
        motifs: motifs.length,
      },
      eras,
      materials,
      motifs,
      axioms,
      suggestions,
    };
  }

  return {
    kg,
    axioms,
    inferredTriples,
    resolveNode,
    findPaths,
    compareEntities,
    runSparql,
    predictMissing,
    queryArtifacts,
    inspectEvidence,
    getCatalogSummary,
  };
}
