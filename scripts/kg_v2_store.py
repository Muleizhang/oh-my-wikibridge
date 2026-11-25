#!/usr/bin/env python3
"""Persist typed assertions without replacing v1 or deleting review history."""
import argparse
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

from kg_v2.schema import schema
from kg_v2.common import OUT, ident, load, save, source_path
from kg_v2.identity import build_identity_review
from kg_v2.images import install_previews
from kg_v2_validate import validate


def persist(graph, root):
    graph['identityReview'] = build_identity_review(graph)
    validate(graph)
    root.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(root / 'knowledge.sqlite3', timeout=30)
    conn.execute('PRAGMA foreign_keys=ON')
    conn.executescript(schema())
    source = source_path()
    with source.open('rb') as f: digest = hashlib.file_digest(f, 'sha256').hexdigest()
    corpus, source_id = ident('corpus', 'typed-kg-v2'), ident('source', digest, 'typed-kg-v2')
    stable = [graph[k] for k in ['version', 'selection', 'records', 'entities', 'assertions', 'events', 'identityProposals']]
    run = ident('run', stable)
    graph['runId'] = run
    destination = root / 'sources' / (source_id + '.pdf'); destination.parent.mkdir(exist_ok=True)
    if not destination.exists():
        temporary = destination.with_suffix('.pdf.tmp'); shutil.copyfile(source, temporary); temporary.replace(destination)
    install_previews(graph, root)
    backup = root / 'backups/before-typed-kg-v2.sqlite3'
    if not backup.exists():
        backup.parent.mkdir(exist_ok=True)
        with sqlite3.connect(backup) as copy: conn.backup(copy)
    with conn:
        conn.execute('INSERT INTO corpora(id,name,description) VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET description=excluded.description',
            (corpus, '中国纹样 · 条目与陈述 v2', f"{len(graph['selection'])}页语料。属性、事件和实体分离；候选尚未独立验收。"))
        conn.execute('INSERT OR IGNORE INTO sources(id,corpus_id,name,extension,bytes,hash,status) VALUES (?,?,?,?,?,?,?)',
            (source_id, corpus, source.name, 'pdf', source.stat().st_size, digest, 'draft'))
        conn.execute('INSERT INTO kg_runs(id,source_id,state,graph_json) VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET graph_json=excluded.graph_json',
            (run, source_id, 'complete', json.dumps(graph, ensure_ascii=False)))
        source_pages = conn.execute("""SELECT s.id, MAX(json_array_length(r.graph_json,'$.selection'))
            FROM sources s JOIN kg_runs r ON r.source_id=s.id
            WHERE s.corpus_id=? AND r.state='complete' GROUP BY s.id""", (corpus,)).fetchall()
        conn.execute('UPDATE corpora SET description=? WHERE id=?',
            (f"{len(source_pages)}册、{sum(row[1] for row in source_pages)}页语料。属性、事件和实体分离；候选尚未独立验收。", corpus))
        for table in ['kg_assertions', 'kg_events', 'kg_source_mentions', 'kg_records']:
            conn.execute(f'DELETE FROM {table} WHERE run_id=?', (run,))
        conn.execute('DELETE FROM kg_entities WHERE run_id=?', (run,))
        for doc in graph['documents']:
            if doc['engine'] != 'ppstructure': continue
            conn.execute('INSERT OR IGNORE INTO units(source_id,kind,ordinal,locator,method) VALUES (?,?,?,?,?)',
                (source_id, 'page', doc['page'], f"PDF 第{doc['page']}页 · PP-Structure", 'ocr'))
            unit = conn.execute('SELECT id FROM units WHERE source_id=? AND ordinal=?', (source_id, doc['page'])).fetchone()[0]
            chunk = f"{source_id}:{doc['page']}:1"
            conn.execute('INSERT INTO chunks(id,unit_id,text) VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET text=excluded.text', (chunk, unit, doc['text']))
            seq = conn.execute('SELECT seq FROM chunks WHERE id=?', (chunk,)).fetchone()[0]
            conn.execute('DELETE FROM chunks_fts WHERE rowid=?', (seq,))
            text = ''.join(doc['text'].split())
            conn.execute('INSERT INTO chunks_fts(rowid,tokens) VALUES (?,?)', (seq, ' '.join(list(text)+[text[i:i+2] for i in range(len(text)-1)])))
        for e in graph['entities']:
            conn.execute('INSERT INTO kg_entities VALUES (?,?,?,?,?)', (run, e['id'], e['label'], e['kind'], json.dumps(e, ensure_ascii=False)))
        for r in graph['records']:
            conn.execute('INSERT INTO kg_records VALUES (?,?,?,?,?,?)', (run,r['id'],r['page'],r['item'],r['label'],json.dumps(r,ensure_ascii=False)))
        for s in graph['assertions']:
            conn.execute('INSERT INTO kg_assertions VALUES (?,?,?,?,?,?,?)', (run,s['id'],s['subject'],s['predicate'],s['object']['kind'],json.dumps(s['object'],ensure_ascii=False),json.dumps(s,ensure_ascii=False)))
        for e in graph['events']:
            conn.execute('INSERT INTO kg_events VALUES (?,?,?,?)', (run,e['id'],e['kind'],json.dumps(e,ensure_ascii=False)))
        for m in graph['mentions']:
            conn.execute('INSERT INTO kg_source_mentions VALUES (?,?,?,?)', (run,m['id'],m['entityId'],json.dumps(m,ensure_ascii=False)))
        if conn.execute('PRAGMA foreign_key_check').fetchall(): raise ValueError('Foreign key violation')
    saved = json.loads(conn.execute('SELECT graph_json FROM kg_runs WHERE id=?',(run,)).fetchone()[0])
    if saved != graph: raise ValueError('Database payload mismatch')
    report = {'runId': run, 'database': str(root/'knowledge.sqlite3'), 'state': 'candidate',
        'records': len(graph['records']), 'assertions': len(graph['assertions']),
        'reviewsPreserved': conn.execute('SELECT COUNT(*) FROM kg_reviews WHERE run_id=?',(run,)).fetchone()[0],
        'foreignKeyViolations': 0}
    conn.close()
    return report


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--database-root',type=Path,default=Path.home()/'.local/share/cn.wikibridge.desktop')
    args=parser.parse_args();graph=load(OUT/'graph.json');report=persist(graph,args.database_root)
    save(OUT/'graph.json',graph);save(OUT/'database-import.json',report);print(report)
