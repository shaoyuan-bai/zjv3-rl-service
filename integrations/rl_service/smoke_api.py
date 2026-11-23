"""Opt-in real GPU smoke test against an already running API; not a quality benchmark."""
import argparse
import json
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--base', default='http://127.0.0.1:8000/api/v1')
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()

    def call(method, path, body=None):
        data = json.dumps(body).encode('utf-8') if body is not None else None
        req = Request(args.base + path, data=data, method=method, headers={'Content-Type': 'application/json'})
        try:
            with urlopen(req, timeout=60) as response:
                return json.load(response)['data']
        except HTTPError as exc:
            raise RuntimeError(exc.read().decode('utf-8')) from exc

    def finish(run_id):
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            r = call('GET', '/standing/runs/' + run_id)
            if r['status'] == 'succeeded':
                return call('GET', '/standing/runs/' + run_id + '/result')
            if r['status'] in ('failed', 'cancelled'):
                raise RuntimeError(json.dumps(r))
            time.sleep(1)
        raise TimeoutError(run_id)

    call('GET', '/health')
    parameters = call('GET', '/standing/defaults')['parameters']
    parameters['rewards']['orientation']['weight'] = -13
    parameters['rewards']['torque']['enabled'] = False
    call('POST', '/standing/validate', {'parameters': parameters})
    config = call('POST', '/standing/configs', {'name': 'HTTP integration smoke; not production training', 'parameters': parameters})
    training = call('POST', '/standing/runs', {'mode': 'train', 'config_id': config['config_id'], 'config_revision': config['revision'], 'num_envs': 8, 'iterations': 2, 'pushes': 'off'})
    print('TRAIN', training['run_id'], flush=True)
    training_result = finish(training['run_id'])
    assert training_result['metrics']['completed_iterations'] == 2
    artifacts = call('GET', '/standing/runs/' + training['run_id'] + '/artifacts')['items']
    snapshot = next(a for a in artifacts if a['kind'] == 'parameters')
    with urlopen(args.base + snapshot['download_url']) as response:
        actual = json.load(response)
    assert actual['rewards']['orientation']['weight'] == -13
    assert actual['rewards']['torque']['enabled'] is False
    assert actual['disturbance']['enabled'] is False
    checkpoint = training_result['metrics']['final_checkpoint_artifact_id']
    evaluation = call('POST', '/standing/runs', {'mode': 'eval', 'checkpoint': {'source_run_id': training['run_id'], 'artifact_id': checkpoint}, 'num_envs': 1, 'seconds': 2, 'pushes': 'off', 'video': True})
    print('EVAL', evaluation['run_id'], flush=True)
    evaluation_result = finish(evaluation['run_id'])
    videos = [a for a in call('GET', '/standing/runs/' + evaluation['run_id'] + '/artifacts')['items'] if a['kind'] == 'video' and a['ready']]
    assert len(videos) == 1 and videos[0]['size_bytes'] > 0
    report = {'passed': True, 'purpose': 'HTTP/config/train/export/checkpoint/eval/video integration; not a policy quality benchmark', 'training': training_result, 'evaluation': evaluation_result, 'parameters_snapshot_checked': True, 'video_download_ready': True}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('SMOKE_PASSED', args.output, flush=True)


if __name__ == '__main__':
    main()
