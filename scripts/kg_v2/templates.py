"""Chinese surface and dependency templates for open relation candidates.

Templates preserve raw predicates and evidence; they are not a trained relation classifier.
It uses syntactic dependencies, never the old A0/A1 pair assembler or an NER list.
"""
import re

CATALOG = [
    {'id': 'C75_CLASS', 'slides': [75], 'pattern': 'NP 是/为 [一种/一类/...之一] NP',
     'purpose': 'Explicit category/member construction; retain the source predicate.'},
    {'id': 'C80_SVO', 'slides': [80, 82], 'pattern': 'NP_subject —SBV→ V ←VOB— NP_object',
     'purpose': 'Lexical predicate with syntactic subject and nominal object.'},
    {'id': 'C80_PROPERTY', 'slides': [80, 82], 'pattern': 'NP_owner 的 NP_property V NP_value; NP_topic，NP_property V NP_value',
     'purpose': 'Keep the property name in the relation expression and bind its value to the owner/topic.'},
    {'id': 'C80_PREPOSITION', 'slides': [80], 'pattern': 'NP V Prep NP; Prep NP，V NP',
     'purpose': 'Retain prepositional arguments and distinguish location/source/manner roles.'},
    {'id': 'C80_RELATIVE', 'slides': [80, 82], 'pattern': 'NP1 V 的 NP2',
     'purpose': 'Recover the nominal head in an attributive clause as an argument; retain textual direction.'},
    {'id': 'C83_NAME', 'slides': [83], 'pattern': 'NP (又/亦/也/习) 称/叫/称为 NP',
     'purpose': 'Chinese lexical/syntactic naming pattern; requires an identifiable subject.'},
]

BREAKS = set('，,。；;！？!?：:')
MODAL = {'可能', '可以', '能够', '会', '应当', '应该', '似', '似乎', '大概', '或许'}
NEGATIVE = {'不', '未', '没有', '无', '不见', '未见', '并非', '不是', '未曾'}
QUANTIFIERS = {'有些', '有的', '大多', '多数', '少数', '一般', '部分', '全部', '都'}
NAMING = {'称', '称为', '称作', '叫', '叫作'}
FUNCTIONAL = {'是', '为', '有', '到', '来', '去', '加'} | MODAL | NEGATIVE
NOMINAL_POS = {'n', 'nh', 'ni', 'nl', 'ns', 'nz', 'nt', 'nd', 'r', 'q', 'm', 'a', 'b', 'z'}
PROPERTY_VERBS = {'有', '具有', '包括', '包含', '采用', '使用', '含有', '具备', '组成', '构成'}
NOUN_POS = {'n', 'nh', 'ni', 'nl', 'ns', 'nz'}


class TemplateExtractor:
    def __init__(self, text, parsed):
        self.text = text
        self.words, self.pos = parsed['tokens'], parsed['pos']
        self.parent = [p - 1 for p in parsed['dep']['head']]
        self.labels = parsed['dep']['label']
        self.children = [[] for _ in self.words]
        self.offsets, cursor = [], 0
        for i, word in enumerate(self.words):
            start = text.index(word, cursor)
            self.offsets.append((start, start + len(word))); cursor = start + len(word)
            if self.parent[i] >= 0:
                self.children[self.parent[i]].append(i)
        self.facts, self.events, self.filtered = [], [], []

    def clause(self, index):
        begin, end = index, index + 1
        while begin > 0 and self.words[begin - 1] not in BREAKS:
            begin -= 1
        while end < len(self.words) and self.words[end] not in BREAKS:
            end += 1
        return begin, end

    def segment(self, begin, end):
        if begin >= end:
            return None
        return (self.offsets[begin][0], self.offsets[end - 1][1])

    def value(self, region):
        return self.text[region[0]:region[1]] if region else ''

    def nominal(self, head, exclude=None, coordinate=True):
        """Expand a nominal head locally, without swallowing relative clauses."""
        left, right = self.clause(head)
        selected, todo = {head}, [head]
        while todo:
            node = todo.pop()
            for child in self.children[node]:
                if child in selected or child == exclude or not left <= child < right:
                    continue
                label = self.labels[child]
                allowed = label in {'ATT', 'RAD', 'LAD'} or coordinate and label == 'COO'
                if node == head and self.pos[head].startswith('v') and label == 'VOB':
                    allowed = True  # Nominalized verbal item in an enumeration.
                if not allowed or self.pos[child].startswith('v') and label == 'ATT' and any(
                        self.labels[k] == 'SBV' or self.words[k] == '的' for k in self.children[child]):
                    continue
                selected.add(child); todo.append(child)
        return self.segment(min(selected), max(selected) + 1)

    def subjects(self, predicate):
        visited, node = set(), predicate
        while node >= 0 and node not in visited:
            visited.add(node)
            subjects = [i for i in self.children[node] if self.labels[i] == 'SBV' and self.pos[i] in NOMINAL_POS]
            if subjects:
                result = []
                for i in subjects:
                    region = self.nominal(i)
                    between = self.text[region[1]:self.offsets[predicate][0]]
                    if node != predicate and sum(c in BREAKS for c in between) > 1:
                        continue
                    result.append((region, node != predicate))
                return result
            parent = self.parent[node]
            if self.labels[node] == 'COO' or self.labels[node] == 'VOB' and parent >= 0 and (
                    self.words[parent] in FUNCTIONAL or self.words[node] in NAMING and self.words[parent] == '习'):
                node = parent
            else:
                break
        return []

    def objects(self, predicate):
        return [i for i in self.children[predicate] if self.labels[i] == 'VOB' and
                (self.pos[i] in NOMINAL_POS or self.pos[i].startswith('v') and
                 any(self.labels[k] == 'COO' for k in self.children[i]))]

    def verb_region(self, predicate):
        start, end = predicate, predicate + 1
        if self.words[predicate] in NAMING:
            while start > 0 and self.words[start - 1] in {'亦', '也', '又', '习'}:
                start -= 1
        for child in self.children[predicate]:
            if child == end and self.labels[child] == 'CMP' and self.words[child] in {'到', '于'}:
                end += 1
        return self.segment(start, end)

    def qualifiers(self, predicate):
        nodes, node = {predicate}, predicate
        # Inherited negation/modality on a governing auxiliary remains attached.
        while self.parent[node] >= 0 and self.labels[node] == 'VOB' and self.words[self.parent[node]] in FUNCTIONAL:
            node = self.parent[node]; nodes.add(node)
        found = []
        for node in nodes:
            candidates = [node] + self.children[node]
            for child in candidates:
                if child != node and self.labels[child] not in {'ADV', 'ATT'}:
                    continue
                word = self.words[child]
                if word in NEGATIVE:
                    found.append({'role': '否定', 'text': word})
                elif word in MODAL:
                    found.append({'role': '可能性', 'text': word})
                elif word in QUANTIFIERS:
                    found.append({'role': '范围', 'text': word})
                elif self.labels[child] == 'ADV' and (self.pos[child] == 'nt' or self.pos[child] == 'nd' and
                        any(self.pos[k] == 'nt' for k in self.children[child])):
                    found.append({'role': '时间语境', 'text': self.value(self.nominal(child))})
        # Preserve attribution when the clause is the complement of a reporting verb.
        node, visited = predicate, set()
        while node >= 0 and node not in visited:
            visited.add(node)
            if self.words[node] in {'认为', '指出', '推测', '记载', '表明'}:
                for subject, _ in self.subjects(node):
                    found.append({'role': '观点来源', 'text': self.value(subject)})
            node = self.parent[node]
        return list({(x['role'], x['text']): x for x in found if x['text']}.values())

    def emit(self, subject, predicate_region, obj, predicate_index, template, inherited=False, extra=None):
        if not subject or not obj or not predicate_region:
            return
        s, p, o = map(self.value, (subject, predicate_region, obj))
        reason = None
        if not s or not o or s == o:
            reason = 'empty or self pair'
        elif not re.search(r'[\u3400-\u9fffA-Za-z0-9]', s + o):
            reason = 'nonlexical arguments'
        elif max(len(s), len(o)) > 100:
            reason = 'argument exceeds 100 characters'
        if reason:
            self.filtered.append({'subject': s, 'predicate': p, 'object': o, 'template': template, 'reason': reason})
            return
        qualifiers = self.qualifiers(predicate_index) + (extra or [])
        qualifiers = list({(q['role'], q['text']): q for q in qualifiers}.values())
        self.facts.append({'subject': s, 'predicate': p, 'object': o, 'evidence': self.text,
            'qualifiers': qualifiers, 'template_id': template,
            'template_spans': {'subject': list(subject), 'predicate': list(predicate_region), 'object': list(obj)},
            'inherited_subject': inherited, 'needs_coreference': s in {'它', '其', '有的', '有些', '上', '上面', '这种'},
            'derivation': 'course-template:' + template})

    def property_owner(self, subject, predicate):
        """NP 的 property, or an explicit nominal topic before a comma."""
        start, end = subject
        if any(c in BREAKS for c in self.text[end:self.offsets[predicate][0]]):
            return None
        de = self.text.rfind('的', start, end)
        if de > start:
            owner = (start, de)
            owner_tokens = [i for i, (a, b) in enumerate(self.offsets) if start <= a and b <= de]
            if any(self.pos[i] in NOUN_POS for i in owner_tokens) and not any(self.pos[i].startswith('v') for i in owner_tokens):
                attribute = (de + 1, self.offsets[predicate][1])
                return owner, attribute
        clause_left, _ = self.clause(predicate)
        if clause_left > 0 and self.words[clause_left - 1] in {'，', ','}:
            previous_end = clause_left - 1
            previous_left, _ = self.clause(previous_end - 1)
            heads = [i for i in range(previous_left, previous_end) if self.pos[i] in NOUN_POS and
                     (self.parent[i] >= previous_end or self.parent[i] < previous_left)]
            if heads:
                topic = self.nominal(heads[-1])
                if topic[1] < subject[0]:
                    return topic, (subject[0], self.offsets[predicate][1])
        return None

    def run(self):
        for predicate, pos in enumerate(self.pos):
            if not pos.startswith('v') or self.words[predicate] in MODAL | NEGATIVE:
                continue
            parent = self.parent[predicate]
            if self.labels[predicate] == 'COO' and parent >= 0 and self.labels[parent] == 'VOB':
                continue  # A verbal item inside an object list is not a new clause.
            subjects, objects = self.subjects(predicate), self.objects(predicate)
            verb = self.verb_region(predicate)
            for subject, inherited in subjects:
                for obj_head in objects:
                    obj = self.nominal(obj_head)
                    template = 'C83_NAME' if self.words[predicate] in NAMING else 'C80_SVO'
                    if self.words[predicate] in {'是', '为'} and re.search(r'一种|一类|之一', self.value(obj)):
                        template = 'C75_CLASS'
                    owner = self.property_owner(subject, predicate) if not inherited and self.words[predicate] in PROPERTY_VERBS else None
                    if owner:
                        self.emit(owner[0], owner[1], obj, predicate, 'C80_PROPERTY', inherited)
                    else:
                        self.emit(subject, verb, obj, predicate, template, inherited)
                for prep in self.children[predicate]:
                    if self.pos[prep] != 'p' or self.labels[prep] not in {'ADV', 'CMP'}:
                        continue
                    for target in self.children[prep]:
                        if self.labels[target] == 'POB' and self.pos[target] in NOMINAL_POS:
                            role = '来源/方向' if self.words[prep] in {'从', '由', '向'} else '介词限定'
                            self.emit(subject, verb, self.nominal(target), predicate, 'C80_PREPOSITION', inherited,
                                      [{'role': role, 'text': self.value(self.segment(prep, target + 1))}])
            # NP1 V 的 NP2: use the outer nominal head, not the complete relative clause.
            head = self.parent[predicate]
            if self.labels[predicate] == 'ATT' and head >= 0 and self.pos[head].startswith('n'):
                if any(self.words[c] == '的' for c in self.children[predicate]):
                    for subject, inherited in subjects:
                        self.emit(subject, verb, self.nominal(head, exclude=predicate), predicate, 'C80_RELATIVE', inherited)
            # A leading prepositional phrase may describe an event with no explicit subject.
            if not subjects and objects:
                preps = [c for c in self.children[predicate] if self.pos[c] == 'p' and self.words[c] in {'在', '于'}]
                for prep in preps:
                    targets = [c for c in self.children[prep] if self.labels[c] == 'POB']
                    for target in targets:
                        for obj_head in objects:
                            self.emit(self.nominal(obj_head), verb, self.nominal(target), predicate, 'C80_PREPOSITION',
                                      extra=[{'role': '地点', 'text': self.value(self.nominal(target))}])
            if not subjects and objects and self.qualifiers(predicate):
                # Retain incomplete frames instead of inventing a cross-clause subject.
                arguments = [{'role': '宾语（主语未解）', 'text': self.value(self.nominal(i))} for i in objects]
                arguments += self.qualifiers(predicate)
                self.events.append({'trigger': self.value(verb), 'arguments': arguments, 'evidence': self.text,
                                    'incomplete_subject': True})
        # Conservative, exact-structure duplicate removal; no semantic merging.
        unique = {}
        for fact in self.facts:
            key = (tuple(fact['template_spans']['subject']), fact['predicate'], tuple(fact['template_spans']['object']),
                   tuple((q['role'], q['text']) for q in fact['qualifiers']))
            unique.setdefault(key, fact)
        return {'facts': list(unique.values()), 'events': self.events, 'filtered': self.filtered,
                'raw': {'input': self.text, 'template_catalog': CATALOG,
                        'note': 'Chinese adaptation of course templates. No bootstrapping or learned relation classifier in this stage.'}}
