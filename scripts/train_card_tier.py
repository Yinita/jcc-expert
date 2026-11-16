#!/usr/bin/env python3
"""Fit candidate HOG/linear-SVM suffix models on development titles only."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import sys
from collections import Counter

import cv2
import numpy as np
from PIL import Image,ImageDraw,ImageFont

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.card_tier_model import TIERS,CardTierModel,extract_suffix,glyph_features


def synthetic(font_path,tier,seed):
    rng=np.random.default_rng(seed)
    image=Image.new('L',(160,100),0)
    draw=ImageDraw.Draw(image)
    font=ImageFont.truetype(str(font_path),int(rng.integers(28,66)))
    draw.text((10,5),tier,fill=255,font=font,stroke_width=int(rng.integers(0,2)))
    glyph=np.asarray(image)
    ys,xs=np.where(glyph>70)
    glyph=glyph[ys.min():ys.max()+1,xs.min():xs.max()+1]
    # Small blur and resize perturbations remain entirely within this font group.
    if seed%3==0:glyph=cv2.GaussianBlur(glyph,(3,3),.4)
    return glyph


def load_real(path):
    path=Path(path).resolve();payload=json.loads(path.read_text());rows=[]
    if any(s.get('evaluation_role')=='sealed_test' or s.get('split')=='holdout' for s in payload['samples']):
        raise ValueError('Training input must contain development samples only; sealed labels are forbidden')
    for sample in payload['samples']:
        file=path.parent/(sample.get('file') or sample.get('path'))
        image=cv2.imread(str(file))
        if image is None:raise ValueError('Unreadable development image')
        for index,entity in enumerate(sample.get('card_boxes',sample['labels'].get('entities',[]))):
            match=re.fullmatch(r'(.+?)\s+(I|II|III|IV|V)',entity.get('name',''))
            box=entity.get('title_bbox')
            if not match or not box:continue
            x,y,w,h=box;ih,iw=image.shape[:2]
            crop=image[round(y*ih):round((y+h)*ih),round(x*iw):round((x+w)*iw)]
            glyph,error=extract_suffix(crop)
            rows.append({'id':sample['id']+f':{index}','group':sample['group_id'],'name':entity['name'],
                         'base_name':match[1],'tier':match[2],'glyph':glyph,'crop':crop,'segmentation_error':error})
    return rows


def split_real(rows,validation_group):
    validation=[r for r in rows if r['group']==validation_group]
    # A card title reused across publishers may derive from the same rendered
    # asset. Purge those identities from training as well as splitting sources.
    heldout_card_names={r['name'] for r in validation}
    purged=[r for r in rows if r['group']!=validation_group and r['name'] in heldout_card_names]
    training=[r for r in rows if r['group']!=validation_group and r['name'] not in heldout_card_names]
    return training,validation,purged


def run(annotations,output):
    cv2.setNumThreads(2);output=Path(output);output.mkdir(parents=True,exist_ok=True)
    real=load_real(annotations);groups=sorted({r['group'] for r in real})
    if len(groups)<2:raise ValueError('At least two real source groups are required for group validation')
    validation_group=next((g for g in groups if 'taptap' in g),groups[-1])
    real_train,real_validation,purged=split_real(real,validation_group)
    # Typeface-family separation, not random crop/augmentation splitting.
    font_families={
      'dejavu_sans':['/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'],
      'liberation_sans':['/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf','/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf'],
      'liberation_serif':['/usr/share/fonts/truetype/liberation2/LiberationSerif-Regular.ttf']}
    feature_rows=[];labels=[];synth_validation=[];synth_counts=Counter()
    for family,fonts in font_families.items():
        for font in fonts:
            if not Path(font).exists():continue
            for index,tier in enumerate(TIERS):
                for seed in range(24):
                    glyph=synthetic(font,tier,seed+index*100)
                    if family=='liberation_serif':synth_validation.append((glyph,tier,family))
                    else:feature_rows.append(glyph_features(glyph));labels.append(index)
                    synth_counts['validation' if family=='liberation_serif' else 'train']+=1
    for row in real_train:
        if row['glyph'] is not None:feature_rows.append(glyph_features(row['glyph']));labels.append(TIERS.index(row['tier']))
    features=np.asarray(feature_rows,np.float32);target=np.asarray(labels,np.int32)
    orientations={}
    for index,tier in enumerate(TIERS):
        binary=np.where(target==index,1,-1).astype(np.int32)
        model=cv2.ml.SVM_create();model.setType(cv2.ml.SVM_C_SVC);model.setKernel(cv2.ml.SVM_LINEAR);model.setC(2.)
        model.setTermCriteria((cv2.TERM_CRITERIA_MAX_ITER|cv2.TERM_CRITERIA_EPS,10000,1e-5))
        model.train(features,cv2.ml.ROW_SAMPLE,binary)
        raw=model.predict(features,flags=cv2.ml.StatModel_RAW_OUTPUT)[1].ravel()
        orientations[tier]=1. if raw[target==index].mean()>raw[target!=index].mean() else -1.
        model.save(str(output/f'svm_{tier}.xml'))
    official=json.loads((ROOT/'app/data/orange_official_facts.json').read_text())
    allowed=sorted({match[1] for row in official['cards'] if (match:=re.fullmatch(r'(.+?)\s+(I|II|III|IV|V)',row.get('name_zh','')))})
    manifest={'schema_version':1,'model':'HOG+geometry five one-vs-rest linear SVMs','classes':TIERS,'orientations':orientations,
              'allowed_base_names':allowed, 'base_name_allowlist_source':'official static card catalog, independent of screenshot labels',
              'minimum_margin_confidence':.65,
              'approved_for_use':False,'notice':'Experimental; confidence is an uncalibrated margin score. Never auto-correct card IDs.',
              'training_annotations_sha256':hashlib.sha256(Path(annotations).read_bytes()).hexdigest()}
    (output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    fitted=CardTierModel(output)
    def evaluate_real(rows):
        outcomes=[]
        for r in rows:
            prediction=fitted.predict_title(r['crop'],r['base_name'])
            outcomes.append({k:r[k] for k in ['id','group','name','tier','segmentation_error']}|{'prediction':prediction,
                            'outcome':'abstain' if prediction['tier'] is None else 'correct' if prediction['tier']==r['tier'] else 'wrong'})
        return {'count':len(rows),'outcomes':dict(Counter(r['outcome'] for r in outcomes)),'records':outcomes}
    synth_correct=sum(fitted.classify_glyph(glyph)['tier']==tier for glyph,tier,family in synth_validation)
    report={'status':'candidate_not_integrated','real_counts':{'train':len(real_train),'validation':len(real_validation),
              'train_segmented':sum(r['glyph'] is not None for r in real_train),'validation_segmented':sum(r['glyph'] is not None for r in real_validation),
              'train_classes':dict(Counter(r['tier'] for r in real_train)),'validation_classes':dict(Counter(r['tier'] for r in real_validation))},
            'source_group_split':{'training':[g for g in groups if g!=validation_group],'validation':[validation_group],
                                  'purged_shared_card_identity_count':len(purged),'purged_records':[r['id'] for r in purged],
                                  'card_name_intersection_train_validation':sorted({r['name'] for r in real_train}&{r['name'] for r in real_validation})},
            'synthetic_counts':dict(synth_counts),'synthetic_validation':{'correct':synth_correct,'total':len(synth_validation),'font_family':'liberation_serif'},
            'real_training_evaluation':evaluate_real(real_train),'real_group_validation':evaluate_real(real_validation),
            'limitations':['Only development annotations were loaded; no sealed screenshots or labels were inspected.',
                          'Real validation contains very few independent examples and may not cover II/III/IV/V.',
                          'Synthetic validation is not real-game accuracy; it measures glyph classification after ideal segmentation.',
                          'Title segmentation can reject or include Chinese strokes; failed/ambiguous crops are abstentions.',
                          'No recognizer integration and no card-ID mutation; model is an unapproved candidate.']}
    report['weight_files']=[{'file':p.name,'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(output.glob('svm_*.xml'))]
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--annotations',type=Path,required=True)
    parser.add_argument('--output',type=Path,default=ROOT/'var/models/card-tier-candidate')
    args=parser.parse_args();run(args.annotations,args.output)
