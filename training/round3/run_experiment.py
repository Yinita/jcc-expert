from pathlib import Path
from copy import deepcopy
import hashlib,importlib.util,json,sys

ROOT=Path(__file__).resolve().parents[2]
PROJECT=ROOT/'outputs/jcc-expert'
sys.path.insert(0,str(PROJECT))
OUT=ROOT/'work/round3_training'

def module(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def prepare():
 plan={'sohu_1068964903':'train','source_chuapp_291737':'train','ali213_1032951':'train','source_taptap_867251881297052929':'train',
       'youxituoluo_534823':'calibration','source_taptap_867454613899445849':'calibration','source_taptap_867151065470994551':'calibration',
       'chuapp_291576':'validation','17173_08242026_093003976':'validation','source_3dm_3746579':'validation','source_taptap_867484028389820540':'validation'}
 samples=[];records={};seen_pixels={}
 for split in ['development','sealed']:
  folder=ROOT/'work/expanded_eval'/split
  annotation=json.load(open(ROOT/'work/expanded_eval'/(split+'.json')))
  runs={r['sample_id']:r for r in json.load(open(folder/'optimized/report.json'))['runs']if r.get('track')=='default'}
  for original in annotation['samples']:
   s=deepcopy(original);sid=s['id'];rawpath=folder/'optimized'/runs[sid]['raw_file'];raw=json.load(open(rawpath))['recognition']
   f=Path(s['file']);s['file']=str(f.resolve());content=sha(f)
   if runs[sid].get('file_sha256') and runs[sid]['file_sha256']!=content:raise ValueError('Old consumed image changed')
   pixel=runs[sid].get('decoded_image_sha256')
   if pixel in seen_pixels:raise ValueError('Repeated old image pixels')
   seen_pixels[pixel]=sid
   s.update(split=plan[s['group_id']],partition=plan[s['group_id']],evaluation_role='consumed_round2_development',sealed_test=False,original_evaluation_role=original.get('evaluation_role'))
   s['inference_screen_type']=raw.get('screen_type','unknown')
   if all(field in s.get('expected_absent_current_state_fields',[])for field in ['stage','gold','hp','level']):
    s['known_absent_fields']=['stage','gold','hp','level'];s['field_annotation_complete']=True
   if not s.get('field_boxes') and s.get('profile_origin')=='per_sample_manual':
    s['field_boxes']={slot['field']:slot['bbox']for slot in s.get('layout_profile',{}).get('slots',[])if slot['field']in ['stage','gold','hp','level']}
   lines=[{'text':r['text'],'confidence':r['confidence'],'bbox':r['bbox']}for r in raw.get('evidence',[])if r.get('kind')=='ocr_text']
   size=raw['image_size'];shape=(size['height'],size['width'],3)
   records[sid]={'lines':lines,'shape':shape,'raw_sha256':sha(rawpath),'image_sha256':content}
   samples.append(s)
 payload={'purpose':'Round3 recognition training improvement on OLD38 consumed development only. No round3 sealed paths or labels are opened.','fixed_source_plan':plan,'samples':samples}
 (OUT/'annotations_consumed38.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2))
 (OUT/'experiment_plan.json').write_text(json.dumps({'fixed_before_fit':True,'source_plan':plan,'candidate_activation_allowed':False,'target_precision':.98,'minimum_validation_answers_per_mode':20,'minimum_validation_groups':2,'old_38_all_consumed':True,'new_round3_sealed_accessed':False,'comparison':'Old features/trainer vs OCR-only shared context + dedup + source-weighted/calibration-negative guard, identical old labels/lines/source partitions.'},ensure_ascii=False,indent=2))
 return samples,records

def main():
 samples,records=prepare()
 old_features=module('round3_baseline_features',OUT/'baseline_field_model.py')
 baseline=module('round3_baseline_trainer',OUT/'baseline_train_field_model.py')
 for name in ['FIELDS','FEATURE_VERSION','artifact_key','calibrated_probabilities','features','parse_value','predict_artifact','valid_bbox']:
  setattr(baseline,name,getattr(old_features,name))
 enhanced_path=OUT/'expanded_v3/trainer_snapshot.py'
 enhanced=module('round3_enhanced_trainer',enhanced_path)
 enhanced.ROOT=PROJECT
 results={}
 import joblib
 for name,trainer in [('baseline',baseline),('enhanced',enhanced)]:
  report=trainer.train(deepcopy(samples),records,'shared','18.6',OUT/name)
  report.update(experiment='Round3 old38 consumed-development candidate experiment',independent_test_evidence=False,new_round3_sealed_accessed=False,
                input_annotations_sha256=sha(OUT/'annotations_consumed38.json'),ocr_raw_sha256={sid:r['raw_sha256']for sid,r in records.items()})
  if report.get('artifact'):
   artifact=joblib.load(report['artifact']);meta=json.load(open(report['metadata']))
   val=[dict(s,screen_type=s['inference_screen_type'])for s in samples if s['partition']=='validation']
   report['serving_context_validation_metrics']=trainer.evaluate_images(artifact,meta,val,records,report['thresholds'])
  (OUT/name/'training_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
  results[name]=report
 comparison={'scope':'All old38 consumed development; this is NOT a new unseen test.','same_labels_lines_partitions':True,'new_round3_sealed_accessed':False,'results':results,
             'feature_code_sha256':sha(PROJECT/'app/field_model.py'),'trainer_sha256':sha(enhanced_path),'trainer_snapshot':str(enhanced_path)}
 (OUT/'comparison.json').write_text(json.dumps(comparison,ensure_ascii=False,indent=2))
 for name,r in results.items():
  print(name,json.dumps({k:r.get(k)for k in ['status','deployable','n_training_rows','supervised_class_counts','thresholds','serving_context_validation_metrics','data_quality']},ensure_ascii=False))

if __name__=='__main__':main()
