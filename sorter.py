"""Local Windows clip sorter. Preview is read-only; apply is always explicit."""
import argparse
import csv
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

CATEGORIES = ['0','1','2','3','4','5+','Needs review','Deathmatch','Range','Outside of match','Short clips']
EXTENSIONS={'.mp4'}
ENGINE='report-v2-safe-1'

def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(4*1024*1024),b''): h.update(block)
    return h.hexdigest()

def atomic_json(path, obj):
    temp=path.with_suffix('.tmp')
    with temp.open('w',encoding='utf8') as f:
        json.dump(obj,f,indent=2); f.flush(); os.fsync(f.fileno())
    os.replace(temp,path)

def log_event(work,event,**fields):
    with (work/'undo.jsonl').open('a',encoding='utf8') as f:
        f.write(json.dumps(dict(time=datetime.now(timezone.utc).isoformat(),event=event,**fields))+'\n')
        f.flush(); os.fsync(f.fileno())

class State:
    def __init__(self,work):
        self.work=Path(work).resolve(); self.work.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(self.work/'state.sqlite3')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS clips (source TEXT PRIMARY KEY, signature TEXT, sha TEXT, result TEXT, active INTEGER DEFAULT 1)')
        self.db.execute('CREATE TABLE IF NOT EXISTS operations (id TEXT PRIMARY KEY, source TEXT, destination TEXT, stage TEXT, sha TEXT, mode TEXT, status TEXT)')
        columns={r[1] for r in self.db.execute('PRAGMA table_info(operations)')}
        for name in ['identity','restore_identity']:
            if name not in columns: self.db.execute(f"ALTER TABLE operations ADD COLUMN {name} TEXT DEFAULT ''")
        self.db.commit()
    def close(self): self.db.close()
    def rows(self):
        return [dict(source=s,sha256=h,**json.loads(r)) for s,h,r in self.db.execute('SELECT source,sha,result FROM clips WHERE active=1 ORDER BY source')]

class Lock:
    """Windows kernel lock releases automatically on crash; no stale lock deletion."""
    def __init__(self,work): self.work=work
    def __enter__(self):
        self.work.mkdir(parents=True,exist_ok=True)
        self.f=(self.work/'session.lock').open('a+b'); self.f.seek(0)
        if self.f.read(1)==b'': self.f.write(b'0'); self.f.flush()
        self.f.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.f.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.f.close(); raise RuntimeError('Another sorter is using this work folder')
        return self
    def __exit__(self,*exc): self.f.close()

def export(state):
    rows=state.rows()
    atomic_json(state.work/'results.json',rows)
    fields=['source','category','kills','duration','method','reason','timestamps','evidence','sha256']
    temp=state.work/'results.csv.tmp'
    with temp.open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore'); writer.writeheader()
        for row in rows:
            row=dict(row,timestamps=';'.join(f'{t:.3f}' for t in row.get('timestamps',[])))
            writer.writerow(row)
    os.replace(temp,state.work/'results.csv')

def preview(args,state):
    from prototype import Reader,NAMES,VERSION
    folder=args.input.resolve(); output=args.output.resolve()
    if not folder.is_dir(): raise ValueError(f'Clips folder not found: {folder}')
    if folder==output or folder.is_relative_to(output): raise ValueError('Output must not contain the input folder')
    if folder==state.work or folder.is_relative_to(state.work): raise ValueError('Work folder must not contain the input folder')
    names=args.names or NAMES
    config=dict(engine=ENGINE,prototype=VERSION,names=names,feed=not args.skip_feed)
    files=sorted(p.resolve() for p in (folder.rglob('*') if args.recursive else folder.iterdir())
                 if p.is_file() and p.suffix.lower() in EXTENSIONS and p.resolve().is_relative_to(folder) and not p.resolve().is_relative_to(output)
                 and not p.resolve().is_relative_to(state.work))
    if not files: raise ValueError('No supported video files found')
    atomic_json(state.work/'plan.json',dict(input=str(folder),output=str(output),recursive=args.recursive,config=config,complete=False))
    state.db.execute('UPDATE clips SET active=0')
    state.db.executemany('UPDATE clips SET active=1 WHERE source=?',[(str(p),) for p in files]); state.db.commit()
    reader=None
    for index,path in enumerate(files,1):
        stat=path.stat(); signature=json.dumps([stat.st_size,stat.st_mtime_ns,config],sort_keys=True)
        cached=state.db.execute('SELECT signature FROM clips WHERE source=?',(str(path),)).fetchone()
        if cached and cached[0]==signature and not args.reanalyze:
            print(f'[{index}/{len(files)}] Resume: {path.name}',flush=True); continue
        print(f'[{index}/{len(files)}] Analyzing: {path.name}',flush=True)
        if reader is None: reader=Reader(names)
        key=hashlib.sha256(str(path).encode()).hexdigest()[:20]
        evidence=state.work/'evidence'/key
        # Hash before/after decoding to prevent caching a file changed mid-analysis.
        sha=digest(path)
        try:
            result=reader.analyze(path,evidence,feed_fallback=not args.skip_feed)
        except (KeyboardInterrupt,SystemExit): raise
        except Exception as e:
            result=dict(category='Needs review',kills=None,duration=None,method='decode/OCR error',
                        reason=f'{type(e).__name__}: {e}',timestamps=[])
        if path.stat().st_mtime_ns!=stat.st_mtime_ns or digest(path)!=sha:
            raise RuntimeError(f'Source changed during analysis: {path}')
        result['evidence']=str(evidence)
        state.db.execute('INSERT OR REPLACE INTO clips VALUES (?,?,?,?,1)',(str(path),signature,sha,json.dumps(result)))
        state.db.commit(); export(state)
        print(f'  {result["category"]}: {result["reason"]}',flush=True)
    export(state)
    atomic_json(state.work/'plan.json',dict(input=str(folder),output=str(output),recursive=args.recursive,config=config,complete=True))
    print(f'Preview complete: {state.work / "results.csv"}. No clips copied or moved.')

def unique_path(folder,name):
    base=Path(name); candidate=folder/base.name; index=1
    while candidate.exists():
        candidate=folder/f'{base.stem} ({index}){base.suffix}'; index+=1
    return candidate

def publish(stage,destination):
    # os.rename on Windows fails if the target exists. No os.replace here.
    if os.name=='nt': os.rename(stage,destination)
    else:
        os.link(stage,destination); stage.unlink()

def verified_copy(source,stage,expected):
    h=hashlib.sha256()
    with source.open('rb') as src,stage.open('xb') as dst:
        for block in iter(lambda:src.read(4*1024*1024),b''):
            dst.write(block); h.update(block)
        dst.flush(); os.fsync(dst.fileno())
    if h.hexdigest()!=expected or digest(stage)!=expected:
        raise RuntimeError('Copy verification failed; source is preserved')
    shutil.copystat(source,stage)

def identity(path):
    stat=path.stat()
    return f'{stat.st_dev}:{stat.st_ino}'

def finish_operation(state,op):
    ident,src,dst,stage,sha,mode,status,*extra=op
    owned=extra[0] if extra else ''
    source,destination,staged=Path(src),Path(dst),Path(stage)
    if status=='prepared':
        if destination.exists():
            # Never claim an unrelated pre-existing destination, even identical bytes.
            # A published file has no stage; a collision leaves the stage in place.
            if staged.exists() or not owned:
                destination=unique_path(destination.parent,source.name)
                state.db.execute('UPDATE operations SET destination=? WHERE id=?',(str(destination),ident)); state.db.commit()
                log_event(state.work,'retarget',id=ident,destination=str(destination))
            elif identity(destination)!=owned or digest(destination)!=sha:
                raise RuntimeError(f'Destination changed; manual review needed: {destination}')
        if not destination.exists():
            if staged.exists() and digest(staged)!=sha:
                staged.unlink()  # Only our logged partial stage, never a source.
            if not staged.exists():
                if not source.is_file() or digest(source)!=sha: raise RuntimeError(f'Source missing or changed: {source}')
                verified_copy(source,staged,sha)
            owned=identity(staged)
            state.db.execute('UPDATE operations SET identity=? WHERE id=?',(owned,ident)); state.db.commit()
            while True:
                try: publish(staged,destination); break
                except FileExistsError:
                    destination=unique_path(destination.parent,source.name)
                    state.db.execute('UPDATE operations SET destination=? WHERE id=?',(str(destination),ident)); state.db.commit()
                    log_event(state.work,'retarget',id=ident,destination=str(destination))
        state.db.execute('UPDATE operations SET status=? WHERE id=?',('published',ident)); state.db.commit()
        log_event(state.work,'published',id=ident,destination=str(destination))
    if not destination.is_file() or (owned and identity(destination)!=owned) or digest(destination)!=sha: raise RuntimeError(f'Destination missing or changed: {destination}')
    if mode=='move' and source.exists():
        if digest(source)!=sha: raise RuntimeError(f'Source changed; refusing deletion: {source}')
        source.unlink()
    state.db.execute('UPDATE operations SET status=? WHERE id=?',('done',ident)); state.db.commit()
    log_event(state.work,'done',id=ident,source=src,destination=str(destination),sha256=sha,mode=mode)

def load_apply_plan(work, expected_input=None, expected_output=None, expected_recursive=None):
    path=Path(work)/'plan.json'
    if not path.is_file(): raise RuntimeError('No saved preview in this results folder. Click Preview / Resume first.')
    plan=json.loads(path.read_text(encoding='utf8'))
    if not plan.get('complete'): raise RuntimeError('Preview is incomplete. Resume preview before applying.')
    for key,expected in [('input',expected_input),('output',expected_output)]:
        if expected is not None and Path(plan.get(key,'')).resolve()!=Path(expected).resolve():
            raise RuntimeError(f'The saved preview uses a different {key} folder:\n{plan.get(key)}\nClick Preview / Resume to analyze your selected folders first.')
    if expected_recursive is not None and bool(plan.get('recursive',False))!=expected_recursive:
        raise RuntimeError('Include subfolders has changed. Click Preview / Resume first.')
    return plan

def apply(args,state):
    recursive=getattr(args,'expected_recursive',None)
    plan=load_apply_plan(state.work,getattr(args,'expected_input',None),getattr(args,'expected_output',None),
                         None if recursive is None else recursive=='true')
    output=Path(plan['output'])
    # Recover incomplete operations before considering new ones.
    for op in state.db.execute("SELECT * FROM operations WHERE status IN ('prepared','published')").fetchall():
        finish_operation(state,op)
    for category in CATEGORIES: (output/category).mkdir(parents=True,exist_ok=True)
    for row in state.rows():
        source=Path(row['source']); sha=row['sha256']
        existing=state.db.execute("SELECT mode,destination FROM operations WHERE source=? AND sha=? AND status='done'",(str(source),sha)).fetchone()
        if existing:
            if existing[0]!=args.mode: raise RuntimeError(f'Already applied as {existing[0]}; undo first to switch mode: {source}')
            if not Path(existing[1]).is_file() or digest(existing[1])!=sha: raise RuntimeError(f'Applied destination missing or changed: {existing[1]}')
            print(f'Already applied: {source.name}'); continue
        if row['category'] not in CATEGORIES: raise ValueError('Invalid category in plan')
        if not source.is_file() or digest(source)!=sha: raise RuntimeError(f'Source missing or changed since preview: {source}')
        destination=unique_path(output/row['category'],source.name)
        ident=uuid.uuid4().hex; stage=destination.parent/f'.valsort-{ident}.partial'
        op=(ident,str(source),str(destination),str(stage),sha,args.mode,'prepared')
        state.db.execute('INSERT INTO operations (id,source,destination,stage,sha,mode,status) VALUES (?,?,?,?,?,?,?)',op); state.db.commit()
        log_event(state.work,'prepared',id=ident,source=str(source),destination=str(destination),stage=str(stage),sha256=sha,mode=args.mode)
        finish_operation(state,op)
        print(f'{args.mode}: {source.name} -> {destination.parent.name}',flush=True)
    print(f'Apply complete. Undo journal: {state.work / "undo.jsonl"}')

def undo(args,state):
    for op in state.db.execute("SELECT * FROM operations WHERE status IN ('prepared','done','published','undoing') ORDER BY rowid DESC").fetchall():
        ident,src,dst,stage,sha,mode,status,owned,restored=op
        source,destination=Path(src),Path(dst)
        if status=='prepared':
            # Cancel an interrupted copy, or undo a publish that crashed before DB commit.
            if Path(stage).exists(): Path(stage).unlink()
            if not owned or not destination.exists() or identity(destination)!=owned:
                state.db.execute("UPDATE operations SET status='undone' WHERE id=?",(ident,)); state.db.commit()
                log_event(state.work,'cancelled',id=ident); continue
        if status!='undoing':
            if not destination.is_file() or (owned and identity(destination)!=owned) or digest(destination)!=sha: raise RuntimeError(f'Undo refuses missing/changed destination: {destination}')
            if mode=='copy' and (not source.is_file() or digest(source)!=sha): raise RuntimeError(f'Undo preserves the copy because its source is missing or changed: {source}')
            if mode=='move' and source.exists(): raise RuntimeError(f'Undo refuses to overwrite original path: {source}')
            state.db.execute("UPDATE operations SET status='undoing' WHERE id=?",(ident,)); state.db.commit()
            log_event(state.work,'undo_prepared',id=ident)
        if mode=='move':
            if source.exists():
                if not restored or identity(source)!=restored or digest(source)!=sha: raise RuntimeError(f'Undo refuses existing or changed original path: {source}')
            else:
                if not destination.is_file() or digest(destination)!=sha: raise RuntimeError('Cannot restore missing/changed destination')
                source.parent.mkdir(parents=True,exist_ok=True)
                restore=source.parent/f'.valsort-restore-{ident}.partial'
                if restore.exists() and digest(restore)!=sha: restore.unlink()
                if not restore.exists(): verified_copy(destination,restore,sha)
                restored=identity(restore)
                state.db.execute('UPDATE operations SET restore_identity=? WHERE id=?',(restored,ident)); state.db.commit()
                publish(restore,source)
        if destination.exists():
            if digest(destination)!=sha: raise RuntimeError(f'Destination changed during undo: {destination}')
            destination.unlink()
        state.db.execute("UPDATE operations SET status='undone' WHERE id=?",(ident,)); state.db.commit()
        log_event(state.work,'undone',id=ident); print(f'Undone: {destination}',flush=True)
    print('Undo complete. Empty category folders are retained.')

def main():
    p=argparse.ArgumentParser(description=__doc__); sub=p.add_subparsers(dest='command',required=True)
    q=sub.add_parser('preview',help='Analyze only; originals stay untouched')
    q.add_argument('--input',type=Path,required=True); q.add_argument('--output',type=Path,default=Path('Sorted'))
    q.add_argument('--work',type=Path,default=Path('sort_results')); q.add_argument('--names',nargs='+')
    q.add_argument('--recursive',action='store_true'); q.add_argument('--reanalyze',action='store_true')
    q.add_argument('--skip-feed',action='store_true',help='Skip slow review-only feed fallback')
    q=sub.add_parser('apply',help='Apply the saved preview')
    q.add_argument('--work',type=Path,default=Path('sort_results')); q.add_argument('--mode',choices=['copy','move'],default='copy')
    q.add_argument('--expected-input',type=Path); q.add_argument('--expected-output',type=Path)
    q.add_argument('--expected-recursive',choices=['true','false'])
    q=sub.add_parser('undo',help='Undo verified operations without overwriting files')
    q.add_argument('--work',type=Path,default=Path('sort_results'))
    args=p.parse_args()
    try:
        with Lock(args.work.resolve()):
            state=State(args.work)
            try: globals()[args.command](args,state)
            finally: state.close()
    except KeyboardInterrupt:
        print('Interrupted. Rerun the same command to resume.',file=sys.stderr); return 130
    except Exception as e:
        print(f'Error: {e}',file=sys.stderr); return 1
    return 0

if __name__=='__main__': raise SystemExit(main())
