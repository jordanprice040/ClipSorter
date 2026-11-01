from pathlib import Path
import cv2
from PIL import Image, ImageDraw

out = Path('inspection')
out.mkdir(exist_ok=True)
for path in sorted(Path('sample_clips').glob('*.mp4')):
    cap = cv2.VideoCapture(str(path))
    duration = cap.get(cv2.CAP_PROP_FRAME_COUNT) / cap.get(cv2.CAP_PROP_FPS)
    times = sorted(set([duration*f for f in [.1,.3,.5,.7,.85,.95,.99]]))
    sheet = Image.new('RGB', (960, 4*294))
    draw = ImageDraw.Draw(sheet)
    for i,t in enumerate(times):
        cap.set(cv2.CAP_PROP_POS_MSEC,t*1000)
        ok, frame=cap.read()
        if not ok: continue
        img=Image.fromarray(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB))
        img.thumbnail((480,270))
        x,y=(i%2)*480,(i//2)*294
        sheet.paste(img,(x,y+24))
        draw.text((x+5,y+4),f'{t:.1f}s / {duration:.1f}s',fill='white')
    cap.release()
    sheet.save(out/(path.stem+'.jpg'))
    print(path.name,round(duration,2),flush=True)
