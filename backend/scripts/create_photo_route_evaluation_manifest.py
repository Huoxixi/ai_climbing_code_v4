"""Create a non-destructive validation/holdout annotation manifest skeleton."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def create_manifest(output: Path, validation: list[Path], holdout: list[Path]) -> dict:
    output = Path(output).resolve()
    root = output.parent
    if len(validation) < 3 or len(holdout) < 2 or len(validation) + len(holdout) > 10:
        raise ValueError('需要至少 3 张验证照片和 2 张留出照片，总数不超过 10 张')
    samples = []
    seen = set()
    for split, paths in (('validation', validation), ('holdout', holdout)):
        for supplied in paths:
            path = Path(supplied).resolve()
            if not path.is_relative_to(root) or not path.is_file():
                raise ValueError('照片必须位于清单目录内；脚本不会复制或移动照片')
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest in seen:
                raise ValueError('验证集和留出集不能包含重复照片')
            seen.add(digest)
            samples.append({
                'image': path.relative_to(root).as_posix(),
                'image_sha256': digest,
                'split': split,
                'scene_id': None,
                'source_id': None,
                'human_reviewed': False,
                'complete': False,
                'model_training_overlap': None if split == 'holdout' else False,
                'algorithm_tuning_overlap': None if split == 'holdout' else False,
                'objects': [],
            })
    manifest = {'schema_version': 2, 'samples': samples}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8') as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--validation', type=Path, nargs='+', required=True)
    parser.add_argument('--holdout', type=Path, nargs='+', required=True)
    args = parser.parse_args()
    result = create_manifest(args.output, args.validation, args.holdout)
    counts = {split: sum(sample['split'] == split for sample in result['samples'])
              for split in ('validation', 'holdout')}
    print(json.dumps({'created': True, **counts}, ensure_ascii=False))


if __name__ == '__main__':
    main()
