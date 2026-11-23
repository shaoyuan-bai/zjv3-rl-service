"""Persistent, single-job service. No simulator imports in the API process."""
from copy import deepcopy
from datetime import datetime, timezone
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import uuid

import jsonschema
import psutil

ACTIVE = {'starting', 'running', 'cancelling'}
TERMINAL = {'succeeded', 'failed', 'cancelled'}
MODES = {'train', 'eval', 'pd', 'verify', 'play'}


def now():
    return datetime.now(timezone.utc).isoformat()


def uid(prefix):
    return prefix + '_' + uuid.uuid4().hex


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    os.replace(temporary, path)


class ApiError(Exception):
    def __init__(self, status, code, message, details=None):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message
        self.details = details or []


def invalid(message, path=''):
    raise ApiError(422, 'VALIDATION_ERROR', message, [{'path': path, 'message': message}])


def keys(body, allowed, required=()):
    if not isinstance(body, dict):
        invalid('请求体必须是对象')
    if set(body) - set(allowed):
        invalid('未知字段: ' + ', '.join(sorted(set(body) - set(allowed))))
    for key in required:
        if key not in body:
            invalid('缺少字段: ' + key, '/' + key)


class Service:
    def __init__(self, settings, acquire_lock=True):
        self.settings = settings
        settings.data.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.handle = None
        if acquire_lock:
            self.handle = (settings.data / 'service.lock').open('a+b')
            self.handle.seek(0)
            self.handle.write(b'0')
            self.handle.flush()
            self.handle.seek(0)
            try:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                self.handle.close()
                raise RuntimeError('Another API/import process owns this data directory')
        self.state_file = settings.data / 'state.json'
        self.state = json.loads(self.state_file.read_text(encoding='utf-8')) if self.state_file.exists() else {'configs': {}, 'runs': {}, 'idempotency': {}}
        self.state.setdefault('idempotency', {})
        self.thread = None
        self.proc = None
        self.closed = False
        for r in self.state['runs'].values():
            if r['status'] in ACTIVE:
                r.update(status='failed', finished_at=now(), error={'code': 'SERVICE_INTERRUPTED', 'message': '服务中断，任务未恢复；请从已完成检查点另建续训任务'})
        self._save()
        spec = importlib.util.spec_from_file_location('rl_stand_settings', settings.task / 'stand_settings.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.validate_fn = module.validate_settings
        self._health_cache = None

    def _save(self):
        atomic_json(self.state_file, self.state)

    def defaults(self):
        return json.loads((self.settings.task / 'stand_parameters.json').read_text(encoding='utf-8'))

    def schema(self):
        schema = json.loads((self.settings.task / 'stand_parameters.schema.json').read_text(encoding='utf-8'))
        schema['$schema'] = 'https://json-schema.org/draft/2020-12/schema'
        return {'schema_version': 1, 'schema': schema, 'cross_field_rules': ['所有数字必须有限', '四组外力区间下界≤上界', 'minimum_height_m < height_m < spawn_height_m+0.1']}

    def validate(self, parameters):
        try:
            self.validate_fn(parameters)
        except jsonschema.ValidationError as exc:
            path = '/' + '/'.join(str(p).replace('~', '~0').replace('/', '~1') for p in exc.absolute_path)
            invalid(exc.message, path)
        except (ValueError, TypeError) as exc:
            invalid(str(exc))
        return parameters

    def config(self, config_id):
        with self.lock:
            if config_id not in self.state['configs']:
                raise ApiError(404, 'NOT_FOUND', '配置不存在')
            return deepcopy(self.state['configs'][config_id])

    def save_config(self, body, config_id=None):
        keys(body, ['name', 'parameters'] + (['expected_revision'] if config_id else []), ['name', 'parameters'] + (['expected_revision'] if config_id else []))
        name = body['name']
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
            invalid('name长度必须为1–100', '/name')
        self.validate(body['parameters'])
        with self.lock:
            if config_id:
                old = self.config(config_id)
                if type(body['expected_revision']) is not int or body['expected_revision'] != old['revision']:
                    raise ApiError(409, 'REVISION_CONFLICT', '配置修订号不一致，请重新读取')
            else:
                old = {'config_id': uid('cfg'), 'revision': 0, 'created_at': now()}
            old.update(name=name.strip(), parameters=deepcopy(body['parameters']), revision=old['revision'] + 1, updated_at=now())
            self.state['configs'][old['config_id']] = old
            self._save()
            return deepcopy(old)

    def health(self, refresh=False):
        with self.lock:
            if self._health_cache is None or refresh:
                code = "import importlib.util,json,torch; print('RL_PROBE '+json.dumps({'python_available':True,'isaacsim_available':bool(importlib.util.find_spec('isaacsim')) and bool(importlib.util.find_spec('isaaclab')),'cuda_available':torch.cuda.is_available(),'gpu_name':torch.cuda.get_device_name(" + self.settings.device[5:] + ") if torch.cuda.is_available() else None}))"
                result = {'python_available': self.settings.python.is_file(), 'isaacsim_available': False, 'cuda_available': False, 'gpu_name': None}
                try:
                    probe = subprocess.run([str(self.settings.python), '-c', code], env=self.settings.environment(), capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=45, cwd=self.settings.project)
                    line = next(x[9:] for x in probe.stdout.splitlines() if x.startswith('RL_PROBE '))
                    result.update(json.loads(line))
                    result['message'] = None
                except (OSError, subprocess.TimeoutExpired, StopIteration, ValueError) as exc:
                    result['message'] = '运行环境探测失败：' + type(exc).__name__
                if not self.settings.usd.is_file():
                    result['message'] = '机器人资产缺失，请配置robot_usd'
                result['status'] = 'ready' if all(result[x] for x in ('python_available', 'isaacsim_available', 'cuda_available')) and self.settings.usd.is_file() else 'unavailable'
                result['task_id'] = 'Isaac-ZJV3-Stand-v0'
                self._health_cache = result
            result = deepcopy(self._health_cache)
            result['active_run_id'] = next((r['run_id'] for r in self.state['runs'].values() if r['status'] in ACTIVE), None)
            return result

    def _record(self, run_id):
        if run_id not in self.state['runs']:
            raise ApiError(404, 'NOT_FOUND', '任务不存在')
        return self.state['runs'][run_id]

    def directory(self, record):
        return self.settings.data / 'runs' / record['run_id']

    def run(self, run_id):
        with self.lock:
            record = self._record(run_id)
            self._scan(record)
            progress = self.directory(record) / 'progress.json'
            if progress.exists():
                try:
                    values = json.loads(progress.read_text(encoding='utf-8'))
                    record['progress'].update({k: v for k, v in values.items() if k in ('current_iteration', 'simulation_time_s')})
                except (OSError, ValueError):
                    pass
            r = deepcopy(record)
            r.pop('artifacts', None)
            r['run_directory'] = str(self.directory(r))
            return r

    def list_runs(self, limit=20, cursor=None, mode=None, status=None):
        if mode is not None and mode not in MODES:
            invalid('非法mode')
        if status is not None and status not in ACTIVE | TERMINAL:
            invalid('非法status')
        with self.lock:
            runs = sorted([r for r in self.state['runs'].values() if (not mode or r['mode'] == mode) and (not status or r['status'] == status)], key=lambda r: (r['created_at'], r['run_id']), reverse=True)
            if cursor:
                try:
                    c = json.loads(base64.urlsafe_b64decode(cursor.encode()))
                    if c['mode'] != mode or c['status'] != status:
                        raise ValueError()
                    runs = [r for r in runs if (r['created_at'], r['run_id']) < tuple(c['after'])]
                except (ValueError, KeyError, TypeError):
                    raise ApiError(400, 'BAD_REQUEST', '游标无效或筛选条件变化')
            page = runs[:limit]
            next_cursor = base64.urlsafe_b64encode(json.dumps({'after': [page[-1]['created_at'], page[-1]['run_id']], 'mode': mode, 'status': status}).encode()).decode() if len(runs) > limit else None
            return {'items': [self.run(r['run_id']) for r in page], 'next_cursor': next_cursor}

    def artifact_file(self, run_id, artifact_id):
        with self.lock:
            record = self._record(run_id)
            self._scan(record)
            a = next((a for a in record.get('artifacts', []) if a['artifact_id'] == artifact_id), None)
            if a is None:
                raise ApiError(404, 'NOT_FOUND', '产物不存在或不属于该任务')
            if not a['ready']:
                raise ApiError(409, 'RUN_NOT_READY', '产物尚未写入完成')
            path = (self.directory(record) / a['name']).resolve()
            if not path.is_relative_to(self.directory(record).resolve()) or not path.is_file():
                raise ApiError(404, 'NOT_FOUND', '产物文件缺失')
            return path, deepcopy(a)

    def start(self, body, idempotency_key=None):
        allowed = ['mode', 'config_id', 'config_revision', 'checkpoint', 'num_envs', 'iterations', 'seconds', 'pushes', 'seed', 'video', 'diagnostics']
        keys(body, allowed, ['mode'])
        request_hash = hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        if idempotency_key is not None:
            if not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key) <= 128:
                invalid('Idempotency-Key必须是1–128字符', '/headers/Idempotency-Key')
            old = self.state['idempotency'].get(idempotency_key)
            if old:
                if old['request_hash'] != request_hash:
                    raise ApiError(409, 'IDEMPOTENCY_CONFLICT', '同一Idempotency-Key对应了不同请求')
                return self.run(old['run_id'])
        mode = body['mode']
        if not isinstance(mode, str) or mode not in MODES:
            invalid('非法mode', '/mode')
        request = dict(body)
        for key, value in {'config_id': None, 'config_revision': None, 'checkpoint': None, 'num_envs': 128 if mode == 'train' else 2 if mode == 'verify' else 1 if mode == 'play' else 32, 'pushes': 'off' if mode == 'verify' else 'full', 'seed': 42, 'video': False, 'diagnostics': False}.items():
            request.setdefault(key, value)
        if mode == 'train':
            request.setdefault('iterations', 300)
        elif mode in ('eval', 'pd', 'play'):
            request.setdefault('seconds', 300 if mode == 'play' else 20)
        for key, low, high in [('num_envs', 1, 256), ('seed', 0, 2147483647), ('iterations', 1, 100000)]:
            if key in request and (type(request[key]) is not int or not low <= request[key] <= high):
                invalid('非法整数范围', '/' + key)
        if 'seconds' in request and (type(request['seconds']) not in (int, float) or not .02 <= request['seconds'] <= 3600 or abs(request['seconds'] / .02 - round(request['seconds'] / .02)) > 1e-6):
            invalid('seconds必须在[0.02,3600]内且为0.02的整数倍', '/seconds')
        if (mode != 'train' and 'iterations' in request) or (mode not in ('eval', 'pd', 'play') and 'seconds' in request):
            invalid('该模式不接受iterations或seconds')
        if not isinstance(request['pushes'], str) or request['pushes'] not in ('off', 'mild', 'full'):
            invalid('非法pushes', '/pushes')
        if mode == 'play' and request['num_envs'] != 1:
            invalid('play要求num_envs=1', '/num_envs')
        if mode == 'verify' and (request['pushes'] != 'off' or request['num_envs'] != 2):
            invalid('verify要求num_envs=2且pushes=off')
        for field in ('video', 'diagnostics'):
            if type(request[field]) is not bool:
                invalid('必须是boolean', '/' + field)
        if request['video'] and (mode not in ('eval', 'pd') or request['num_envs'] != 1):
            invalid('视频仅支持eval/pd且num_envs=1', '/video')
        checkpoint = request['checkpoint']
        if mode in ('eval', 'play') and not checkpoint:
            invalid('eval/play必须指定checkpoint', '/checkpoint')
        if checkpoint and mode not in ('train', 'eval', 'play'):
            invalid('该模式不接受checkpoint', '/checkpoint')
        with self.lock:
            if self.closed or any(r['status'] in ACTIVE for r in self.state['runs'].values()):
                raise ApiError(409, 'RESOURCE_BUSY', '已有活动任务或服务正在关闭')
            ckpt = None
            if checkpoint is not None:
                keys(checkpoint, ['source_run_id', 'artifact_id'], ['source_run_id', 'artifact_id'])
                if not all(isinstance(checkpoint[k], str) for k in checkpoint):
                    invalid('检查点ID必须是字符串')
                ckpt, artifact = self.artifact_file(checkpoint['source_run_id'], checkpoint['artifact_id'])
                if artifact['kind'] != 'checkpoint':
                    invalid('必须使用训练检查点，不能使用推理模型', '/checkpoint')
            config_id = request['config_id']
            revision = request['config_revision']
            if config_id is not None:
                if not isinstance(config_id, str):
                    invalid('config_id必须是字符串')
                c = self.config(config_id)
                if type(revision) is not int:
                    invalid('config_revision为必填整数')
                if revision != c['revision']:
                    raise ApiError(409, 'REVISION_CONFLICT', '配置版本不一致')
                parameters, source = c['parameters'], 'config'
            elif revision is not None:
                invalid('config_revision不能单独出现')
            elif ckpt:
                snapshot = ckpt.parent / 'parameters.json'
                if not snapshot.exists():
                    invalid('检查点快照缺失，请显式指定配置')
                parameters, source = json.loads(snapshot.read_text(encoding='utf-8')), 'checkpoint_snapshot'
            else:
                parameters, source = self.defaults(), 'defaults'
            self.validate(parameters)
            h = self.health()
            if h['status'] != 'ready':
                raise ApiError(503, 'SIMULATOR_UNAVAILABLE', h['message'] or 'CUDA/Isaac Sim不可用')
            r = {'run_id': uid('run'), 'mode': mode, 'status': 'starting', 'created_at': now(), 'started_at': None, 'finished_at': None, 'exit_code': None, 'config_id': config_id, 'config_revision': revision, 'parameter_source': source, 'parameters_artifact_id': None, 'request': request, 'progress': {'current_iteration': None, 'target_iterations': request.get('iterations'), 'simulation_time_s': None, 'target_seconds': request.get('seconds')}, 'error': None, 'artifacts': []}
            directory = self.directory(r)
            directory.mkdir(parents=True, exist_ok=False)
            atomic_json(directory / 'input_parameters.json', parameters)
            if mode == 'play':
                # Keep playback independent of source-artifact cleanup/replacement.
                local_checkpoint = directory / 'playback_checkpoint.pt'
                shutil.copy2(ckpt, local_checkpoint)
                ckpt = local_checkpoint
            cmd = [str(self.settings.python), '-u', str(self.settings.script), '--mode', mode, '--config', str(directory / 'input_parameters.json'), '--run_dir', str(directory), '--num_envs', str(request['num_envs']), '--pushes', request['pushes'], '--seed', str(request['seed']), '--device', self.settings.device]
            if mode != 'play':
                cmd += ['--headless']
            for key in ('iterations', 'seconds'):
                if key in request:
                    cmd += ['--' + key, str(request[key])]
            for key in ('video', 'diagnostics'):
                if request[key]:
                    cmd += ['--' + key]
            if ckpt:
                cmd += ['--checkpoint', str(ckpt)]
            job_env = self.settings.environment()
            overrides = {k: job_env[k] for k in ('PYTHONPATH', 'ZJV3_USD_PATH', 'ZJV3_RUNS_DIR', 'WARP_CACHE_PATH', 'PYTHONUNBUFFERED', 'PYTHONIOENCODING')}
            job = {'command': cmd, 'cwd': str(self.settings.project), 'env': overrides, 'owner_pid': os.getpid(), 'owner_start': psutil.Process().create_time(), 'cancel_file': str(directory / 'cancel.request')}
            # Internal job contains host-specific paths; never expose/download/bundle it.
            atomic_json(directory / 'worker_job.json', job)
            self.state['runs'][r['run_id']] = r
            if idempotency_key is not None:
                self.state['idempotency'][idempotency_key] = {'request_hash': request_hash, 'run_id': r['run_id'], 'created_at': now()}
            self._save()
            self.thread = threading.Thread(target=self._execute, args=(r['run_id'],), daemon=True)
            self.thread.start()
            return self.run(r['run_id'])

    def restart(self, run_id):
        """Create a new run from the last completed checkpoint; no in-place mutation."""
        with self.lock:
            old = self._record(run_id)
            if old['status'] in ACTIVE:
                raise ApiError(409, 'INVALID_STATE', '活动任务不能重启，请先取消')
            self._scan(old)
            checkpoint = next((a for a in old['artifacts'] if a['kind'] == 'checkpoint' and a['name'] == 'model_final.pt' and a['ready']), None)
            if checkpoint is None:
                raise ApiError(409, 'RUN_NOT_READY', '任务没有可用于重启的完整检查点')
            request = deepcopy(old['request'])
            request.pop('imported', None)
            if old['mode'] in ('train', 'eval', 'play'):
                request['checkpoint'] = {'source_run_id': run_id, 'artifact_id': checkpoint['artifact_id']}
            else:
                request.pop('checkpoint', None)
            request.pop('config_id', None)
            request.pop('config_revision', None)
            request['mode'] = 'train' if old['mode'] == 'train' else old['mode']
        return self.start(request)

    def _execute(self, run_id):
        with self.lock:
            r = self._record(run_id)
            directory = self.directory(r)
        try:
            with (directory / 'service.log').open('ab', buffering=0) as log:
                proc = subprocess.Popen([sys.executable, str(Path(__file__).with_name('worker.py')), str(directory / 'worker_job.json')], cwd=self.settings.project, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                with self.lock:
                    self.proc = proc
                    r['started_at'] = now()
                    if r['status'] != 'cancelling':
                        r['status'] = 'running'
                    self._save()
                code = proc.wait()
            with self.lock:
                r['exit_code'] = code
                r['finished_at'] = now()
                if r['status'] == 'cancelling':
                    r['status'] = 'cancelled'
                elif code != 0:
                    r.update(status='failed', error={'code': 'SIMULATION_FAILED', 'message': '子进程异常退出，请查看日志'})
                else:
                    required = 'model_final.pt' if r['mode'] == 'train' else 'verification.json' if r['mode'] == 'verify' else 'evaluation.json'
                    if not (directory / required).is_file():
                        r.update(status='failed', error={'code': 'OUTPUT_MISSING', 'message': '进程退出但缺少预期结果'})
                    else:
                        r['status'] = 'succeeded'
                        if r['mode'] == 'train':
                            r['progress']['current_iteration'] = r['request']['iterations']
                self._scan(r)
                (directory / 'worker_job.json').unlink(missing_ok=True)
                self._save()
        except Exception as exc:
            with self.lock:
                r.update(status='failed', finished_at=now(), error={'code': 'LAUNCH_FAILED', 'message': str(exc)})
                self._save()
        finally:
            with self.lock:
                self.proc = None

    def cancel(self, run_id):
        with self.lock:
            r = self._record(run_id)
            if r['status'] not in ACTIVE:
                raise ApiError(409, 'INVALID_STATE', '终态任务不能取消')
            r['status'] = 'cancelling'
            (self.directory(r) / 'cancel.request').touch()
            self._save()
            return self.run(run_id)

    def close(self):
        with self.lock:
            self.closed = True
            for r in self.state['runs'].values():
                if r['status'] in ACTIVE:
                    self.cancel(r['run_id'])
        if self.thread:
            self.thread.join(timeout=20)
            if self.thread.is_alive():
                # Keep the ownership lock until worker shutdown; do not allow a second GPU job.
                raise RuntimeError('Worker still stopping; ownership lock retained until process exit')
        if self.handle:
            self.handle.close()
            self.handle = None

    def _scan(self, r):
        directory = self.directory(r)
        result = []
        names = {'parameters.json': 'parameters', 'policy_io.json': 'policy_io', 'env.yaml': 'environment', 'agent.yaml': 'agent', 'evaluation.json': 'evaluation', 'verification.json': 'verification', 'export_verification.json': 'export_verification', 'export_error.txt': 'export_error', 'standing.mp4': 'video', 'service.log': 'log', 'exported/policy.pt': 'torchscript', 'exported/policy.onnx': 'onnx'}
        names.update({p.name: 'checkpoint' for p in directory.glob('model_*.pt')})
        for name, kind in names.items():
            path = directory / name
            if not path.is_file() or path.is_symlink():
                continue
            artifact_id = 'art_' + hashlib.sha256(name.encode()).hexdigest()[:20]
            # Conservative: no files downloadable until the simulation has exited.
            ready = r['status'] in TERMINAL and (kind != 'video' or r['status'] == 'succeeded')
            with path.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            result.append({'artifact_id': artifact_id, 'name': name, 'kind': kind, 'content_type': 'application/json' if name.endswith('.json') else 'application/yaml' if name.endswith('.yaml') else 'video/mp4' if name.endswith('.mp4') else 'text/plain; charset=utf-8' if name.endswith(('.txt', '.log')) else 'application/octet-stream', 'size_bytes': path.stat().st_size, 'sha256': digest, 'ready': ready, 'download_url': f'/standing/runs/{r["run_id"]}/artifacts/{artifact_id}/download' if ready else None})
        r['artifacts'] = result
        r['parameters_artifact_id'] = next((x['artifact_id'] for x in result if x['kind'] == 'parameters'), None)

    def artifacts(self, run_id):
        with self.lock:
            r = self._record(run_id)
            self._scan(r)
            return {'items': deepcopy(r['artifacts'])}

    def cleanup(self, run_id, body):
        keys(body, ['artifact_ids', 'keep_kinds'], [])
        if 'artifact_ids' in body and not isinstance(body['artifact_ids'], list):
            invalid('artifact_ids必须是数组')
        if 'keep_kinds' in body and not isinstance(body['keep_kinds'], list):
            invalid('keep_kinds必须是数组')
        with self.lock:
            r = self._record(run_id)
            if r['status'] in ACTIVE:
                raise ApiError(409, 'INVALID_STATE', '活动任务不能清理产物')
            self._scan(r)
            selected = set(body.get('artifact_ids', []))
            keep = set(body.get('keep_kinds', []))
            deleted = []
            for a in list(r['artifacts']):
                if selected and a['artifact_id'] not in selected:
                    continue
                if a['kind'] in keep:
                    continue
                path = (self.directory(r) / a['name']).resolve()
                if path.is_file() and path.is_relative_to(self.directory(r).resolve()):
                    path.unlink()
                    deleted.append(a['artifact_id'])
            self._scan(r)
            self._save()
            return {'run_id': run_id, 'deleted_artifact_ids': deleted, 'remaining_artifacts': deepcopy(r['artifacts'])}

    def logs(self, run_id, cursor=None, limit=200):
        with self.lock:
            r = self._record(run_id)
            directory = self.directory(r)
            offset, sequence = 0, 0
            if cursor:
                try:
                    c = json.loads(base64.urlsafe_b64decode(cursor.encode()))
                    if c['run_id'] != run_id or type(c['offset']) is not int or type(c['sequence']) is not int or min(c['offset'], c['sequence']) < 0:
                        raise ValueError()
                    offset, sequence = c['offset'], c['sequence']
                except (ValueError, KeyError, TypeError):
                    raise ApiError(400, 'BAD_REQUEST', '日志游标无效')
            path = directory / 'service.log'
            items = []
            if path.exists():
                with path.open('rb') as f:
                    if offset > path.stat().st_size:
                        raise ApiError(400, 'BAD_REQUEST', '日志游标超出文件长度')
                    f.seek(offset)
                    for _ in range(limit):
                        line = f.readline(65536)
                        if not line:
                            break
                        # Keep unfinished UTF-8 log line for the next request while running.
                        if not line.endswith(b'\n') and len(line) < 65536 and r['status'] in ACTIVE:
                            break
                        items.append({'sequence': sequence, 'text': line.decode('utf-8', errors='replace').rstrip('\r\n')})
                        sequence += 1
                        offset = f.tell()
            size = path.stat().st_size if path.exists() else 0
            next_cursor = base64.urlsafe_b64encode(json.dumps({'run_id': run_id, 'offset': offset, 'sequence': sequence}).encode()).decode()
            return {'items': items, 'next_cursor': next_cursor, 'eof': r['status'] in TERMINAL and offset >= size}

    def result(self, run_id):
        with self.lock:
            r = self._record(run_id)
            if r['status'] in ACTIVE:
                raise ApiError(409, 'RUN_NOT_READY', '结果尚未就绪')
            if r['status'] != 'succeeded':
                raise ApiError(409, 'INVALID_STATE', '任务未成功，请查看状态和日志')
            directory = self.directory(r)
            self._scan(r)
            warnings = []
            if r['mode'] == 'train':
                ids = {a['kind']: a['artifact_id'] for a in r['artifacts']}
                ok = 'onnx' in ids and 'torchscript' in ids and not (directory / 'export_error.txt').exists()
                metrics = {'requested_iterations': r['request']['iterations'], 'completed_iterations': r['progress']['current_iteration'], 'final_checkpoint_artifact_id': next(a['artifact_id'] for a in r['artifacts'] if a['name'] == 'model_final.pt'), 'export_status': 'succeeded' if ok else 'failed', 'torchscript_artifact_id': ids.get('torchscript'), 'onnx_artifact_id': ids.get('onnx'), 'export_error': (directory / 'export_error.txt').read_text(encoding='utf-8') if (directory / 'export_error.txt').exists() else None}
                if 'export_verification' not in ids:
                    warnings.append('导出一致性未验证')
            else:
                metrics = json.loads((directory / ('verification.json' if r['mode'] == 'verify' else 'evaluation.json')).read_text(encoding='utf-8'))
                if 'checkpoint' in metrics and metrics['checkpoint'] is not None:
                    metrics['checkpoint'] = r['request'].get('checkpoint', {}).get('artifact_id') if r['request'].get('checkpoint') else None
            return {'mode': r['mode'], 'run_id': run_id, 'metrics': metrics, 'warnings': warnings}

    def import_run(self, source):
        """Local administrative command; copy finished results, never execute imports."""
        source = Path(source).resolve()
        if not (source / 'parameters.json').is_file():
            invalid('导入目录必须包含parameters.json')
        parameters = json.loads((source / 'parameters.json').read_text(encoding='utf-8'))
        self.validate(parameters)
        mode = 'train' if (source / 'model_final.pt').exists() else 'verify' if (source / 'verification.json').exists() else 'eval'
        if mode == 'eval' and not (source / 'evaluation.json').exists():
            invalid('缺少可识别的结果文件')
        with self.lock:
            run_id = uid('run')
            r = {'run_id': run_id, 'mode': mode, 'status': 'succeeded', 'created_at': now(), 'started_at': None, 'finished_at': now(), 'exit_code': 0, 'config_id': None, 'config_revision': None, 'parameter_source': 'checkpoint_snapshot', 'parameters_artifact_id': None, 'request': {'mode': mode, 'imported': True}, 'progress': {'current_iteration': None, 'target_iterations': None, 'simulation_time_s': None, 'target_seconds': None}, 'error': None, 'artifacts': []}
            dest = self.directory(r)
            dest.mkdir(parents=True)
            filenames = ['parameters.json', 'policy_io.json', 'env.yaml', 'agent.yaml', 'evaluation.json', 'verification.json', 'export_verification.json', 'export_error.txt', 'standing.mp4', 'model_final.pt', 'exported/policy.pt', 'exported/policy.onnx']
            for name in filenames:
                src = source / name
                if src.is_file():
                    target = dest / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, target)
            if mode == 'train':
                # Do not deserialize imported checkpoints in the web/backend process.
                r['request']['iterations'] = None
            self._scan(r)
            self.state['runs'][run_id] = r
            self._save()
            return self.run(run_id)
