#!/usr/bin/env python3
"""Anonymous downloads only; fixed revisions for the four local parsing models."""
import os
from pathlib import Path

os.environ['HF_HUB_DISABLE_IMPLICIT_TOKEN']='1'
os.environ['HF_HUB_DISABLE_XET']='1'
MODELS={
 'PP-DocLayout_plus-L':'aa52b8528c84f9b1a34ac3a88fe0e576edb9d11d',
 'PP-DocBlockLayout':'f270657da59d956ab69ffc2c4722fe1f557bf17b',
 'PP-OCRv5_server_det':'ca867c897ecbca8873081573a802ad70d499cb94',
 'PP-OCRv5_server_rec':'b26c3587fda8da3c8ec0ce357214b4d661ff1558',
}

if __name__=='__main__':
 from huggingface_hub import snapshot_download
 for name,revision in MODELS.items():
  snapshot_download('PaddlePaddle/'+name,revision=revision,token=False,
   local_dir=Path.home()/'.paddlex/official_models'/name,max_workers=2,
   allow_patterns=['inference.*','config.json'])
  print(name,revision)
