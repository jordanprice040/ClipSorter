import cv2, json
from pathlib import Path
from rapidocr_onnxruntime import RapidOCR
ocr=RapidOCR(intra_op_num_threads=2,inter_op_num_threads=2)
out=Path('inspection'); records=[]
for path in sorted(Path('sample_clips').glob('*.mp4')):
    cap=cv2.VideoCapture(str(path)); duration=cap.get(7)/cap.get(5)
    for offset in [1,4,8]:
        t=max(0,duration-offset); cap.set(cv2.CAP_PROP_POS_MSEC,t*1000); ok,f=cap.read()
        if not ok:continue
        h,w=f.shape[:2]; crop=f[int(h*.20):int(h*.84),int(w*.775):int(w*.998)]
        crop=cv2.resize(crop,None,fx=2,fy=2)
        cv2.imwrite(str(out/f'{path.stem}_{offset}.png'),crop)
        result,_=ocr(crop)
        records.append(dict(file=path.name,t=t,offset=offset,text=result))
    cap.release()
    print(path.name,[(r['offset'],[(x[1],round(float(x[2]),2)) for x in r['text'] or []]) for r in records[-3:]],flush=True)
    (out/'ocr.json').write_text(json.dumps(records,indent=2),encoding='utf8')
