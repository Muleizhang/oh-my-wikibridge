#!/usr/bin/env python3
"""Run the gated 20-page typed pipeline; preserve the v1 baseline."""
import os
import subprocess
import sys
import time
from pathlib import Path

from kg_v2.common import OUT, ROOT, save


if __name__ == '__main__':
    started=time.perf_counter()
    nlp=os.environ.get('WIKIBRIDGE_LTP_PYTHON','/tmp/wikibridge-openie-env/bin/python')
    layout=os.environ.get('WIKIBRIDGE_LAYOUT_PYTHON','/tmp/wikibridge-layout-env/bin/python')
    for binary in [nlp,layout]:
        if not Path(binary).is_file(): raise SystemExit(f'Missing local environment: {binary}. See docs/kg-pipeline-v2/README.md')
    stages=[(layout,'kg_v2_layout.py'),(nlp,'kg_v2_extract.py'),(sys.executable,'kg_v2_build.py'),
            (nlp,'kg_v2_link.py'),(sys.executable,'kg_v2_evaluate.py'),
            (sys.executable,'kg_v2_validate.py'),(sys.executable,'kg_v2_store.py')]
    for python,script in stages:
        subprocess.run(['unshare','-n',python,str(ROOT/'scripts'/script)],check=True)
    save(OUT/'pipeline-run.json',{'state':'candidate_workflow_complete','pages':20,
        'wallSeconds':round(time.perf_counter()-started,3),'automaticAcceptance':False,
        'network':'disabled during inference','entry':'http://localhost:1420/?view=localgraph'})
    print('Typed workflow complete: http://localhost:1420/?view=localgraph')
