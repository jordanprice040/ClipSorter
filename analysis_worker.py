"""Persistent, disposable OCR worker. Standard output is a JSON-lines protocol."""
import json
import sys
import threading
import os
from pathlib import Path

def emit(**message):
    print(json.dumps(message),flush=True)

def main():
    # Imports and model construction are inside the parent's per-clip deadline.
    from prototype import Reader
    from sorter import digest
    reader=None; current_names=None
    for line in sys.stdin:
        request=json.loads(line); path=Path(request['source']); sha=None
        watchdog=threading.Timer(request.get('timeout',120)+5,lambda:os._exit(124)); watchdog.daemon=True; watchdog.start()
        try:
            emit(event='phase',phase='hashing')
            before=path.stat(); sha=digest(path)
            emit(event='hashed',sha256=sha)
            emit(event='phase',phase='analyzing')
            if reader is None or current_names!=request['names']:
                reader=Reader(request['names']); current_names=request['names']
            result=reader.analyze(path,Path(request['evidence']),feed_fallback=request['feed'])
            emit(event='phase',phase='verifying')
            after=path.stat()
            if (after.st_size,after.st_mtime_ns)!=(before.st_size,before.st_mtime_ns) or digest(path)!=sha:
                sha=None
                raise RuntimeError('Source changed during analysis; run preview again before applying')
            emit(event='result',result=result,sha256=sha)
        except Exception as e:
            # A partially decoded clip must remain reviewable, never guessed as zero.
            if sha is not None:
                try:
                    after=path.stat()
                    if (after.st_size,after.st_mtime_ns)!=(before.st_size,before.st_mtime_ns): sha=None
                except OSError: sha=None
            emit(event='error',reason=f'{type(e).__name__}: {e}',sha256=sha)
        finally: watchdog.cancel()

if __name__=='__main__': main()
