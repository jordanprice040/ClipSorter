"""Labels are read ONLY here, never by the visual analyzer."""
import argparse
import csv
import json
import re
from pathlib import Path

def expected(name):
    low=name.lower()
    if low=='deathmatch.mp4': return 'Deathmatch'
    if low=='range.mp4': return 'Range'
    if low=='notinmatch.mp4': return 'Outside of match'
    if low=='sub20sec_doubleclip.mp4': return 'Short clips'
    m=re.search(r'(\d+)kills?',low)
    if not m: raise ValueError(f'No label: {name}')
    return str(int(m[1])) if int(m[1])<5 else '5+'

def validate(path):
    results=json.loads(path.read_text(encoding='utf8'))
    rows=[dict(file=r.get('file',Path(r.get('source','')).name),expected=expected(r.get('file',Path(r.get('source','')).name)),predicted=r['category'],
               correct=r['category']==expected(r.get('file',Path(r.get('source','')).name)),
               timestamps=';'.join(f'{t:.3f}' for t in r['timestamps'])) for r in results]
    with path.with_name('validation.csv').open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=rows[0]); writer.writeheader(); writer.writerows(rows)
    correct=sum(r['correct'] for r in rows); review=sum(r['predicted']=='Needs review' for r in rows)
    print(json.dumps(dict(total=len(rows),correct=correct,review=review,wrong=len(rows)-correct-review)))
    return correct==len(rows)

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('results',type=Path)
    raise SystemExit(0 if validate(p.parse_args().results) else 1)
