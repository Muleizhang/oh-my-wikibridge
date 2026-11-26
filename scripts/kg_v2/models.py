"""Pinned public NLP weights; model loading never downloads implicitly."""
import os
from pathlib import Path

MODELS = {
    'gliner': ('urchade/gliner_multi-v2.1', '443d26d654e0324125a96bebd8e796c14ff2efe6',
               ['gliner_config.json', 'model.safetensors']),
    'gliner_encoder': ('microsoft/mdeberta-v3-base', 'a0484667b22365f84929a935b5e50a51f71f159d',
                       ['config.json', 'tokenizer_config.json', 'spm.model']),
    'uie': ('Casually/uie-base', '10ffc2501d5d23ccb58d54f92a586a5aeff57f57',
            ['*.json', '*.safetensors', 'vocab.txt']),
    'ltp': ('LTP/small', 'dea87bf0da3c5d054bbd426a78d7fa9efd347799',
            ['*.json', 'pytorch_model.bin', 'vocab.txt']),
    'embedding': ('BAAI/bge-small-zh-v1.5', '7999e1d3359715c523056ef9478215996d62a620',
                  ['*.json', 'model.safetensors', 'vocab.txt']),
    'reranker': ('BAAI/bge-reranker-base', '2cfc18c9415c912f9d8155881c133215df768a70',
                 ['*.json', 'model.safetensors', 'sentencepiece.bpe.model']),
}


def model_spec(role):
    model, revision, _ = MODELS[role]
    cache = Path(os.environ.get('HF_HUB_CACHE', Path(os.environ.get('HF_HOME', Path.home() / '.cache/huggingface')) / 'hub'))
    path = cache / ('models--' + model.replace('/', '--')) / 'snapshots' / revision
    if not path.is_dir():
        raise RuntimeError(f'Missing local {role} weights. Run scripts/download_kg_v2_models.py first.')
    return {'model': model, 'revision': revision, 'path': str(path)}
