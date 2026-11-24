#!/usr/bin/env python3
"""Download all pinned public NLP weights anonymously; inference stays offline."""
import os
from kg_v2.models import MODELS

os.environ['HF_HUB_DISABLE_IMPLICIT_TOKEN'] = '1'
os.environ['HF_HUB_DISABLE_XET'] = '1'

if __name__ == '__main__':
    from huggingface_hub import snapshot_download
    for role, (repo, revision, patterns) in MODELS.items():
        path = snapshot_download(repo, revision=revision, token=False, max_workers=2,
                                 allow_patterns=patterns)
        print(role, path)
