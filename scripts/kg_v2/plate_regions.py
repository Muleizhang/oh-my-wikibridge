"""Local figure geometry: isolated labels, complete panels, and spatial pairing."""
import re

import cv2
import numpy as np


def area(b):
    return max(0, b[2]-b[0])*max(0, b[3]-b[1])


def overlap(a, b):
    return area([max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])])


def text_line(line):
    # Thin drawings (hairpins in particular) are sometimes OCR'd as characters.
    return line['score'] > .7 and (len(re.findall(r'[\u3400-\u9fff]', line['text'])) >= 2
                                   or bool(re.search(r'\d.*(?:厘米|毫米|cm|mm)', line['text'])))


def erase(mask, box, scale=1, pad=0):
    x1, y1, x2, y2 = [round(v*scale) for v in box]
    h, w = mask.shape
    mask[max(0,y1-pad):min(h,y2+pad), max(0,x1-pad):min(w,x2+pad)] = 0


def marginal_number(box, width, height):
    x, y = (box[0]+box[2])/2, (box[1]+box[3])/2
    return (x < .065*width or x > .945*width) and .40*height < y < .60*height


def panels(gray, lines):
    h, w = gray.shape
    scale = min(1, 1000/w)
    mask = cv2.inRange(cv2.resize(gray, None, fx=scale, fy=scale), 0, 211)
    hh, ww = mask.shape
    for line in lines:
        if text_line(line):
            erase(mask, line['bbox'], scale, 3)
    mask[:round(.04*hh)] = 0
    mask[round(.965*hh):] = 0
    mask[:, :round(.045*ww)] = 0
    mask[:, round(.97*ww):] = 0
    connected = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5,5), np.uint8))
    contours, _ = cv2.findContours(connected, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for contour in contours:
        x, y, bw, bh = cv2.boundingRect(contour)
        ratio = cv2.contourArea(contour)/(bw*bh)
        if .008*hh*ww < bw*bh < .35*hh*ww and ratio > .80:
            polygon = cv2.approxPolyDP(contour, .015*cv2.arcLength(contour, True), True)
            if len(polygon) <= 6:
                boxes.append([round(v/scale) for v in [x,y,x+bw,y+bh]])
    return boxes


def isolated_digits(image, gray, lines):
    """Find labels before figures, so failed figure segmentation cannot hide labels."""
    h, w = gray.shape
    photographs = panels(gray, lines)
    candidates = []
    for threshold in (160, 205):
        mask = cv2.inRange(gray, 0, threshold)
        mask[:round(.04*h)] = 0
        mask[round(.97*h):] = 0
        mask[:,:round(.035*w)] = 0
        mask[:,round(.98*w):] = 0
        for line in lines:
            if text_line(line):
                erase(mask, line['bbox'], pad=8)
        for box in photographs:
            erase(mask, box)
        _, _, stats, _ = cv2.connectedComponentsWithStats(mask)
        for x, y, bw, bh, ink in stats[1:]:
            if not (.004*h <= bh <= .02*h and .0012*w <= bw <= .045*w
                    and .05 <= bw/bh <= 2.5 and 25 <= ink <= h*w*.00025):
                continue
            box = [int(x),int(y),int(x+bw),int(y+bh)]
            if marginal_number(box,w,h):
                continue
            pad = max(5,round(bh*.45))
            x1,y1,x2,y2 = max(0,x-pad),max(0,y-pad),min(w,x+bw+pad),min(h,y+bh+pad)
            outside = cv2.countNonZero(mask[y1:y2,x1:x2])-cv2.countNonZero(mask[y:y+bh,x:x+bw])
            density = outside/max(1,(x2-x1)*(y2-y1)-bw*bh)
            if density <= .035 and not any(overlap(box,b)>.55*min(area(box),area(b)) for b in candidates):
                candidates.append(box)
    # Printed labels 10, 11, ... consist of separate connected glyphs.
    combined = []
    for a in candidates:
        for b in candidates:
            ah,bh = a[3]-a[1],b[3]-b[1]
            if a[2] <= b[0] <= a[2]+.7*max(ah,bh) and abs(a[3]-b[3]) < .22*max(ah,bh) and .65 < ah/bh < 1.5:
                combined.append([a[0],min(a[1],b[1]),b[2],max(a[3],b[3])])
    candidates = combined+candidates
    patches = [image[max(0,y1-6):min(h,y2+6),max(0,x1-6):min(w,x2+6)] for x1,y1,x2,y2 in candidates]
    return patches,candidates


def deduplicate_labels(labels, width, height):
    labels = [r for r in labels if not marginal_number(r['bbox'],width,height)]
    # A recognized '1' inside a recognized '10' must not become a second label.
    labels.sort(key=lambda r: (-len(str(r['item'])), -r['score']))
    kept = []
    for row in labels:
        if any(overlap(row['bbox'],other['bbox']) > .45*min(area(row['bbox']),area(other['bbox'])) for other in kept):
            continue
        kept.append(row)
    return kept


def clean_boxes(boxes, labels, width, height):
    cleaned = []
    for box in sorted(boxes,key=area,reverse=True):
        if any(overlap(box,b) > .88*area(box) for b in cleaned):
            continue
        # Large scanning frames or a whole stack of illustrations are not objects.
        bh,bw = box[3]-box[1],box[2]-box[0]
        nearby = [r for r in labels if box[1] < r['bbox'][1] < box[3]
                  and abs(r['bbox'][2]-box[2]) < .08*width]
        if bh > .55*height and bw > .12*width and len({r['item'] for r in nearby}) > 1:
            continue
        if bh > .35*height and bw < .04*width and box[0] < .06*width:
            continue
        cleaned.append(box)
    return sorted(cleaned,key=lambda b:(b[1],b[0]))


def complete_regions(gray, lines, labels, layout):
    h,w = gray.shape
    scale = min(1,1000/w)
    mask = cv2.inRange(cv2.resize(gray,None,fx=scale,fy=scale),0,211)
    hh,ww = mask.shape
    for line in lines:
        if text_line(line) or (line['text'].strip().isdigit() and line['score']>.8):
            erase(mask,line['bbox'],scale,2)
    for label in labels:
        erase(mask,label['bbox'],scale,2)
    # Reuse precise cached image boxes, but reject whole-page/column detections.
    raw = layout['raw']
    fixed = []
    captions=[line['bbox'] for line in lines if re.match(r'^\s*\d{1,2}\s*[.．、]\s*[\u3400-\u9fff]',line['text'])]
    for block in raw['layout_det_res']['boxes']:
        if block['label']!='image' or block['score']<.65:
            continue
        box=[round(v*k) for v,k in zip(block['coordinate'],[w/raw['width'],h/raw['height']]*2)]
        inside = [r for r in labels if overlap(box,r['bbox'])>.5*area(r['bbox'])]
        if (.008*w*h < area(box) < .32*w*h and len(inside)<2
                and not any(overlap(box,caption)>.5*area(caption) for caption in captions)):
            fixed.append(box)
    fixed.extend(panels(gray,lines))
    fixed = clean_boxes(fixed,labels,w,h)
    for box in fixed:
        erase(mask,box,scale,8)
    mask[:round(.04*hh)] = 0
    mask[round(.965*hh):] = 0
    mask[:,:round(.02*ww)] = 0
    mask[:,round(.97*ww):] = 0
    for kernel in [(1,80),(80,1)]:
        rules=cv2.morphologyEx(mask,cv2.MORPH_OPEN,np.ones(kernel,np.uint8))
        _, components, stats, _=cv2.connectedComponentsWithStats(rules)
        thin=np.zeros_like(mask)
        for index,(x,y,bw,bh,ink) in enumerate(stats[1:],1):
            if min(bw,bh)<=3:
                thin[components==index]=255
        # Only marginal thin rules, never every long line within a drawing/photo.
        thin[round(.10*hh):round(.93*hh),round(.075*ww):round(.93*ww)]=0
        mask[cv2.dilate(thin,np.ones((3,3),np.uint8))>0]=0
    connected=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
    _,_,stats,_=cv2.connectedComponentsWithStats(connected)
    boxes=list(fixed)
    for x,y,bw,bh,ink in stats[1:]:
        if not (ink > hh*ww*.00014 and bw > ww*.006 and bh > hh*.015 and bw*bh > hh*ww*.001):
            continue
        if bw>.25*ww and bh>.45*hh and ink/(bw*bh)<.15:
            continue
        box=[round(v/scale) for v in [x,y,x+bw,y+bh]]
        # Residual blank paper beside a detected photograph is not a second view.
        if bw<.065*ww and bh>.12*hh:
            x1,y1,x2,y2=box
            neighbors=[b for b in fixed if max(0,min(b[3],y2)-max(b[1],y1))>.6*(y2-y1)
                       and min(abs(x1-b[2]),abs(x2-b[0]))<.025*w]
            if neighbors and float(np.std(gray[y1:y2,x1:x2]))<18:
                continue
        boxes.append(box)
    return clean_boxes(boxes,labels,w,h)


def nearest_groups(boxes, labels, width, height):
    duplicates={r['item'] for r in labels if sum(s['item']==r['item'] for s in labels)>1}
    usable=[r for r in labels if r['item'] not in duplicates]
    groups={r['item']:[] for r in usable}
    unassigned=[]
    for index,box in enumerate(boxes):
        options=[]
        for label in usable:
            x1,y1,x2,y2=label['bbox']
            ax,ay=(x1+x2)/2,(y1+y2)/2
            if ay < box[1]+.50*(box[3]-box[1]) or ay-box[3] > .70*height:
                continue
            if ax < box[0]-.06*width or ax > box[2]+.70*width:
                continue
            dx=abs(ax-box[2])/width
            dy=abs(ay-box[3])/height
            cost=1.8*dx+2.5*dy
            options.append((cost,label['item']))
        if options:
            cost,item=min(options)
            if cost<1.5:
                groups[item].append(index)
                continue
        unassigned.append(index)
    return groups,unassigned,sorted(duplicates),[]


def choose_regions(image, gray, lines, labels, layout, legacy):
    h,w=gray.shape
    modern=complete_regions(gray,lines,labels,layout)
    legacy=clean_boxes(legacy,labels,w,h)
    caption_lines=[line for line in lines if re.match(r'^\s*\d{1,2}\s*[.．、]\s*[\u3400-\u9fff]',line['text'])]
    # A visual box spanning the catalog text is not a complete-object crop.
    modern=[b for b in modern if not any(overlap(b,line['bbox'])>.5*area(line['bbox']) for line in caption_lines)]
    legacy=[b for b in legacy if not any(overlap(b,line['bbox'])>.5*area(line['bbox']) for line in caption_lines)]
    new_groups,*_=nearest_groups(modern,labels,w,h)
    old_groups,*_=nearest_groups(legacy,labels,w,h)
    new_coverage=sum(bool(v) for v in new_groups.values())
    old_coverage=sum(bool(v) for v in old_groups.values())
    chroma=np.max(image,axis=2).astype(np.int16)-np.min(image,axis=2).astype(np.int16)
    colorful=float(np.mean(chroma>35))>.08
    if colorful or new_coverage>old_coverage or not legacy:
        return modern,'complete_panels_components'
    return legacy,'ink_components_with_spatial_pairing'
