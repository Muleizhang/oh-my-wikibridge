#!/usr/bin/env python3
import argparse
import hashlib
from pathlib import Path

from kg_v2.common import OUT, load, save, selected_pages
from kg_v2.contracts import publication_gate
from kg_v2.evaluation import score_quantities


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--reference', help='Source-specific annotated quantity reference')
    args = parser.parse_args()
    reference_path = Path(args.reference) if args.reference else OUT / 'development-reference.json'
    reference = load(reference_path) if args.reference or reference_path.exists() else None
    if reference is not None and not args.reference:
        digest = hashlib.sha256(reference_path.read_bytes()).hexdigest()
        if digest != (OUT / 'development-reference.sha256').read_text().strip():
            raise ValueError('Frozen development reference changed')
    graph = load(OUT / 'graph.json')
    graph['coverage'] = load(OUT / 'extraction-run.json').get('coverage', {})
    pages = selected_pages()
    quantity = {}
    if reference is not None:
        baseline_records = [r for p in pages for r in load(OUT / f'extractions/v1-p{p:04d}.json')['baselineRecords']]
        quantity = {
            'tesseract_same_record_parser': score_quantities(reference, load(OUT / 'baseline-quantity-assertions.json'), baseline_records),
            'ppstructure_same_record_parser': score_quantities(reference, graph['assertions'], graph['records'])}
    results = {'referenceAuthority': reference['authority'] if reference else 'not_available_for_this_source',
        'quantity': quantity,
        'quantityStatus': 'development_diagnostic' if reference else 'not_measured',
        'quantityNote': 'No annotated reference for this source; references from other volumes are not reused.' if not reference else reference.get('purpose', ''),
        'identity': {'status': 'not_measured', 'reason': 'Needs independent same/different/unknown identity references'},
        'relations': {'status': 'not_measured', 'reason': 'Needs complete independently annotated relation and qualifier references'},
        'reservedPagesEvaluated': False,
        'previouslyReservedPagesProcessed': sorted(set(pages).intersection(range(101, 111))) if reference else [],
        'heldoutNote': 'Any previously reserved pages included in this run are now processed; they are not an untouched test set.' if reference else 'No held-out reference is available for this source.'}
    results['publication'] = publication_gate({})  # Quantity-only development checks cannot open the full KG gate.
    graph['evaluation'] = results
    graph['publication'] = results['publication']
    save(OUT / 'evaluation.json', results)
    save(OUT / 'graph.json', graph)
    for name, row in results['quantity'].items():
        print(name, {key: row[key] for key in ['truePositive', 'falsePositive', 'falseNegative', 'precision', 'recall']})


if __name__ == '__main__':
    main()
