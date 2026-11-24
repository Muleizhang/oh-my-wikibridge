"""Offline syntax and semantic-role features; relation assembly lives in templates."""
from pathlib import Path
from .models import model_spec


class LocalLTP:
    model_id = 'LTP/small'
    revision = 'dea87bf0da3c5d054bbd426a78d7fa9efd347799'

    def __init__(self):
        import torch
        from ltp import LTP
        path = Path(model_spec('ltp')['path'])
        self.model = LTP(str(path), local_files_only=True, use_auth_token=False, strict=False)
        state = torch.load(path / 'pytorch_model.bin', map_location='cpu', weights_only=True)
        expected = set(self.model.model.state_dict())
        missing, extra = expected - set(state), set(state) - expected
        # Newer Transformers omits this deterministic, non-learned position buffer.
        if missing or extra - {'backbone.embeddings.position_ids'}:
            raise RuntimeError(f'LTP weight mismatch: missing={missing}, extra={extra}')
        for key in extra:
            values = state[key]
            if not torch.equal(values, torch.arange(values.shape[-1]).reshape(1, -1)):
                raise RuntimeError('Unexpected LTP position buffer')
        del state
        self.model.to('cuda' if torch.cuda.is_available() else 'cpu')

    def predict(self, text):
        output = self.model.pipeline([text], tasks=['cws', 'pos', 'srl', 'dep'])
        words, frames, dep = output.cws[0], output.srl[0], output.dep[0]
        offsets, cursor = [], 0
        for word in words:
            begin = text.index(word, cursor)
            offsets.append((begin, begin + len(word)))
            cursor = begin + len(word)
        events = []
        for frame in frames:
            arguments = [{'role': a[0], 'text': text[offsets[a[2]][0]:offsets[a[3]][1]]}
                         for a in frame['arguments']]
            events.append({'trigger': frame['predicate'], 'arguments': arguments, 'evidence': text,
                           'role_system': 'LTP PropBank labels; A0/A1 are not verified real-world roles'})
        return {'events': events,
                'raw': {'input': text, 'tokens': words, 'pos': output.pos[0], 'srl': frames, 'dep': dep}}
