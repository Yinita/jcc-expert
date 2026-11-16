"""Read numeric counters only inside a visually and semantically anchored HUD.

The circular mobile skin has an XP button on the left, a small level badge,
and a same-height gold button on the right. Coordinates locate search areas;
actual circles, a visible XP control and parseable OCR digits are mandatory.
This module does not infer player HP from opponents or infer max level.
"""
from __future__ import annotations

import math
import re

import cv2
import numpy as np


def _compact(text):
    return re.sub(r"\s+", "", str(text))


def _center(box, width, height):
    x,y,w,h=box
    return (x+w/2)*width,(y+h/2)*height


def _circles(gray, bounds, low, high, threshold=25):
    h,w=gray.shape
    left,top,right,bottom=[round(v*s) for v,s in zip(bounds,(w,h,w,h))]
    crop=gray[top:bottom,left:right]
    result=cv2.HoughCircles(crop,cv2.HOUGH_GRADIENT,dp=1,minDist=max(8,h*.065),
                            param1=110,param2=threshold,
                            minRadius=max(5,round(low*h)),maxRadius=max(6,round(high*h)))
    return [] if result is None else [(float(x+left),float(y+top),float(r)) for x,y,r in result[0]]


def locate_mobile_hud(image, lines, context="unknown"):
    if context in {"orange_loadout","inventory","result"}:
        return None
    height,width=image.shape[:2]
    if width<700 or height<300 or not 1.85<=width/height<=2.6:
        return None
    anchors=[r for r in lines if float(r.get("confidence",0))>=.80 and
             _compact(r.get("text","")) in {"购买经验","满级","已满"} and
             r["bbox"][0]<.25 and .72<r["bbox"][1]<.96]
    # A collage containing multiple unrelated XP controls is ambiguous.
    centers={tuple(round(v,2) for v in r["bbox"][:2]) for r in anchors}
    if not anchors or len(centers)>2:
        return None
    scale=min(1.,600/height)
    small=cv2.resize(image,None,fx=scale,fy=scale,interpolation=cv2.INTER_AREA) if scale<1 else image
    h,w=small.shape[:2]
    gray=cv2.GaussianBlur(cv2.cvtColor(small,cv2.COLOR_BGR2GRAY),(5,5),1)
    left=_circles(gray,(0.,.68,.25,1.),.055,.13)
    right=_circles(gray,(.78,.68,1.,1.),.055,.13)
    anchored=[]
    for xp in left:
        x,y,r=xp
        if y/h<.81 or not any(math.hypot(*np.subtract(_center(a["bbox"],w,h),(x,y)))<r*.90 for a in anchors):
            continue
        anchored.append(xp)
    if len(anchored)!=1:
        return None
    xp=anchored[0]
    x,y,r=xp
    badges=_circles(gray,(max(0.,(x+.35*r)/w),max(.68,(y+.20*r)/h),
                           min(.3,(x+1.65*r)/w),min(1.,(y+1.35*r)/h)),.020,.052,18)
    badges=[c for c in badges if .5<=(c[0]-x)/r<=1.5 and .30<=(c[1]-y)/r<=1.25]
    # The small level badge can remain visible behind an overlay which hides
    # the gold button. It still needs its own real ring and XP text/large ring.
    regions={}
    golds=[g for g in right if g[1]/h>=.81 and abs(g[1]-y)<=h*.045 and .72<=g[2]/r<=1.35]
    if len(golds)==1:
        regions["gold"]=golds[0]
    if len(badges)==1:
        regions["level"]=badges[0]
    if not regions:
        return None
    return {"regions":{f:[cx/w,cy/h,cr/h] for f,(cx,cy,cr) in regions.items()},
            "xp_circle":[xp[0]/w,xp[1]/h,xp[2]/h],
            "kind":"anchored_circular_mobile_hud","requires_confirmation":True}


def _inside_core(row, circle, shape, field):
    h,w=shape[:2];cx,cy,r=circle;cx*=w;cy*=h;r*=h
    bx,by,bw,bh=row["bbox"];x,y=_center(row["bbox"],w,h)
    if field=="gold":
        return (abs(x-cx)<r*.75 and abs(y-cy)<r*.48 and
                by*h>cy-r*.70 and (by+bh)*h<cy+r*.75 and bw*w<r*1.75)
    return math.hypot(x-cx,y-cy)<r*.8 and bw*w<r*1.8 and bh*h<r*1.8


def read_mobile_hud(image, lines, *, context="unknown", backend=None):
    hud=locate_mobile_hud(image,lines,context)
    if hud is None:
        return [],None
    h,w=image.shape[:2];evidence=[]
    for field,circle in hud["regions"].items():
        rows=[r for r in lines if _inside_core(r,circle,image.shape,field)]
        # Keep lower-confidence competing digits as conflicts, never select the
        # most convenient answer from repeated OCR passes.
        candidates=[r for r in rows if float(r.get("confidence",0))>=.80 and
                    re.fullmatch(r"\d{1,3}",_compact(r.get("text","")))]
        values={int(_compact(r["text"])) for r in candidates}
        if len(values)>1:
            continue
        strong=[r for r in candidates if float(r["confidence"])>=.94]
        if not strong and backend is not None:
            cx,cy,rad=circle;cx*=w;cy*=h;rad*=h
            # Retain the digits and coin on the gold button, exclude its upper
            # interest badge. A second crop never uses a ground-truth box.
            x0=max(0,round(cx-rad*.80));x1=min(w,round(cx+rad*.88))
            y0=max(0,round(cy-rad*.48));y1=min(h,round(cy+rad*.52))
            if field=="level":
                x0=max(0,round(cx-rad*.75));x1=min(w,round(cx+rad*.75))
                y0=max(0,round(cy-rad*.72));y1=min(h,round(cy+rad*.72))
            crop=image[y0:y1,x0:x1]
            if min(crop.shape[:2])<8:
                continue
            enlarged=cv2.resize(crop,None,fx=3.,fy=3.,interpolation=cv2.INTER_CUBIC)
            extra,error=backend.read(enlarged)
            if error:
                continue
            for row in extra:
                b=row["bbox"]
                mapped={**row,"bbox":[(x0+b[0]*(x1-x0))/w,(y0+b[1]*(y1-y0))/h,
                                      b[2]*(x1-x0)/w,b[3]*(y1-y0)/h]}
                if (_inside_core(mapped,circle,image.shape,field) and float(row.get("confidence",0))>=.94
                        and re.fullmatch(r"\d{1,3}",_compact(row.get("text","")))):
                    candidates.append(mapped);strong.append(mapped)
            values={int(_compact(r["text"])) for r in candidates}
        if not strong or len(values)!=1:
            continue
        value=next(iter(values))
        if field=="level" and not 1<=value<=12:
            continue
        if field=="gold" and not 0<=value<=999:
            continue
        best=max(strong,key=lambda r:float(r["confidence"]))
        evidence.append({**best,"field":field,"value":value,"kind":"visual_anchored_hud_ocr",
                         "requires_confirmation":True,"value_source":"parseable_OCR_text",
                         "hud_geometry":hud,"score_is_calibrated_probability":False})
    return evidence,hud
