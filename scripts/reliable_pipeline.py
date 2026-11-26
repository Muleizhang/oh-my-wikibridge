#!/usr/bin/env python3
"""Run the selected pages through the offline candidate pipeline."""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

from kg_v2.common import OUT, ROOT, save, selected_pages


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--skip-layout', action='store_true', help='Use already completed layout caches')
    parser.add_argument('--no-network-namespace', action='store_true',
                        help='Use offline model settings without Linux unshare')
    args = parser.parse_args()
    started = time.perf_counter()
    nlp = os.environ.get('WIKIBRIDGE_LTP_PYTHON', sys.executable)
    layout = os.environ.get('WIKIBRIDGE_LAYOUT_PYTHON', sys.executable)
    stages = [] if args.skip_layout else [(layout, 'kg_v2_layout.py')]
    stages += [(nlp, 'kg_v2_extract.py'), (sys.executable, 'kg_v2_build.py'),
               (nlp, 'kg_v2_link.py'), (sys.executable, 'kg_v2_evaluate.py'),
               (sys.executable, 'kg_v2_validate.py'), (sys.executable, 'kg_v2_store.py')]
    for binary in {binary for binary, _ in stages}:
        if not Path(binary).is_file():
            raise SystemExit(f'Missing local environment: {binary}. See docs/reliable-pipeline.md')
    isolation = [] if args.no_network_namespace else ['unshare', '-n', '--']
    network = 'unshare -n' if isolation else 'offline model settings'
    offline = dict(os.environ, HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                   WIKIBRIDGE_KG_NETWORK_MODE=network)
    for python, script in stages:
        subprocess.run([*isolation, python, str(ROOT/'scripts'/script)], env=offline, check=True)
    save(OUT/'pipeline-run.json',{'state':'candidate_workflow_complete','pages':len(selected_pages()),
        'layoutIncludedInWallTime': not args.skip_layout,
        'wallSeconds':round(time.perf_counter()-started,3),'automaticAcceptance':False,
        'network':'disabled during inference' if isolation else network,
        'entry':'http://localhost:1420/?view=localgraph'})
    print('Typed workflow complete: http://localhost:1420/?view=localgraph')
