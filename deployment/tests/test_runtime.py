"""No network/provider calls. Requires isolated Modal plus exact runtime deps."""
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
import struct
from unittest.mock import patch

class RuntimeTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.temp=tempfile.TemporaryDirectory();cls.db=Path(cls.temp.name)/'state.db'
  os.environ.update(STOA_DB=str(cls.db),STOA_DOCUMENT_ROOT=str(Path(cls.temp.name)/'documents'),STOA_ENABLE_PAID_API='0',STOA_API_BALANCE_VERIFIED='0')
  from deployment.runtime import create_app
  from fastapi.testclient import TestClient
  cls.commits=0
  def persist():
   c=sqlite3.connect(cls.db,timeout=0);c.execute('BEGIN EXCLUSIVE');c.close();cls.commits+=1
  cls.client=TestClient(create_app(persist))
 @classmethod
 def tearDownClass(cls):cls.client.close();cls.temp.cleanup()
 def test_public_native_routes_and_persistence(self):
  from app import provider
  self.assertFalse(provider.access()['paid_enabled'])
  for path in ('/development/evidence','/docs','/openapi.json','/debug'):
   self.assertEqual(self.client.get(path).status_code,404)
  self.assertEqual(self.client.get('/health').status_code,200)
  self.assertEqual(self.client.get('/').status_code,200)
  source=Path('data/raw/junction-dataset-preview/data/swiss_dwellings')
  with patch.object(provider,'invoke',side_effect=AssertionError('Forbidden model call')):
   for name,question,expected in [('site1000_bldg2082_floor9385.pdf','What is the combined area of room 2.01 and room 2.02?',27.66),('site2293_bldg3380_floor15055.pdf','What is the area of room 4.23?',4.322160437)]:
    doc=self.client.post('/documents',files={'file':(name,(source/name).read_bytes(),'application/pdf')}).json()
    req={'document_ids':[doc['document_id']],'page_index':0,'question':question,'runtime_model':'gpt-6.1-sol','use_cache':True}
    r=self.client.post('/query',json=req);self.assertEqual(r.status_code,200);a=r.json()
    self.assertEqual(a['status'],'answered');self.assertAlmostEqual(a['value'],expected,places=6);self.assertEqual(a['metadata']['attempts'],0)
    self.assertEqual(self.client.get('/runs/'+a['run_id']).status_code,200)
    cache=self.client.post('/query',json=req).json();self.assertTrue(cache['metadata']['cache_hit']);self.assertEqual(cache['metadata']['incremental_cost_usd'],0)
    image=self.client.get(doc['pages'][0]['image_url']);self.assertEqual(image.status_code,200)
    self.assertEqual(struct.unpack('>II',image.content[16:24]),(doc['pages'][0]['width'],doc['pages'][0]['height']))
    req['question']='What is the combined area of room 4.23 and room 99.99?'
    missing=self.client.post('/query',json=req).json();self.assertIn(missing['status'],('needs_review','unsupported'));self.assertIn('99.99',str(missing));self.assertEqual(missing['metadata']['attempts'],0)
  self.assertGreater(self.commits,5)
