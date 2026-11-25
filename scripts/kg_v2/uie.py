"""Offline Chinese UIE span extraction adapter."""
import os
from pathlib import Path

os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                  HF_HUB_DISABLE_TELEMETRY='1', TOKENIZERS_PARALLELISM='false')
MODEL_ID = 'Casually/uie-base'
REVISION = '10ffc2501d5d23ccb58d54f92a586a5aeff57f57'


def default_model_dir():
    from .models import model_spec
    path = Path(model_spec('uie')['path'])
    if not path.is_dir():
        raise RuntimeError('UIE weights are not cached locally: ' + str(path))
    return path


class UIE:
    def __init__(self, model_dir=None, device=None, threshold=0.5):
        import torch
        from transformers import AutoTokenizer, ErnieConfig, ErnieModel, ErniePreTrainedModel

        class SpanModel(ErniePreTrainedModel):
            def __init__(self, config):
                super().__init__(config)
                self.encoder = ErnieModel(config)
                self.linear_start = torch.nn.Linear(config.hidden_size, 1)
                self.linear_end = torch.nn.Linear(config.hidden_size, 1)
                self.post_init()

            def forward(self, input_ids, attention_mask, token_type_ids):
                hidden = self.encoder(input_ids=input_ids, attention_mask=attention_mask,
                                      token_type_ids=token_type_ids).last_hidden_state
                return self.linear_start(hidden).squeeze(-1).sigmoid(), self.linear_end(hidden).squeeze(-1).sigmoid()

        path = Path(model_dir) if model_dir else default_model_dir()
        self.device = device or ('cuda' if torch.cuda.is_available() else 'cpu')
        if not 0 < threshold < 1:
            raise ValueError('threshold must be between 0 and 1')
        self.threshold = threshold
        config = ErnieConfig.from_pretrained(path, local_files_only=True)
        self.model, info = SpanModel.from_pretrained(path, config=config, local_files_only=True,
                                use_safetensors=True, output_loading_info=True)
        if info.get('missing_keys') or info.get('unexpected_keys') or info.get('mismatched_keys'):
            raise RuntimeError('UIE weights did not load exactly: ' + repr(info))
        self.model.eval().to(self.device)
        self.tokenizer = AutoTokenizer.from_pretrained(path, use_fast=True, local_files_only=True,
                                                       trust_remote_code=False)
        self.parameters = sum(p.numel() for p in self.model.parameters())
    def query(self, text, prompts):
        return self.query_pairs([(text, prompt) for prompt in prompts])

    def query_pairs(self, pairs, batch_size=16):
        """Batch independent (text, prompt) pairs, retaining each text's offsets."""
        import torch
        answers = []
        for offset in range(0, len(pairs), batch_size):
            batch = pairs[offset:offset + batch_size]
            inputs = self.tokenizer([prompt for text, prompt in batch], [text for text, prompt in batch], padding=True, truncation=False,
                                    return_offsets_mapping=True, return_tensors='pt')
            if inputs['input_ids'].shape[1] > 512:
                raise ValueError('UIE prompt plus text exceeds 512 tokens; split the text first.')
            spans = inputs.pop('offset_mapping').tolist()
            sequence_ids = [inputs.sequence_ids(i) for i in range(len(batch))]
            with torch.inference_mode():
                starts, ends = self.model(**{k: v.to(self.device) for k, v in inputs.items()})
            starts, ends = starts.cpu().tolist(), ends.cpu().tolist()
            for row in range(len(batch)):
                text = batch[row][0]
                candidates = [j for j, p in enumerate(starts[row]) if p > self.threshold and sequence_ids[row][j] == 1]
                stops = [j for j, p in enumerate(ends[row]) if p > self.threshold and sequence_ids[row][j] == 1]
                # UIE pairs each eligible end with the nearest preceding predicted start.
                span_pairs = {}
                a = b = 0
                while a < len(candidates) and b < len(stops):
                    left, right = candidates[a], stops[b]
                    if left <= right:
                        span_pairs[right] = left
                        a += 1
                        if left == right:
                            b += 1
                    else:
                        b += 1
                found = []
                for right, left in span_pairs.items():
                    begin, end = spans[row][left][0], spans[row][right][1]
                    if end > begin:
                        found.append({'text': text[begin:end], 'start': begin, 'end': end,
                                      'score': starts[row][left] * ends[row][right]})
                answers.append(found)
        return answers
