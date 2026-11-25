#!/usr/bin/env python3
"""Local dense/lexical retrieval and cross-encoder identity candidate reranking."""
import hashlib
import json
import os
import time
from collections import defaultdict

from kg_v2.common import OUT, ident, load, save
from kg_v2.models import model_spec
from kg_v2.identity import NORMALIZATION_VERSION, build_identity_review, lexical_candidate_index

CANDIDATE_POLICY_VERSION = 'sparse-name-buckets-v2-bounded-profiles'


def profile(entity, attributes):
    values = '；'.join(f"{s['label']}={s['object']['raw']}" for s in attributes.get(entity['id'], []))
    return f"名称：{entity['label']}。类型候选：{entity['kind']}。{values}。原文：{entity.get('description', entity['evidence'][0]['text'])[:180]}"


def main():
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_IMPLICIT_TOKEN='1')
    import numpy as np
    import torch
    from transformers import AutoModel, AutoModelForSequenceClassification, AutoTokenizer
    torch.set_num_threads(4)
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    started = time.perf_counter()
    graph = load(OUT / 'graph.json'); entities = graph['entities']; attributes = defaultdict(list)
    for s in graph['assertions']:
        if s['object']['kind'] == 'quantity': attributes[s['subject']].append(s)
    descriptions = [profile(e, attributes) for e in entities]
    encoder = model_spec('embedding')
    reranker = model_spec('reranker')
    signature = hashlib.sha256(json.dumps([descriptions, encoder['revision'], reranker['revision'],
                                         NORMALIZATION_VERSION, CANDIDATE_POLICY_VERSION], ensure_ascii=False).encode()).hexdigest()
    cache = OUT / 'identity-scores.json'
    previous = load(cache) if cache.exists() else None
    if previous and previous['signature'] == signature:
        proposals = previous['proposals']
    else:
        tokenizer = AutoTokenizer.from_pretrained(encoder['path'], local_files_only=True)
        model = AutoModel.from_pretrained(encoder['path'], use_safetensors=True, local_files_only=True).eval().to(device)
        embeddings = []
        for start in range(0, len(descriptions), 24):
            inputs = tokenizer(descriptions[start:start+24], padding=True, truncation=True, max_length=256, return_tensors='pt')
            with torch.inference_mode():
                hidden = model(**{k: v.to(device) for k, v in inputs.items()}).last_hidden_state[:, 0]
                embeddings.append(torch.nn.functional.normalize(hidden, dim=1).cpu().numpy())
        vectors = np.concatenate(embeddings)
        del model; torch.cuda.empty_cache()
        pairs = {}; lexical = lexical_candidate_index(entities)
        nearest = []
        count = min(5, len(entities) - 1)
        for start in range(0, len(entities), 256):
            similarity = vectors[start:start+256] @ vectors.T
            for offset, row in enumerate(similarity):
                row[start+offset] = -np.inf
                nearest.append(np.argpartition(row, -count)[-count:] if count else [])
        for i, entity in enumerate(entities):
            for j in set(map(int, nearest[i])) | lexical[i]:
                key = tuple(sorted((i, j)))
                pairs[key] = {'id': ident('identity', entities[key[0]]['id'], entities[key[1]]['id']),
                    'left': entities[key[0]]['id'], 'right': entities[key[1]]['id'],
                    'cosineSimilarity': round(float(vectors[i] @ vectors[j]), 4),
                    'nameMatch': entity['label'] == entities[j]['label'],
                    'typeAgreement': entity['kind'] == entities[j]['kind'],
                    'decision': 'review_required', 'automaticallyMerged': False}
        keys = list(pairs)
        print(f'Reranking {len(keys)} candidate pairs for {len(entities)} source entities', flush=True)
        tokenizer = AutoTokenizer.from_pretrained(reranker['path'], local_files_only=True)
        model = AutoModelForSequenceClassification.from_pretrained(reranker['path'], use_safetensors=True,
                    local_files_only=True).eval().to(device)
        for start in range(0, len(keys), 16):
            group = keys[start:start+16]
            inputs = tokenizer([[descriptions[i], descriptions[j]] for i, j in group],
                               padding=True, truncation='longest_first', max_length=512, return_tensors='pt')
            with torch.inference_mode():
                scores = model(**{k: v.to(device) for k, v in inputs.items()}).logits.flatten().cpu().tolist()
            for pair, score in zip(group, scores):
                pairs[pair]['rerankerLogit'] = round(score, 4)
            if start % 1600 == 0: print(f'Reranked {min(start+16,len(keys))}/{len(keys)}', flush=True)
        proposals = sorted(pairs.values(), key=lambda x: -x['rerankerLogit'])
        save(cache, {'signature': signature, 'proposals': proposals, 'models': [encoder, reranker]})
    graph['identityProposals'] = proposals
    graph['identityReview'] = build_identity_review(graph)
    adjacent = defaultdict(list)
    for proposal in proposals:
        adjacent[proposal['left']].append(proposal['id']); adjacent[proposal['right']].append(proposal['id'])
    graph['identityDecisions'] = [{'entityId': e['id'], 'decision': 'source_record' if e['kind'] == 'artifact' else 'unresolved',
        'reason': '保留书内条目身份，跨条目身份尚未确认' if e['kind'] == 'artifact' else '候选已检索和重排，尚无经校准的自动匹配规则',
        'candidateIds': adjacent[e['id']][:5]} for e in entities]
    graph['summary']['identityProposals'] = len(proposals)
    graph['summary']['automaticIdentityMerges'] = 0
    graph['linking'] = {'models': [encoder['model'], reranker['model']],
        'candidateGeneration': 'dense top-5 plus indexed sparse normalized-name candidates; large name buckets use representative anchors',
        'scoreMeaning': 'retrieval relevance logit, not calibrated identity probability',
        'profileLimits': 'encoder 256 tokens, paired reranker 512 tokens; model profiles only, original evidence unchanged',
        'automaticMerging': False, 'reason': 'No independently labeled identity validation set',
        'wallSeconds': round(time.perf_counter() - started, 3), 'cached': bool(previous and previous['signature'] == signature)}
    save(OUT / 'graph.json', graph); save(OUT / 'summary.json', graph['summary'])
    save(OUT / 'linking-run.json', graph['linking'])
    print('Identity candidates ranked:', len(proposals), '; no uncalibrated automatic merges', flush=True)


if __name__ == '__main__':
    main()
