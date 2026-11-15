"""Run explicitly in isolated Modal tooling; never normal testpaths."""
import ast
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from deployment.ledger import seed_empty,initialized,export_spend
from deployment.gates import require_final

class DeploymentTests(unittest.TestCase):
 def test_ledger_preserves_unknown_and_imports_once(self):
  with tempfile.TemporaryDirectory() as d:
   db=Path(d)/'state.db'
   data={'version':1,'rows':[{'id':'known','reserved':.2,'charge':.1,'details':{}},{'id':'unknown','reserved':.3,'charge':None,'details':{}}],'totals':{'known_usd':.1,'unknown_reserved_usd':.3,'cap_usd':2.0}}
   self.assertFalse(initialized(db))
   def commit():
    # Closed SQLite permits exclusive lock at persistence boundary.
    c=sqlite3.connect(db,timeout=0);c.execute('BEGIN EXCLUSIVE');c.close()
   seed_empty(db,data,commit)
   self.assertTrue(initialized(db));self.assertEqual(export_spend(db),data)
   with self.assertRaises(ValueError):seed_empty(db,data,commit)
 def test_failed_commit_propagates(self):
  with tempfile.TemporaryDirectory() as d:
   with self.assertRaises(OSError):seed_empty(Path(d)/'x.db',{'rows':[],'totals':{'known_usd':0,'unknown_reserved_usd':0,'cap_usd':2.0}},lambda:(_ for _ in ()).throw(OSError('commit failed')))
 def test_ready_gate(self):
  with tempfile.TemporaryDirectory() as d:
   with self.assertRaises(RuntimeError):require_final(d)
 def test_modal_constraints(self):
  import modal
  self.assertEqual(modal.__version__,'1.6.4')
  s=Path('modal_app.py').read_text();ast.parse(s)
  self.assertNotIn('@modal.concurrent',s);self.assertNotIn('retries=',s);self.assertNotIn('gpu=',s)
  for value in ('cpu=1','memory=2048','max_containers=1','timeout=180','version=2','include_source=False'):self.assertIn(value,s)
  self.assertNotIn('add_local_dir',s)
if __name__=='__main__':unittest.main()
