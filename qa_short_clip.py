"""Derived fixture: short standard-match clip, not an independent labeled sample."""
from pathlib import Path
import json
import cv2
from prototype import Reader

out=Path('.tmp/short_fixture'); out.mkdir(parents=True,exist_ok=True)
cap=cv2.VideoCapture('sample_clips/5kills_nodeath_oneround_noassists.mp4')
duration=cap.get(cv2.CAP_PROP_FRAME_COUNT)/cap.get(cv2.CAP_PROP_FPS)
writer=cv2.VideoWriter(str(out/'short.mp4'),cv2.VideoWriter_fourcc(*'mp4v'),10,(1280,720))
for index in range(100):
    cap.set(cv2.CAP_PROP_POS_MSEC,(duration-10+index/10)*1000)
    ok,frame=cap.read()
    if not ok: raise RuntimeError('Fixture decode failed')
    writer.write(cv2.resize(frame,(1280,720)))
writer.release(); cap.release()
result=Reader().analyze(out/'short.mp4',out/'evidence')
(out/'result.json').write_text(json.dumps(result,indent=2),encoding='utf8')
print(result['category'],result['duration'])
assert result['category']=='Short clips'
