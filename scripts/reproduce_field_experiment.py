#!/usr/bin/env python3
"""Re-fit the inactive V4 field classifier from the exact real OCR records.

No source image is re-read, no sealed input is opened, no active model replaced.
The archived labels/boxes and OCR records can be audited with the screenshot
dataset separately. This reproduces consumed-development training, not a test.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'var/reproduced-field-v4')
    args=parser.parse_args()
    folder=ROOT/'training/round3'
    samples=json.loads((folder/'expanded_v4/annotations_consumed45.json').read_text())['samples']
    if len(samples)!=45 or any(s.get('evaluation_role')=='sealed_test'or s.get('sealed_test')is True for s in samples):
        raise ValueError('Only the fixed 45 consumed development inputs are accepted')
    records=json.loads((folder/'replay_records.json').read_text())['records']
    spec=importlib.util.spec_from_file_location('archived_v4_trainer',folder/'expanded_v4/trainer_snapshot.py')
    trainer=importlib.util.module_from_spec(spec);spec.loader.exec_module(trainer);trainer.ROOT=ROOT
    result=trainer.train(samples,records,'shared','18.6',args.output,target_precision=.98,min_validation_answers=20)
    assert result['deployable']is False
    original=json.loads((folder/'expanded_v4/model/training_report.json').read_text())
    result['reproduced_original_artifact_hash']=result['artifact_sha256']==original['artifact_sha256']
    result['input_records_sha256']=hashlib.sha256((folder/'replay_records.json').read_bytes()).hexdigest()
    (args.output/'reproduction_report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps({'deployable':False,'n_training_rows':result['n_training_rows'],
                      'validation':{k:result['validation_metrics'][k]for k in ['correct','wrong','abstain']},
                      'same_weight_hash':result['reproduced_original_artifact_hash']},ensure_ascii=False))


if __name__=='__main__':
    main()
