"""Read-only visual prototype. Never uses filenames as recognition input."""
import argparse
import json
import re
from pathlib import Path
import cv2
import numpy as np
from rapidocr_onnxruntime import RapidOCR

VERSION = 'prototype-3-zero'
NAMES = ['BecauseWhyNot','BecauseWhyAlt','BecauseWhyNot040','JordanTimes5','Jardon',
         'zoom12','NorthRememberers','Rebound','Gabimaru']

def compact(text):
    return re.sub(r'[^A-Z0-9]', '', text.upper())

class Reader:
    def __init__(self, names=None):
        self.ocr = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=2)
        self.names = {compact(n) for n in (names or NAMES)}

    def feed_evidence(self, cap, duration, evidence):
        """Track named outgoing feed events for human review, never guess a round total.

        Feed entries can disappear behind menus, repeat victims after resurrection,
        or be absent at the start of a recording. Without a proven complete round,
        this is supporting evidence, not a reliable exact kill count.
        """
        events=[]; tracks={}
        for index in range(int(duration*2)):
            t=index/2
            cap.set(cv2.CAP_PROP_POS_MSEC,t*1000); ok,f=cap.read()
            if not ok: continue
            h,w=f.shape[:2]
            crop=f[int(h*.065):int(h*.31),int(w*.70):]
            crop=cv2.resize(crop,None,fx=2,fy=2)
            rows=self.read(crop)
            for a in rows:
                if compact(a['text']) not in self.names or a['x']>=.55 or a['confidence']<.70: continue
                victims=[v for v in rows if v['x']>.60 and abs(v['y']-a['y'])<.035 and v['confidence']>=.65]
                if len(victims)!=1: continue
                victim=victims[0]; key=(compact(a['text']),compact(victim['text']))
                if key not in tracks or t-tracks[key]>8:
                    events.append(dict(timestamp=t,attacker=a['text'],victim=victim['text']))
                    cv2.imwrite(str(evidence/f'feed_{t:.2f}.jpg'),f)
                tracks[key]=t
        return events

    def read(self, frame):
        rows, _ = self.ocr(frame)
        return [{'text': r[1], 'confidence': float(r[2]),
                 'x': sum(p[0] for p in r[0])/4/frame.shape[1],
                 'y': sum(p[1] for p in r[0])/4/frame.shape[0]} for r in rows or []]

    def report(self, frame):
        h,w=frame.shape[:2]
        crop=frame[int(h*.20):int(h*.84),int(w*.775):int(w*.998)]
        crop=cv2.resize(crop,None,fx=2,fy=2)
        rows=self.read(crop)
        headers=[r for r in rows if compact(r['text'])=='COMBATREPORT' and r['confidence']>=.70]
        if not headers: return None
        header=headers[0]
        # A complete panel must show its footer; do not count truncated reports.
        footer=any('TOGGLEMOUSE' in compact(r['text']) or 'HIDEREPORT' in compact(r['text']) for r in rows)
        kills=[r for r in rows if compact(r['text'])=='KILLED' and r['x']<.30
               and r['y']>header['y'] and r['confidence']>=.55]
        assists=[r for r in rows if compact(r['text'])=='ASSIST' and r['x']<.30
                 and r['y']>header['y']]
        end_candidates=[r['y'] for r in rows if r['y']>header['y']+.05 and
                        (compact(r['text']) in {'ROUNDONGOING','ABILITY'} or
                         'HIDEREPORT' in compact(r['text']) or 'TOGGLEMOUSE' in compact(r['text']))]
        end=min(end_candidates,default=.95)
        damage=[r for r in rows if .08<r['x']<.23 and header['y']<r['y']<end
                and re.fullmatch(r'\d{1,3}',r['text']) and r['confidence']>=.55]
        # Kill/assist rows have a red outgoing border even when OCR drops a label.
        # Zero is accepted only with positively read damage rows and no outgoing
        # highlight, not merely an absence of KILLED text.
        ch,cw=crop.shape[:2]
        lane=crop[int((header['y']+.025)*ch):int((end-.01)*ch),int(cw*.050):int(cw*.065)].astype(np.int16)
        red=(lane[:,:,2]>130)&(lane[:,:,2]>lane[:,:,1]*1.35)&(lane[:,:,2]>lane[:,:,0]*1.15)
        red_height=int(np.count_nonzero(np.mean(red,axis=1)>.20)) if lane.size else 0
        highlighted=round(red_height/(ch*.085))
        labels_complete=highlighted==len(kills)+len(assists)
        zero_verified=bool(damage) and red_height<ch*.01 and not kills and not assists
        return dict(kills=len(kills), assists=len(assists),complete=footer,
                    rows=rows, confidence=min([header['confidence']]+[r['confidence'] for r in kills]),
                    highlighted_rows=highlighted,labels_complete=labels_complete,
                    zero_verified=zero_verified,damage_rows=[r['text'] for r in damage])

    def analyze(self, path, evidence, feed_fallback=False):
        cap=cv2.VideoCapture(str(path))
        fps=cap.get(cv2.CAP_PROP_FPS); count=cap.get(cv2.CAP_PROP_FRAME_COUNT)
        if fps<=0 or count<=0: raise ValueError('Cannot decode video metadata')
        duration=count/fps
        evidence.mkdir(parents=True,exist_ok=True)
        def frame_at(t):
            cap.set(cv2.CAP_PROP_POS_MSEC,max(0,t)*1000)
            ok,f=cap.read()
            if not ok: raise ValueError(f'Cannot decode frame at {t:.2f}s')
            return f
        terminal=[]
        try:
            for offset in [.2,2,5]:
                t=max(0,duration-offset); f=frame_at(t)
                h,w=f.shape[:2]; resized=cv2.resize(f,(1280,round(h*1280/w)))
                rows=self.read(resized); words=[compact(r['text']) for r in rows]
                joined=' '.join(words)
                category=None
                if ('CHANGESETTINGS' in joined or 'BOTARMOR' in joined or 'PRACTICE' in joined
                    or ('CHALLENGE' in joined and 'ENABLED' in joined)):
                    category='Range'
                elif (any(x in joined for x in ['SINGLEKILL','DOUBLEKILL','TRIPLEKILL','RESPAWNING'])
                      or (any(re.fullmatch(r'[2-9]:[0-5][0-9]',r['text']) and .45<r['x']<.55 and r['y']<.08 for r in rows)
                          and any(len(re.sub(r'\D','',r['text']))>=6 and .22<r['x']<.45 and .02<r['y']<.07 for r in rows))):
                    category='Deathmatch'
                elif any(x in joined for x in ['PLAYAGAIN','ACCOLADES','PERFORMANCESCORE',
                                                'COLLECTION','BATTLEPASS','MATCHHISTORY']):
                    category='Outside of match'
                terminal.append(dict(timestamp=t,category=category,rows=rows))
                cv2.imwrite(str(evidence/f'terminal_{t:.2f}.jpg'),f)
            cats=[x['category'] for x in terminal]
            for cat in ['Range','Deathmatch','Outside of match']:
                if cats.count(cat)>=2:
                    return dict(category=cat,kills=None,method='terminal HUD',duration=duration,
                                reason='Repeated terminal HUD evidence',timestamps=[x['timestamp'] for x in terminal if x['category']==cat],terminal=terminal)
            if any(cats):
                return dict(category='Needs review',kills=None,method='ambiguous HUD',duration=duration,
                            reason='Terminal mode evidence is inconsistent; kill counting withheld',
                            timestamps=[x['timestamp'] for x in terminal],terminal=terminal)
            # Standard HUD evidence: a round timer and minimap/health OCR, across frames.
            standard=sum(any(re.fullmatch(r'[01]:[0-5][0-9]',r['text']) for r in x['rows']) for x in terminal)>=2
            if duration<20 and standard:
                return dict(category='Short clips',kills=None,method='duration + HUD',duration=duration,
                            reason='Under 20 seconds with standard match timer',timestamps=[x['timestamp'] for x in terminal],terminal=terminal)
            reports=[]
            # Dense sampling at the end catches reports shown only in the final half-second.
            offsets=[.15,.4,.7,1,1.4,2,3,5,8,12,16,20,25,30]
            for offset in offsets:
                t=max(0,duration-offset); f=frame_at(t); r=self.report(f)
                if r:
                    r['timestamp']=t; reports.append(r)
                    cv2.imwrite(str(evidence/f'report_{t:.2f}.jpg'),f)
                if len(reports)>=2:
                    if reports[0]['kills']>0: break
                    verified=[tuple(r['damage_rows']) for r in reports if r['zero_verified']]
                    if any(verified.count(x)>=2 for x in verified): break
            if reports:
                latest=reports[0]
                # Never infer zero from missing OCR text.
                agree=len(reports)>=2 and reports[1]['kills']==latest['kills'] and all(r['complete'] and r['labels_complete'] for r in reports)
                verified=[tuple(r['damage_rows']) for r in reports if r['zero_verified']]
                zero=all(r['zero_verified'] for r in reports) and any(verified.count(x)>=2 for x in verified)
                if agree and (latest['kills']>0 or zero) and min(r['confidence'] for r in reports)>=.60:
                    k=latest['kills']
                    return dict(category=str(k) if k<5 else '5+',kills=k,method='combat report',duration=duration,
                                reason='Two complete reports agree on outgoing KILLED labels',
                                timestamps=[r['timestamp'] for r in reports],reports=reports,terminal=terminal)
            events=self.feed_evidence(cap,duration,evidence) if feed_fallback else []
            return dict(category='Needs review',kills=None,method='kill-feed evidence' if events else 'uncertain',duration=duration,
                        reason='No repeated complete final report. Feed events are review-only; exact final-round total is unproven.',
                        timestamps=[r['timestamp'] for r in reports]+[e['timestamp'] for e in events],
                        reports=reports,terminal=terminal,feed_events=events)
        finally:
            cap.release()

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('folder',type=Path)
    parser.add_argument('--output',type=Path,default=Path('prototype_results'))
    args=parser.parse_args(); args.output.mkdir(exist_ok=True,parents=True)
    reader=Reader(); results=[]
    for p in sorted(args.folder.glob('*.mp4')):
        r=reader.analyze(p,args.output/p.stem); r['file']=p.name; results.append(r)
        print(p.name,r['category'],r.get('timestamps'),flush=True)
        (args.output/'results.json').write_text(json.dumps(results,indent=2),encoding='utf8')

if __name__=='__main__': main()
