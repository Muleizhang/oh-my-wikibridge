"""Token and sentence windows with offsets preserved."""
import re


def token_windows(text, tokenizer, size=192, overlap=48):
    """Cover all characters without silently truncating long pages."""
    if not 0 <= overlap < size <= 220:
        raise ValueError('Require 0 <= overlap < window size <= 220 tokens')
    if not text:
        return []
    offsets = tokenizer(text, add_special_tokens=False, return_offsets_mapping=True,
                        truncation=False)['offset_mapping']
    if not offsets:
        return [{'start': 0, 'end': len(text), 'text': text, 'token_count': 0}]
    windows = []
    cursor = 0
    while cursor < len(offsets):
        stop = min(cursor + size, len(offsets))
        begin = 0 if cursor == 0 else offsets[cursor][0]
        end = len(text) if stop == len(offsets) else offsets[stop - 1][1]
        windows.append({'start': begin, 'end': end, 'text': text[begin:end], 'token_count': stop - cursor})
        if stop == len(offsets):
            break
        cursor = stop - overlap
    covered = 0
    for window in windows:
        if window['start'] > covered:
            raise ValueError('Tokenizer left a gap between extraction windows')
        covered = max(covered, window['end'])
    if covered != len(text):
        raise ValueError('Extraction windows do not cover the full page')
    return windows


def windows(text, size=210, overlap=40):
    """Parse each sentence separately; LTP expects sentences, not paragraphs."""
    for sentence in re.finditer(r'[^。！？；!?;]+[。！？；!?;]*|[。！？；!?;]+', text):
        start, stop = sentence.span()
        while start < stop:
            end = min(stop, start + size)
            yield start, end
            if end == stop:
                break
            start = end - overlap
