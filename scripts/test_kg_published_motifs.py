"""Exercise the SQL actually used by Tauri against the complete production schema."""
import json
import sqlite3
import unittest

from kg_v2.common import ROOT
from kg_v2.schema import schema


class PublishedMotifsTest(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.executescript(schema())
        c = self.db.execute
        c("INSERT INTO corpora(id,name,description) VALUES('vol','第一册','')")
        c("INSERT INTO sources(id,corpus_id,name,extension,bytes,hash,status) VALUES('s','vol','book','pdf',1,'digest','draft')")
        members = [{'kind':'motif','name':'花卉纹','id':'concept','memberIds':['m4','m7'],'proposalIds':['pair']}]
        graph = json.dumps({'version':'typed-kg-v2','identityReview':{'concepts':members}})
        c("INSERT INTO kg_runs(id,source_id,state,graph_json) VALUES('r','s','complete',?)",(graph,))
        for page,item in [(4,4),(7,2)]:
            key,subject,target = f'claim{page}', f'pot{page}', f'm{page}'
            c("INSERT INTO units(id,source_id,kind,ordinal,locator,method) VALUES(?,'s','page',?,'PDF','ocr')",(page,page))
            c("INSERT INTO chunks(id,unit_id,text) VALUES(?,?,'花卉纹彩陶盆')",(f'chunk{page}',page))
            c("INSERT INTO kg_entities VALUES('r',?,'花卉纹彩陶盆','artifact','{}')",(subject,))
            c("INSERT INTO kg_entities VALUES('r',?,'花卉纹','motif','{}')",(target,))
            c("INSERT INTO kg_records VALUES('r',?,?,?,'花卉纹彩陶盆','{}')",(subject,page,item))
            obj = json.dumps({'kind':'entity','id':target})
            data = json.dumps({'recordId':subject,'evidence':[{'page':page,'text':'花卉纹彩陶盆'}], 'qualifiers':[]})
            c("INSERT INTO kg_assertions VALUES('r',?,?,'decorated_with','entity',?,?)",(key,subject,obj,data))
        self.query = (ROOT/'src-tauri/src/published_motifs.sql').read_text()

    def rows(self, *ids):
        return [json.loads(row[0]) for row in self.db.execute(self.query,(json.dumps(ids),))]

    def decide(self, kind, key, decision):
        self.db.execute("INSERT INTO kg_reviews(id,run_id,target_kind,target_id,decision,reviewer,note) VALUES(hex(randomblob(12)),'r',?,?,?,'test','test')",(kind,key,decision))

    def test_publication_scope_revoke_and_rerun(self):
        self.decide('assertion','claim4','accept')
        self.assertEqual(self.rows('vol'),[])
        self.db.execute("UPDATE sources SET status='published'")
        self.assertEqual(self.rows('elsewhere'),[])
        self.assertEqual(len(self.rows('vol')),1)
        self.decide('assertion','claim7','accept')
        a,b = self.rows('vol')
        self.assertNotEqual(a['artifactId'],b['artifactId'])
        self.assertEqual(a['objectId'],b['objectId'])
        self.assertEqual((a['evidenceId'],b['evidenceId']),('chunk4','chunk7'))
        self.decide('identity','pair','reject')
        a,b = self.rows('vol')
        self.assertNotEqual(a['objectId'],b['objectId'])
        self.decide('assertion','claim4','revoke')
        self.assertEqual([r['page'] for r in self.rows('vol')],[7])
        self.db.execute("INSERT INTO kg_runs(id,source_id,state,graph_json) SELECT 'r2',source_id,state,graph_json FROM kg_runs WHERE id='r'")
        self.assertEqual(self.rows('vol'),[])

    def test_manual_alias_merge_and_reversal(self):
        self.db.execute("UPDATE sources SET status='published'")
        self.db.execute("UPDATE kg_entities SET label='花卉纹饰' WHERE id='m7'")
        graph = {'version':'typed-kg-v2','identityProposals':[{'id':'aliases','left':'m4','right':'m7'}]}
        self.db.execute("UPDATE kg_runs SET graph_json=?",(json.dumps(graph),))
        for key in ('claim4','claim7'):
            self.decide('assertion',key,'accept')
        self.assertEqual(len({r['objectId'] for r in self.rows('vol')}),2)
        self.decide('identity','aliases','accept')
        self.assertEqual(len({r['objectId'] for r in self.rows('vol')}),1)
        self.decide('identity','aliases','revoke')
        self.assertEqual(len({r['objectId'] for r in self.rows('vol')}),2)
