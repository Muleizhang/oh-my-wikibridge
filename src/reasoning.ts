export type Evidence = { page: number; engine: string; text: string; bbox?: number[] | null };
export type RecordEntry = { id: string; page: number; item: number; label: string; text: string; engine?: string; bbox?: number[] | null };
export type Entity = { id: string; label: string; kind: string; recordId?: string };
export type Fact = { id: string; recordId: string | null; subject: string | null; predicate: string; label: string;
  object: { kind: string; id?: string; raw?: string; value?: string; normalized?: { lower: string; upper: string; unit: string } };
  evidence: Evidence[]; reviewStatus?: string; issues?: string[] };
export type EventEntry = { id: string; label: string; participants: { role: string; entityId: string }[] };
export type Graph = { records: RecordEntry[]; entities: Entity[]; assertions: Fact[]; events: EventEntry[];
  documents: { page: number; engine: string; imageSize: number[]; source?: string }[];
  identityReview?: { concepts: { id: string; kind: string; name: string; memberIds: string[] }[] };
  sourceContext?: { title: string; printedPage?: number; notes?: string; captionSource?: string; figures?: Record<number, [number, number, number, number]> } };
export type Filter = { name?: string; period?: string; material?: string; motif?: string; place?: string; minHeight?: number };
export type Rule = 'shared' | 'filter' | 'fact';
export type Statement = { id: string; subject: string; label: string; value: string; evidence: Evidence[]; item?: number };
export type PathMatch = { left: string; motif: string; right: string; facts: Statement[]; records: [RecordEntry, RecordEntry] };
export type FilterMatch = { record: RecordEntry; facts: Statement[] };
export type Citation = Statement & { ref: string };
export type Trace = { tool: string; detail: string; count: number; refs: string[] };
export type ChatEntry = { role: 'user' | 'assistant'; content: string };
export type AgentAnswer = { model: string; answer: string; trace: Trace[]; citations: Citation[]; paths: PathMatch[] };

const normalize = (text: string) => text.normalize('NFKC').replace(/\s+/g, '').toLowerCase();
const matches = (value: string, query: string) => normalize(value).includes(normalize(query));
const unusableIssues = ['unresolved_subject', 'unresolved_object', 'conflicting_values', 'quantity_dimension_mismatch',
  'quantity_owner_not_artifact', 'field_value_type_conflict', 'relation_subject_type', 'relation_object_type'];

export function makeReasoner(graph: Graph) {
  const entities = new Map(graph.entities.map(entity => [entity.id, entity]));
  const events = new Map(graph.events.map(event => [event.id, event]));
  const records = new Map(graph.records.map(record => [record.id, record]));
  const artifactOwners = new Map(graph.entities.filter(entity => entity.kind === 'artifact' && entity.recordId)
    .map(entity => [entity.id, entity.recordId!]));
  const factsByRecord = new Map<string, Fact[]>();
  for (const fact of graph.assertions) {
    const owner = fact.subject && artifactOwners.get(fact.subject);
    if (!owner || !records.has(owner) || (fact.recordId && fact.recordId !== owner) || !fact.evidence?.length
        || fact.reviewStatus === 'rejected' || fact.issues?.some(issue => unusableIssues.includes(issue))) continue;
    const entries = factsByRecord.get(owner) ?? [];
    entries.push(fact);
    factsByRecord.set(owner, entries);
  }
  const motifConcepts = new Map((graph.identityReview?.concepts ?? []).filter(concept => concept.kind === 'motif')
    .flatMap(concept => concept.memberIds.map(id => [id, concept] as const)));

  function value(fact: Fact) {
    const object = fact.object;
    if (object.kind === 'entity') return entities.get(object.id!)?.label ?? '';
    if (object.kind === 'event') return events.get(object.id!)?.participants
      .filter(participant => participant.role !== 'object').map(participant => entities.get(participant.entityId)?.label ?? '').filter(Boolean).join('、') ?? '';
    return object.raw ?? object.value ?? '';
  }

  function statement(fact: Fact, record: RecordEntry): Statement {
    return { id: fact.id, subject: record.label, label: fact.label, value: value(fact), evidence: fact.evidence, item: record.item };
  }

  function fields(predicate: string) {
    return [...new Set([...factsByRecord.values()].flatMap(facts => facts.filter(fact => fact.predicate === predicate)
      .map(value)).filter(Boolean))].sort((a, b) => a.localeCompare(b, 'zh-CN'));
  }

  function find(filters: Filter): FilterMatch[] {
    const conditions: [string, string | undefined][] = [['period', filters.period], ['made_of', filters.material], ['decorated_with', filters.motif]];
    return graph.records.flatMap(record => {
      if (filters.name && !matches(record.label, filters.name)) return [];
      const facts = factsByRecord.get(record.id) ?? [];
      const groups = conditions.filter(([, term]) => Boolean(term)).map(([predicate, term]) => facts.filter(fact => fact.predicate === predicate && matches(value(fact), term!)));
      if (filters.place) groups.push(facts.filter(fact => ['出土', '出土地点'].includes(fact.label) && matches(value(fact), filters.place!)));
      if (filters.minHeight !== undefined) groups.push(facts.filter(fact => {
        const quantity = fact.object.normalized;
        return ['height', 'overall_height'].includes(fact.predicate) && quantity?.unit === 'cm' && Number(quantity.lower) > filters.minHeight!;
      }));
      if (groups.some(group => !group.length)) return [];
      const chosen = groups.length ? [...new Set(groups.flat())] : facts;
      return [{ record, facts: chosen.map(fact => statement(fact, record)) }];
    });
  }

  function shared(artifact: string, motif = ''): PathMatch[] {
    const selected = records.get(artifact) ?? graph.records.find(record => normalize(record.label) === normalize(artifact));
    if (!selected) return [];
    const selectedFacts = factsByRecord.get(selected.id) ?? [];
    const results: PathMatch[] = [];
    const seen = new Set<string>();
    for (const first of selectedFacts) {
      if (first.predicate !== 'decorated_with' || first.object.kind !== 'entity' || !first.object.id) continue;
      const concept = motifConcepts.get(first.object.id);
      const motifId = concept?.id ?? first.object.id;
      const name = concept?.name ?? value(first);
      if (!name || !matches(name, motif)) continue;
      for (const [id, facts] of factsByRecord) {
        const other = records.get(id)!;
        const pairKey = `${id}:${motifId}`;
        if (other.id === selected.id || seen.has(pairKey)) continue;
        const second = facts.find(fact => fact.predicate === 'decorated_with' && fact.object.kind === 'entity' && fact.object.id
          && (motifConcepts.get(fact.object.id)?.id ?? fact.object.id) === motifId);
        if (!second) continue;
        seen.add(pairKey);
        results.push({ left: selected.label, motif: name, right: other.label, records: [selected, other],
          facts: [statement(first, selected), statement(second, other)] });
      }
    }
    return results;
  }

  return { find, shared, fields };
}
