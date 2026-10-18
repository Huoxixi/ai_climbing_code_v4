"""Compare uncached public reads with the optimized store using synthetic jobs."""
import argparse
import json
import statistics
import tempfile
import time
from pathlib import Path

from core.climb_replay import ClimbReplayStore, _atomic_json


def median_ms(function, repeats=12):
    samples = []
    for _ in range(repeats):
        started = time.perf_counter()
        function()
        samples.append((time.perf_counter() - started) * 1000)
    return round(statistics.median(samples), 3)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as directory:
        store = ClimbReplayStore(Path(directory))
        poses = [{'source_frame_id': i * 3, 'time_seconds': i / 10,
                  'kpts_xy': [[.2 + j / 100, .4 + j / 100] for j in range(17)],
                  'kpts_score': [.9] * 17} for i in range(600)]
        result = {'pose_samples': poses, 'attempt': {'contacts': [], 'segments': []}}
        for index in range(20):
            ident = f'job{index}'
            _atomic_json(store._path(ident), {'id': ident, 'owner': 'owner',
                'created_at': f'2026-10-09T00:00:{index:02d}', 'status': 'succeeded',
                'result': result, 'automatic_result': result, 'input_path': 'private-synthetic-path'})
        def original_get():
            return store._public(store._read('job0'))
        def original_list():
            jobs = [store._public(json.loads(path.read_text('utf-8')))
                    for path in store.jobs.glob('*/job.json')]
            return sorted(jobs, key=lambda job: job['created_at'], reverse=True)
        started = time.perf_counter()
        cold = store.list('owner')
        cold_ms = (time.perf_counter() - started) * 1000
        assert cold == original_list()
        assert store.get('job0', 'owner') == original_get()
        report = {'data': 'constructed; 20 jobs; 600 poses/job; no model inference',
            'scope': 'store reads and public projection; excludes HTTP transfer and inference',
            'repeats': 12, 'cold_list_ms': round(cold_ms, 3),
            'uncached_get_ms': median_ms(original_get),
            'cached_get_ms': median_ms(lambda: store.get('job0', 'owner')),
            'uncached_list_ms': median_ms(original_list),
            'cached_list_ms': median_ms(lambda: store.list('owner')),
            'cache_bytes': store._public_cache_bytes,
            'identical_public_results': True}
        for operation in ('get', 'list'):
            report[f'{operation}_speedup'] = round(report[f'uncached_{operation}_ms'] / report[f'cached_{operation}_ms'], 2)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
        print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
