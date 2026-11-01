import argparse
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import sorter
from worker_client import AnalysisWorker
from sorter_gui import LogBuffer

FAKE_WORKER='''import sys,json,time,os
for line in sys.stdin:
    r=json.loads(line)
    print(json.dumps(dict(event='hashed',sha256='verified')),flush=True)
    if r['source']=='sleep': time.sleep(30)
    if r['source']=='crash': os._exit(7)
    if r['source']=='flood':
        for i in range(1000): os.write(2,b'decoder error '*1000+b'\\n')
    if r['source']=='bad':
        print(json.dumps(dict(event='error',reason='Invalid video',sha256='verified')),flush=True)
    else:
        print(json.dumps(dict(event='result',result=dict(category='2'),sha256='verified')),flush=True)
'''

class WorkerIsolation(unittest.TestCase):
    def setUp(self):
        self.worker=AnalysisWorker(timeout=2,command=[sys.executable,'-u','-c',FAKE_WORKER])
    def tearDown(self): self.worker.close()
    def analyze(self,name,**kwargs): return self.worker.analyze(name,Path('.tmp'),[],False,**kwargs)
    def test_timeout_then_next_clip(self):
        self.worker.timeout=.4; started=time.monotonic()
        result,sha=self.analyze('sleep')
        self.assertEqual(result['method'],'analysis timeout'); self.assertEqual(sha,'verified')
        self.assertLess(time.monotonic()-started,3)
        self.worker.timeout=2
        self.assertEqual(self.analyze('ok')[0]['category'],'2')
    def test_native_crash_then_next_clip(self):
        self.assertEqual(self.analyze('crash')[0]['method'],'worker error')
        self.assertEqual(self.analyze('ok')[0]['category'],'2')
    def test_decoder_error_then_next_clip(self):
        self.assertEqual(self.analyze('bad')[0]['method'],'decode/OCR error')
        self.assertEqual(self.analyze('ok')[0]['category'],'2')
    def test_stderr_flood_does_not_reach_ui(self):
        self.assertEqual(self.analyze('flood')[0]['category'],'2')
    def test_cancel_kills_worker(self):
        with self.assertRaises(KeyboardInterrupt): self.analyze('sleep',cancelled=lambda:True)
        self.assertIsNone(self.worker.process)

class BatchScaling(unittest.TestCase):
    def setUp(self):
        Path('.tmp').mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=Path('.tmp').resolve())
        self.root=Path(self.temp.name);self.state=sorter.State(self.root/'work')
    def tearDown(self):self.state.close();self.temp.cleanup()
    def test_11000_result_export_streams(self):
        r=json.dumps(dict(category='Needs review',timestamps=[1.2],reason='x'*1000))
        self.state.db.executemany('INSERT INTO clips VALUES (?,?,?,?,1)',[(f'clip{i:05}.mp4','sig','hash',r) for i in range(11000)])
        self.state.db.commit()
        with patch.object(self.state,'rows',side_effect=AssertionError('Must stream large export')):
            sorter.export(self.state)
        with (self.state.work/'results.csv').open(encoding='utf-8-sig') as f:
            self.assertEqual(sum(1 for _ in f),11001)
        self.assertEqual(len(json.loads((self.state.work/'results.json').read_text())),11000)
    def test_preview_batches_exports_and_continues_after_bad_file(self):
        folder=self.root/'clips';folder.mkdir()
        for i in range(103): (folder/f'{i:03}.mp4').write_bytes(b'test')
        args=argparse.Namespace(input=folder,output=self.root/'Sorted',names=None,skip_feed=True,recursive=False,reanalyze=False,clip_timeout=1,retry_errors=False)
        calls=[]
        class Fake:
            def __init__(self,**kwargs):pass
            def close(self):pass
            def analyze(self,path,*a,**kw):
                category='Needs review' if path.name=='001.mp4' else '2'
                return dict(category=category,method='test',reason='fixture',timestamps=[]),sorter.digest(path)
        original=sorter.export
        def export(state,include_json=True):calls.append(include_json);original(state,include_json)
        with patch('worker_client.AnalysisWorker',Fake),patch.object(sorter,'export',export),patch('builtins.print'):
            sorter.preview(args,self.state)
        self.assertEqual(calls,[False,False,True])
        self.assertEqual(len(self.state.rows()),103)
        self.assertTrue(json.loads((self.state.work/'plan.json').read_text())['complete'])
    def test_unhashed_review_not_moved(self):
        source=self.root/'bad.mp4';source.write_bytes(b'preserve')
        sorter.atomic_json(self.state.work/'plan.json',dict(output=str(self.root/'Sorted'),complete=True))
        self.state.db.execute('INSERT INTO clips VALUES (?,?,?,?,1)',(str(source),'sig',None,json.dumps(dict(category='Needs review'))));self.state.db.commit()
        with patch('builtins.print'):sorter.apply(argparse.Namespace(mode='move'),self.state)
        self.assertTrue(source.exists());self.assertEqual(self.state.db.execute('SELECT count(*) FROM operations').fetchone()[0],0)
    def test_interrupted_preview_resumes_committed_clips(self):
        folder=self.root/'clips';folder.mkdir()
        for i in range(3):(folder/f'{i}.mp4').write_bytes(b'test')
        args=argparse.Namespace(input=folder,output=self.root/'Sorted',names=None,skip_feed=True,recursive=False,reanalyze=False,clip_timeout=1,retry_errors=False)
        calls=[];interrupted=[False];closed=[]
        class Fake:
            def __init__(self,**kwargs):pass
            def close(self):closed.append(True)
            def analyze(self,path,*a,**kw):
                calls.append(path.name)
                if path.name=='1.mp4' and not interrupted[0]:interrupted[0]=True;raise KeyboardInterrupt
                return dict(category='2',method='test',reason='fixture',timestamps=[]),sorter.digest(path)
        with patch('worker_client.AnalysisWorker',Fake),patch('builtins.print'):
            with self.assertRaises(KeyboardInterrupt):sorter.preview(args,self.state)
            self.assertFalse(json.loads((self.state.work/'plan.json').read_text())['complete'])
            self.assertEqual(len(self.state.rows()),1)
            sorter.preview(args,self.state)
        self.assertEqual(calls,['0.mp4','1.mp4','1.mp4','2.mp4']);self.assertEqual(len(closed),2)
        self.assertEqual(len(self.state.rows()),3)
    def test_retry_errors_keeps_successful_cache(self):
        folder=self.root/'clips';folder.mkdir()
        for i in range(3):(folder/f'{i}.mp4').write_bytes(b'test')
        args=argparse.Namespace(input=folder,output=self.root/'Sorted',names=None,skip_feed=True,recursive=False,reanalyze=False,clip_timeout=1,retry_errors=False)
        calls=[]
        class Fake:
            def __init__(self,**kwargs):pass
            def close(self):pass
            def analyze(self,path,*a,**kw):
                calls.append(path.name)
                method='decode/OCR error' if path.name=='1.mp4' else 'combat report'
                return dict(category='Needs review' if path.name=='1.mp4' else '2',method=method,reason='fixture',timestamps=[]),sorter.digest(path)
        with patch('worker_client.AnalysisWorker',Fake),patch('builtins.print'):
            sorter.preview(args,self.state);args.retry_errors=True;sorter.preview(args,self.state)
        self.assertEqual(calls,['0.mp4','1.mp4','2.mp4','1.mp4'])
    def test_log_flood_has_bounded_backlog(self):
        buffer=LogBuffer()
        for i in range(100000):buffer.put(f'{i} decoder error\n')
        self.assertEqual(buffer.queue.qsize(),1000);self.assertEqual(buffer.dropped,99000)
        started=time.monotonic();batch=buffer.drain()
        self.assertLess(time.monotonic()-started,.1);self.assertLessEqual(len(batch.splitlines()),100)

if __name__=='__main__':unittest.main()
