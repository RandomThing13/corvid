"""Public pure scoring/payload helpers extracted from the original evaluator.
Private evaluation runners, data and labels are intentionally omitted.
"""
def normalize(value, unit):
    factors = {'m2': ('area', 1), 'm²': ('area', 1), 'sqm': ('area', 1), 'cm2': ('area', 0.0001), 'm': ('length', 1), 'cm': ('length', 0.01), 'mm': ('length', 0.001), 'm3': ('volume', 1), 'm³': ('volume', 1), 'count': ('count', 1), '': ('count', 1)}
    dimension, factor = factors.get(str(unit or '').lower(), ('unknown', 1))
    return (float(value) * factor, dimension)

def score(result, gold, kind, unit):
    try:
        value = result.get('value')
        if kind == 'text':
            return None
        if kind == 'count':
            return result.get('unit') == 'count' and isinstance(value, (int, float)) and (value >= 0) and float(value).is_integer() and (value == float(gold))
        actual, dim = normalize(value, result.get('unit'))
        expected, gdim = normalize(gold, unit)
        expected_dim = {'area': 'area', 'volume': 'volume', 'length': 'length'}[kind]
        if gdim == 'count' and (not unit):
            gdim = expected_dim
        return dim == gdim == expected_dim and (actual == 0 if expected == 0 else abs(actual - expected) <= 0.02 * abs(expected))
    except (TypeError, ValueError, KeyError, AttributeError):
        return False

def outbound(document_id, question, model, mode='direct_vlm'):
    return {'document_ids': [document_id], 'question': question, 'mode': mode, 'runtime_model': model, 'use_cache': False}
