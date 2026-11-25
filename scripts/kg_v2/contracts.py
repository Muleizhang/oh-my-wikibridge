"""Typed assertions, evidence and publication gates shared by stages/tests."""
from .values import FIELD_LABELS

RELATIONS = {
    'artifact_type': {'label': '器类', 'subject': ['artifact'], 'object': ['artifact_type']},
    'decorated_with': {'label': '饰有纹样', 'subject': ['artifact', 'artifact_type'], 'object': ['motif']},
    'made_of': {'label': '材质', 'subject': ['artifact', 'artifact_type'], 'object': ['material']},
    'decorated_with_material': {'label': '装饰材料', 'subject': ['artifact'], 'object': ['decoration_material']},
    'has_shape': {'label': '造型', 'subject': ['artifact'], 'object': ['shape']},
    'uses_technique': {'label': '采用工艺', 'subject': ['artifact', 'artifact_type'], 'object': ['technique']},
    'period': {'label': '所属时代', 'subject': ['artifact', 'artifact_type', 'culture'], 'object': ['period']},
    'alias': {'label': '别名', 'subject': ['motif', 'technique', 'culture', 'artifact_type'], 'object': ['same_type']},
    'discovered_at': {'label': '发现地点', 'subject': ['artifact'], 'object': ['place']},
    'excavated_at': {'label': '出土地点', 'subject': ['artifact'], 'object': ['place']},
    'collected_at': {'label': '采集地点', 'subject': ['artifact'], 'object': ['place']},
    'held_by': {'label': '收藏单位', 'subject': ['artifact'], 'object': ['organization']},
    'belongs_to_culture': {'label': '文化归属', 'subject': ['artifact'], 'object': ['culture']},
    'has_composition': {'label': '构图形式', 'subject': ['artifact'], 'object': ['composition']},
    'decorated_part': {'label': '装饰部位', 'subject': ['artifact'], 'object': ['decoration_part']},
    'decoration_role': {'label': '装饰角色', 'subject': ['artifact'], 'object': ['decoration_role']},
    'distributed_in': {'label': '分布地区', 'subject': ['culture', 'motif'], 'object': ['place']},
}


def statement_issues(statement, entities):
    issues = []
    subject = statement.get('subject')
    if not subject or subject not in entities:
        issues.append('unresolved_subject')
    if not statement.get('evidence'):
        issues.append('missing_evidence')
    obj = statement['object']; predicate = statement['predicate']
    if obj['kind'] == 'quantity':
        dimension = 'mass' if predicate == 'weight' else 'length'
        if predicate not in FIELD_LABELS or obj['dimension'] != dimension:
            issues.append('quantity_dimension_mismatch')
        if subject in entities and entities[subject]['kind'] != 'artifact':
            issues.append('quantity_owner_not_artifact')
    elif obj['kind'] == 'entity':
        target = entities.get(obj['id'])
        if not target:
            issues.append('unresolved_object')
        spec = RELATIONS.get(predicate)
        if spec and subject in entities and target:
            if entities[subject]['kind'] not in spec['subject']:
                issues.append('relation_subject_type')
            allowed = [entities[subject]['kind']] if spec['object'] == ['same_type'] else spec['object']
            if target['kind'] not in allowed:
                issues.append('relation_object_type')
    elif obj['kind'] not in {'time', 'text', 'event', 'unresolved'}:
        issues.append('unknown_value_kind')
    if obj['kind'] == 'unresolved':
        issues.append('unresolved_object')
    if predicate.startswith('open:'):
        issues.append('relation_definition_pending')
    return sorted(set(issues))


def publication_gate(evaluation):
    reasons = []
    if evaluation.get('referenceAuthority') != 'independent_human':
        reasons.append('缺少独立人工参考集')
    for key, target in [('factPrecisionLower95', .95), ('mergePrecisionLower95', .99)]:
        if evaluation.get(key) is None or evaluation[key] < target:
            reasons.append(f'{key} 未达到 {target:.0%}')
    if not evaluation.get('coverageMeasured'):
        reasons.append('尚未测量召回与拒绝覆盖率')
    return {'automaticAcceptance': not reasons, 'reasons': reasons,
            'targets': {'factPrecision': .95, 'mergePrecision': .99}}
