"""CPU tests of persistence, validation, job lifecycle and HTTP contracts."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .core import ApiError, Service
from .settings import Settings


def wait_until(predicate, seconds=15):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(.05)
    raise AssertionError('Timed out')


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.config_file = root / 'deployment.json'
        self.config_file.write_text(json.dumps({'data_dir': 'data', 'robot_usd': 'robot.usd'}))
        self.settings = Settings(self.config_file)
        self.service = Service(self.settings)
        self.service._health_cache = {'status': 'ready'}
        self.fake = root / 'fake.py'
        self.fake.write_text('''import argparse,json,pathlib,time
p=argparse.ArgumentParser(); p.add_argument('--run_dir'); p.add_argument('--seed',type=int); a,unknown=p.parse_known_args()
d=pathlib.Path(a.run_dir)
print('first line',flush=True)
if a.seed==9: time.sleep(60)
if a.seed==8: raise RuntimeError('deliberate failure')
(d/'parameters.json').write_text((d/'input_parameters.json').read_text(encoding='utf-8'),encoding='utf-8')
(d/'verification.json').write_text(json.dumps({'passed':True,'measured_impulse_ns':1.6,'expected_impulse_ns':1.6}))
print('last line',flush=True)
''', encoding='utf-8')
        self.settings.script = self.fake

    def tearDown(self):
        self.service.close()
        self.temp.cleanup()

    def assert_error(self, status, callback):
        with self.assertRaises(ApiError) as context:
            callback()
        self.assertEqual(context.exception.status, status)

    def test_config_revision_validation_and_persistence(self):
        c = self.service.save_config({'name': '站立', 'parameters': self.service.defaults()})
        p = c['parameters']
        p['rewards']['orientation']['weight'] = -18
        newer = self.service.save_config({'name': c['name'], 'parameters': p, 'expected_revision': 1}, c['config_id'])
        self.assertEqual(newer['revision'], 2)
        self.assert_error(409, lambda: self.service.save_config({'name': c['name'], 'parameters': p, 'expected_revision': 1}, c['config_id']))
        p['rewards']['orientation']['scale'] = 0
        self.assert_error(422, lambda: self.service.validate(p))
        self.assertEqual(self.service.config(c['config_id'])['parameters']['rewards']['orientation']['scale'], 1)
        self.service.close()
        self.service = Service(self.settings)
        self.assertEqual(self.service.config(c['config_id'])['revision'], 2)

    def test_single_service_lock(self):
        with self.assertRaises(RuntimeError):
            Service(self.settings)

    def test_client_subnet_allowlist(self):
        import ipaddress
        self.settings.client_networks = [ipaddress.ip_network('192.168.2.0/24')]
        self.assertTrue(self.settings.allows_client('192.168.2.42'))
        self.assertTrue(self.settings.allows_client('::ffff:192.168.2.42'))
        self.assertFalse(self.settings.allows_client('192.168.3.42'))
        self.assertFalse(self.settings.allows_client('invalid'))

    def test_unknown_fields_and_nonfinite(self):
        p = self.service.defaults()
        p['robot']['height_m'] = float('nan')
        self.assert_error(422, lambda: self.service.validate(p))
        self.assert_error(422, lambda: self.service.start({'mode': 'verify', 'command': 'anything'}))
        self.assert_error(422, lambda: self.service.start({'mode': []}))

    def test_mode_constraints(self):
        for body in [{'mode': 'eval'}, {'mode': 'verify', 'num_envs': 3}, {'mode': 'pd', 'iterations': 1}, {'mode': 'eval', 'checkpoint': {'source_run_id': 1, 'artifact_id': 'x'}}, {'mode': 'pd', 'seconds': .031}, {'mode': 'train', 'num_envs': True}, {'mode': 'pd', 'video': True}, {'mode': 'train', 'config_revision': 1}]:
            self.assert_error(422, lambda b=body: self.service.start(b))

    def test_local_play_checkpoint_and_lifecycle(self):
        source = self.service.start({'mode': 'verify'})
        wait_until(lambda: self.service.run(source['run_id'])['status'] == 'succeeded')
        record = self.service._record(source['run_id'])
        record['mode'] = 'train'
        directory = self.service.directory(record)
        (directory / 'model_50.pt').write_bytes(b'checkpoint')
        artifact = next(a for a in self.service.artifacts(source['run_id'])['items'] if a['name'] == 'model_50.pt')
        checkpoint = {'source_run_id': source['run_id'], 'artifact_id': artifact['artifact_id']}
        self.assert_error(422, lambda: self.service.start({'mode': 'play'}))
        self.assert_error(422, lambda: self.service.start({'mode': 'play', 'checkpoint': checkpoint, 'num_envs': 2}))
        self.assert_error(422, lambda: self.service.start({'mode': 'play', 'checkpoint': checkpoint, 'video': True}))
        run = self.service.start({'mode': 'play', 'checkpoint': checkpoint, 'seed': 9, 'seconds': 60}, 'play-test')
        job = json.loads((self.service.directory(run) / 'worker_job.json').read_text())
        self.assertNotIn('--headless', job['command'])
        self.assertEqual(run['request']['num_envs'], 1)
        self.assertEqual(run['parameter_source'], 'checkpoint_snapshot')
        self.assertEqual(self.service.start({'mode': 'play', 'checkpoint': checkpoint, 'seed': 9, 'seconds': 60}, 'play-test')['run_id'], run['run_id'])
        self.assert_error(409, lambda: self.service.start({'mode': 'train'}))
        self.service.cancel(run['run_id'])
        wait_until(lambda: self.service.run(run['run_id'])['status'] == 'cancelled')

    def test_finished_job_result_logs_download(self):
        r = self.service.start({'mode': 'verify'})
        run_id = r['run_id']
        self.assert_error(409, lambda: self.service.result(run_id))
        wait_until(lambda: self.service.run(run_id)['status'] == 'succeeded')
        self.assertTrue(self.service.result(run_id)['metrics']['passed'])
        page1 = self.service.logs(run_id, limit=1)
        page2 = self.service.logs(run_id, cursor=page1['next_cursor'], limit=50)
        self.assertEqual(page1['items'][0]['sequence'], 0)
        self.assertTrue(page2['eof'])
        self.assert_error(400, lambda: self.service.logs(run_id, cursor='bad'))
        a = next(a for a in self.service.artifacts(run_id)['items'] if a['kind'] == 'parameters')
        path, _ = self.service.artifact_file(run_id, a['artifact_id'])
        self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['schema_version'], 1)
        self.assert_error(404, lambda: self.service.artifact_file(run_id, '../../worker_job.json'))
        self.assertFalse((path.parent / 'worker_job.json').exists())
        self.assert_error(409, lambda: self.service.cancel(run_id))

    def test_busy_cancellation_and_failure(self):
        r = self.service.start({'mode': 'verify', 'seed': 9})
        wait_until(lambda: self.service.run(r['run_id'])['status'] == 'running')
        self.assert_error(409, lambda: self.service.start({'mode': 'verify'}))
        self.service.cancel(r['run_id'])
        wait_until(lambda: self.service.run(r['run_id'])['status'] == 'cancelled')
        r2 = self.service.start({'mode': 'verify', 'seed': 8})
        wait_until(lambda: self.service.run(r2['run_id'])['status'] == 'failed')
        self.assert_error(409, lambda: self.service.result(r2['run_id']))

    def test_cursor_bound_to_run_and_filter(self):
        first = self.service.start({'mode': 'verify'})
        wait_until(lambda: self.service.run(first['run_id'])['status'] == 'succeeded')
        second = self.service.start({'mode': 'verify'})
        wait_until(lambda: self.service.run(second['run_id'])['status'] == 'succeeded')
        page = self.service.list_runs(limit=1)
        more = self.service.list_runs(limit=1, cursor=page['next_cursor'])
        self.assertNotEqual(page['items'][0]['run_id'], more['items'][0]['run_id'])
        self.assert_error(400, lambda: self.service.list_runs(cursor=page['next_cursor'], mode='train'))
        logs = self.service.logs(first['run_id'])
        self.assert_error(400, lambda: self.service.logs(second['run_id'], cursor=logs['next_cursor']))

    def test_checkpoint_import_and_missing_snapshot(self):
        src = Path(self.temp.name) / 'import'
        src.mkdir()
        (src / 'parameters.json').write_text(json.dumps(self.service.defaults()))
        (src / 'model_final.pt').write_bytes(b'not executed by import')
        r = self.service.import_run(src)
        a = next(a for a in self.service.artifacts(r['run_id'])['items'] if a['kind'] == 'checkpoint')
        (self.service.directory(r) / 'parameters.json').unlink()
        self.assert_error(422, lambda: self.service.start({'mode': 'eval', 'checkpoint': {'source_run_id': r['run_id'], 'artifact_id': a['artifact_id']}}))

    def test_idempotency_checksum_cleanup(self):
        body = {'mode': 'verify'}
        first = self.service.start(body, 'platform-job-1')
        second = self.service.start(body, 'platform-job-1')
        self.assertEqual(first['run_id'], second['run_id'])
        self.assert_error(409, lambda: self.service.start({'mode': 'verify', 'seed': 99}, 'platform-job-1'))
        wait_until(lambda: self.service.run(first['run_id'])['status'] == 'succeeded')
        artifact = next(a for a in self.service.artifacts(first['run_id'])['items'] if a['kind'] == 'verification')
        self.assertEqual(len(artifact['sha256']), 64)
        result = self.service.cleanup(first['run_id'], {'keep_kinds': ['parameters']})
        self.assertIn(artifact['artifact_id'], result['deleted_artifact_ids'])


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(cls.temp.name)
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0))
            port = s.getsockname()[1]
        config = root / 'deployment.json'
        config.write_text(json.dumps({'data_dir': 'data', 'robot_usd': 'missing.usd', 'port': port, 'allowed_client_ips': ['127.0.0.1'], 'api_token_env': 'RL_TEST_TOKEN'}))
        cls.base = f'http://127.0.0.1:{port}/api/v1'
        cls.log = (root / 'http.log').open('w')
        env = os.environ.copy(); env['RL_TEST_TOKEN'] = 'test-token'
        cls.proc = subprocess.Popen([sys.executable, '-m', 'integrations.rl_service', '--config', str(config), 'serve'], stdout=cls.log, stderr=cls.log, env=env)
        def ready():
            try:
                return cls.call('GET', '/standing/schema')[0] == 200
            except URLError:
                return False
        wait_until(ready)

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(timeout=10)
        cls.log.close()
        cls.temp.cleanup()

    @classmethod
    def call(cls, method, path, body=None, raw=None):
        data = raw if raw is not None else json.dumps(body).encode() if body is not None else None
        req = Request(cls.base + path, data=data, method=method, headers={'Content-Type': 'application/json', 'X-API-Key': 'test-token'})
        try:
            with urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read())
        except HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def test_defaults_validate_roundtrip_revision(self):
        status, d = self.call('GET', '/standing/defaults')
        self.assertEqual(status, 200)
        p = d['data']['parameters']
        self.assertEqual(self.call('POST', '/standing/validate', {'parameters': p})[0], 200)
        status, c = self.call('POST', '/standing/configs', {'name': 'HTTP站立', 'parameters': p})
        self.assertEqual(status, 201)
        config_id = c['data']['config_id']
        p['rewards']['orientation']['enabled'] = False
        status, updated = self.call('PUT', '/standing/configs/' + config_id, {'name': '已修改', 'parameters': p, 'expected_revision': 1})
        self.assertEqual(status, 200)
        self.assertFalse(updated['data']['parameters']['rewards']['orientation']['enabled'])
        self.assertEqual(self.call('PUT', '/standing/configs/' + config_id, {'name': 'old', 'parameters': p, 'expected_revision': 1})[0], 409)

    def test_error_envelope(self):
        for method, path, body, raw, expected in [('POST','/standing/validate',None,b'{',400), ('GET','/standing/runs/missing',None,None,404), ('GET','/standing/runs?limit=0',None,None,422), ('POST','/standing/runs',{'mode':'eval'},None,422), ('POST','/standing/validate',{'parameters':{}},None,422)]:
            status, payload = self.call(method, path, body, raw)
            self.assertEqual(status, expected)
            self.assertIn('request_id', payload)
            self.assertIn('details', payload['error'])

    def test_swagger_bootstrap_and_auth(self):
        root = self.base.removesuffix('/api/v1')
        with urlopen(root + '/docs') as response:
            page = response.read().decode('utf-8')
            self.assertIn('/docs-assets/swagger-ui-bundle.js', page)
            self.assertNotIn('cdn.jsdelivr.net', page)
        for asset in ('swagger-ui-bundle.js', 'swagger-ui.css', 'favicon.svg'):
            with urlopen(root + '/docs-assets/' + asset) as response:
                self.assertEqual(response.status, 200)
        with urlopen(self.base.removesuffix('/api/v1') + '/openapi.json') as response:
            self.assertEqual(response.status, 200)
        with self.assertRaises(HTTPError) as context:
            urlopen(self.base + '/standing/defaults')
        self.assertEqual(context.exception.code, 401)


if __name__ == '__main__':
    unittest.main()
