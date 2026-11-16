from pathlib import Path
import importlib.util
import sys
import tempfile
import json
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.card_tier_model import extract_suffix,glyph_features,predict_title


class CardTierCandidateTests(unittest.TestCase):
    def test_blank_or_invalid_title_abstains(self):
        self.assertIsNotNone(extract_suffix(np.zeros((32,200,3),np.uint8))[1])
        self.assertIsNotNone(extract_suffix(None)[1])

    def test_features_are_finite_fixed_length(self):
        a=np.zeros((20,6),np.uint8);a[:,2:4]=255
        b=np.zeros((40,20),np.uint8);b[:,3:6]=255;b[:,13:16]=255
        self.assertEqual(glyph_features(a).shape,glyph_features(b).shape)
        self.assertTrue(np.isfinite(glyph_features(a)).all())

    def test_training_rejects_sealed_data_before_image_loading(self):
        path=Path(__file__).resolve().parents[1]/'scripts/train_card_tier.py'
        spec=importlib.util.spec_from_file_location('train_card_tier',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/'bad.json';file.write_text(json.dumps({'samples':[{'evaluation_role':'sealed_test','split':'holdout'}]}))
            with self.assertRaises(ValueError):module.load_real(file)

    def test_reused_card_identity_is_purged_across_source_groups(self):
        path=Path(__file__).resolve().parents[1]/'scripts/train_card_tier.py'
        spec=importlib.util.spec_from_file_location('train_card_tier_split',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        rows=[{'id':'a','group':'sourceA','name':'卡 I'}, {'id':'b','group':'sourceA','name':'卡 II'},
              {'id':'c','group':'sourceB','name':'卡 I'}]
        train,validation,purged=module.split_real(rows,'sourceB')
        self.assertEqual([r['id'] for r in train],['b'])
        self.assertEqual([r['id'] for r in validation],['c'])
        self.assertEqual([r['id'] for r in purged],['a'])


if __name__=='__main__':unittest.main()
