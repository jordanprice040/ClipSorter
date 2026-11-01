"""Contain decoder hangs/crashes without blocking the batch or Tk UI."""
import json
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

def review(method,reason):
    return dict(category='Needs review',kills=None,duration=None,method=method,reason=reason,timestamps=[])

class AnalysisWorker:
    def __init__(self,timeout=120,command=None):
        self.timeout=timeout
        self.command=command or [sys.executable,'-u',str(Path(__file__).with_name('analysis_worker.py'))]
        self.process=None
    def start(self):
        self.events=queue.Queue(maxsize=16)
        self.process=subprocess.Popen(self.command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,text=True,encoding='utf8',errors='replace',
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0)
        process=self.process; events=self.events
        def send(message):
            try: events.put_nowait(message)
            except queue.Full:
                try: events.get_nowait()
                except queue.Empty: pass
                try: events.put_nowait({'event':'protocol_error'})
                except queue.Full: pass
        def collect():
            try:
                for line in process.stdout:
                    try: message=json.loads(line)
                    except ValueError: message={'event':'protocol_error'}
                    send(message)
            except (OSError,ValueError): pass
            finally: send({'event':'exit'})
        threading.Thread(target=collect,daemon=True).start()
    def close(self):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
                try: self.process.wait(timeout=3)
                except subprocess.TimeoutExpired: self.process.kill(); self.process.wait(timeout=3)
            self.process.stdin.close(); self.process.stdout.close(); self.process=None
    def analyze(self,path,evidence,names,feed,progress=print,cancelled=lambda:False):
        started=time.monotonic(); sha=None; phase='starting decoder'
        if self.process is None or self.process.poll() is not None:
            self.close(); self.start()
        try:
            self.process.stdin.write(json.dumps(dict(source=str(path),evidence=str(evidence),names=names,feed=feed,timeout=self.timeout))+'\n')
            self.process.stdin.flush()
            next_progress=started+10
            while True:
                if cancelled(): raise KeyboardInterrupt
                remaining=self.timeout-(time.monotonic()-started)
                if remaining<=0:
                    self.close()
                    return review('analysis timeout',f'Exceeded {self.timeout:g}s while {phase}; skipped safely. Retry with a longer clip timeout if needed.'),sha
                try: event=self.events.get(timeout=min(.2,remaining))
                except queue.Empty:
                    if time.monotonic()>=next_progress:
                        progress(f'  Still {phase} ({time.monotonic()-started:.0f}s; limit {self.timeout:g}s)...')
                        next_progress=time.monotonic()+10
                    continue
                kind=event.get('event')
                if kind=='phase': phase=event['phase']
                elif kind=='hashed': sha=event['sha256']
                elif kind=='result': return event['result'],event['sha256']
                elif kind=='error': return review('decode/OCR error',event['reason']),event.get('sha256')
                else:
                    self.close()
                    return review('worker error','Decoder/OCR worker exited unexpectedly; skipped safely.'),sha
        except (BrokenPipeError,OSError) as e:
            self.close()
            return review('worker error',f'Worker connection failed: {e}'),sha
        except BaseException:
            self.close(); raise
