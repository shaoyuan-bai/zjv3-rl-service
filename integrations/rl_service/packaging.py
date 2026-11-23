"""Build a relocatable source/assets bundle; never claim it contains Isaac Sim."""
import hashlib
import json
from pathlib import Path
import platform
import zipfile


def bundle(settings, output, include_runs=False):
    from .core import Service
    service = Service(settings)
    try:
        if any(r['status'] in ('starting', 'running', 'cancelling') for r in service.state['runs'].values()):
            raise RuntimeError('Stop active jobs before packaging')
        project = settings.project
        output = Path(output).resolve()
        if output.exists():
            raise FileExistsError(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        roots = ['source', 'apps', 'integrations', 'assets/robots/zj_v3', 'models/zj_v3', 'docs/deployment']
        files = set()
        for name in roots:
            root = project / name
            if root.exists():
                files.update(p for p in root.rglob('*') if p.is_file() and not p.is_symlink())
        for pattern in ('scripts/my/zj_v3_stand*.py', 'scripts/my/zj_v3_check_export.py', 'scripts/my/zj_v3_prepare_asset.py', 'scripts/my/test_zj_v3*.py', 'scripts/my/README_ZJV3_TRAINING.md', 'start_rl_service.*'):
            files.update(project.glob(pattern))
        for name in ('VERSION', 'LICENSE', 'LICENSE-mimic', 'README_RL.md', 'rl_service.json', 'pyproject.toml', 'environment.yml'):
            if (project / name).is_file():
                files.add(project / name)
        if include_runs:
            files.update(p for p in settings.data.rglob('*') if p.is_file() and not p.is_symlink())
        def allowed(p):
            return not any(x in {'__pycache__', '.git', '.pytest_cache', 'cache', 'warp'} or x.endswith('.egg-info') for x in p.parts) and p.suffix not in ('.pyc', '.pyo', '.tmp') and p.name not in ('service.lock', 'worker_job.json', 'cancel.request', 'api_token.txt')
        manifest = {'format_version': 1, 'runtime_included': False, 'platform_at_build': platform.platform(), 'include_runs': include_runs, 'files': []}
        with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=3) as archive:
            for path in sorted(filter(allowed, files)):
                if path.is_relative_to(settings.data) and include_runs:
                    name = 'runtime/rl/' + path.relative_to(settings.data).as_posix()
                elif path.is_relative_to(project):
                    name = path.relative_to(project).as_posix()
                else:
                    continue
                # No machine-specific deployment file: ship portable defaults.
                if name == 'rl_service.json':
                    data = json.dumps({'host': '127.0.0.1', 'port': 8000, 'python': None, 'data_dir': 'runtime/rl', 'robot_usd': 'assets/robots/zj_v3/robot.usd', 'device': 'cuda:0', 'cors_origins': settings.origins}, indent=2).encode()
                    archive.writestr(name, data)
                    digest, size = hashlib.sha256(data).hexdigest(), len(data)
                else:
                    archive.write(path, name)
                    with path.open('rb') as stream:
                        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
                    size = path.stat().st_size
                manifest['files'].append({'path': name, 'size_bytes': size, 'sha256': digest})
            archive.writestr('BUNDLE_MANIFEST.json', json.dumps(manifest, ensure_ascii=False, indent=2))
        return str(output)
    finally:
        service.close()
