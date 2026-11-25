-- One public projection shared by the atlas and question answering.
WITH RECURSIVE ranked_runs AS (
    SELECT r.id, r.graph_json, r.source_id, s.name, s.bytes,
           row_number() OVER (PARTITION BY r.source_id ORDER BY r.created_at DESC, r.rowid DESC) AS rank
    FROM sources s JOIN kg_runs r ON r.source_id = s.id
    WHERE s.status = 'published' AND s.corpus_id IN (SELECT value FROM json_each(?1))
      AND r.state = 'complete' AND json_extract(r.graph_json,'$.version') = 'typed-kg-v2'
), current_run AS (
    SELECT * FROM ranked_runs WHERE rank = 1
), decisions AS (
    SELECT v.*, row_number() OVER (
        PARTITION BY v.run_id, v.target_kind, v.target_id ORDER BY v.rowid DESC
    ) AS rank FROM kg_reviews v JOIN current_run r ON r.id = v.run_id
), members AS (
    SELECT r.id AS run_id, m.value AS entity_id, g.value ->> 'id' AS concept_id,
           g.value ->> 'name' AS concept_name
    FROM current_run r, json_each(r.graph_json,'$.identityReview.concepts') g,
         json_each(g.value,'$.memberIds') m
    WHERE g.value ->> 'kind' = 'motif' AND NOT EXISTS (
        SELECT 1 FROM json_each(g.value,'$.proposalIds') p JOIN decisions d
          ON d.run_id = r.id AND d.target_kind = 'identity' AND d.target_id = p.value
         AND d.rank = 1 AND d.decision = 'reject'
    )
), motif_keys AS (
    SELECT e.run_id, e.id, coalesce(m.concept_id,e.id) AS key, coalesce(m.concept_name,e.label) AS name
    FROM kg_entities e JOIN current_run r ON r.id=e.run_id
    LEFT JOIN members m ON m.run_id=e.run_id AND m.entity_id=e.id
    WHERE e.kind='motif'
), accepted_pairs AS (
    SELECT r.id AS run_id, l.key AS a, h.key AS b
    FROM current_run r, json_each(r.graph_json,'$.identityProposals') p
    JOIN decisions d ON d.run_id=r.id AND d.target_kind='identity' AND d.target_id=p.value->>'id'
                    AND d.rank=1 AND d.decision='accept'
    JOIN motif_keys l ON l.run_id=r.id AND l.id=p.value->>'left'
    JOIN motif_keys h ON h.run_id=r.id AND h.id=p.value->>'right'
    WHERE l.key<>h.key
), adjacent(run_id,a,b) AS (
    SELECT run_id,a,b FROM accepted_pairs UNION SELECT run_id,b,a FROM accepted_pairs
), reachable(run_id,start,key) AS (
    SELECT run_id,key,key FROM motif_keys
    UNION
    SELECT n.run_id,n.start,a.b FROM reachable n JOIN adjacent a ON a.run_id=n.run_id AND a.a=n.key
), roots AS (
    SELECT run_id,start,min(key) AS root FROM reachable GROUP BY run_id,start
), motif_names AS (
    SELECT k.run_id,k.id,roots.root,min(canonical.name) AS name FROM motif_keys k
    JOIN roots ON roots.run_id=k.run_id AND roots.start=k.key
    JOIN motif_keys canonical ON canonical.run_id=k.run_id AND canonical.key=roots.root
    GROUP BY k.run_id,k.id,roots.root
)
SELECT json_object(
    'id', r.id || '/' || a.id, 'sourceId', r.source_id, 'sourceName', r.name, 'bytes', r.bytes,
    'artifactId', r.id || '/' || owner.id, 'artifact', owner.label, 'item', rec.item,
    'predicate', a.predicate, 'object', coalesce(m.name, target.label),
    'objectId', r.id || '/' || coalesce(m.root, target.id),
    'evidenceId', c.id, 'page', u.ordinal, 'quote', a.data ->> '$.evidence[0].text',
    'qualifiers', json(coalesce(a.data -> '$.qualifiers', '[]')),
    'regions', json(coalesce(b.regions,'null'))
)
FROM current_run r JOIN kg_assertions a ON a.run_id = r.id
JOIN decisions d ON d.run_id = r.id AND d.target_kind = 'assertion' AND d.target_id = a.id
                AND d.rank = 1 AND d.decision = 'accept'
JOIN kg_entities owner ON owner.run_id = r.id AND owner.id = a.subject_id AND owner.kind = 'artifact'
JOIN kg_entities target ON target.run_id = r.id AND target.id = a.object_json ->> 'id'
JOIN kg_records rec ON rec.run_id = r.id AND rec.id = a.data ->> 'recordId'
JOIN units u ON u.source_id = r.source_id AND u.ordinal = a.data ->> '$.evidence[0].page'
JOIN chunks c ON c.unit_id = u.id AND c.seq = (SELECT min(ch.seq) FROM chunks ch WHERE ch.unit_id = u.id)
LEFT JOIN motif_names m ON a.predicate = 'decorated_with' AND m.run_id = r.id AND m.id = target.id
LEFT JOIN kg_plate_regions b ON b.run_id = r.id AND b.assertion_id = a.id
WHERE a.object_kind = 'entity' AND (
    (a.predicate = 'decorated_with' AND target.kind = 'motif') OR
    (a.predicate = 'period' AND target.kind = 'period') OR
    (a.predicate = 'made_of' AND target.kind = 'material') OR
    (a.predicate = 'uses_technique' AND target.kind = 'technique')
)
ORDER BY r.name, r.source_id, rec.page, rec.item, a.predicate, a.id
