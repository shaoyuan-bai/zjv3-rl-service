"""Resolve deployment paths relative to a config file, never a user's drive."""
import json
import ipaddress
import os
from pathlib import Path
import sys


class Settings:
    def __init__(self, filename=None):
        self.project = Path(__file__).resolve().parents[2]
        self.filename = Path(filename or os.getenv('RL_SERVICE_CONFIG', self.project / 'rl_service.json')).resolve()
        self.raw = json.loads(self.filename.read_text(encoding='utf-8'))
        allowed = {'host', 'port', 'python', 'data_dir', 'robot_usd', 'device', 'cors_origins', 'allowed_client_ips', 'api_token_env'}
        if set(self.raw) - allowed:
            raise ValueError('Unknown deployment settings: ' + str(set(self.raw) - allowed))
        self.host = self.raw.get('host', '127.0.0.1')
        if not isinstance(self.host, str) or not self.host:
            raise ValueError('host must be a non-empty address')
        self.port = self.raw.get('port', 8000)
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ValueError('Invalid port')
        self.python = self.path(os.getenv('ZJV3_PYTHON') or self.raw.get('python') or sys.executable)
        self.data = self.path(self.raw.get('data_dir', 'runtime/rl'))
        self.usd = self.path(os.getenv('ZJV3_USD_PATH') or self.raw.get('robot_usd', 'assets/robots/zj_v3/robot.usd'))
        self.device = self.raw.get('device', 'cuda:0')
        if not isinstance(self.device, str) or not self.device.startswith('cuda:') or not self.device[5:].isdigit():
            raise ValueError('device must be cuda:<index>')
        self.origins = self.raw.get('cors_origins', [])
        if not isinstance(self.origins, list) or any(not isinstance(x, str) or x == '*' for x in self.origins):
            raise ValueError('cors_origins must contain explicit origins')
        self.allowed_client_ips = self.raw.get('allowed_client_ips', ['127.0.0.1', '::1'])
        if not isinstance(self.allowed_client_ips, list) or any(not isinstance(x, str) or not x for x in self.allowed_client_ips):
            raise ValueError('allowed_client_ips must be a non-empty string list')
        self.client_networks = [ipaddress.ip_network(x, strict=False) for x in self.allowed_client_ips]
        self.api_token_env = self.raw.get('api_token_env', 'RL_SERVICE_API_TOKEN')
        if not isinstance(self.api_token_env, str) or not self.api_token_env.isidentifier():
            raise ValueError('api_token_env must be an environment variable name')
        self.task = self.project / 'source/isaaclab_tasks/isaaclab_tasks/manager_based/locomotion/velocity/config/zj_v3'
        self.script = self.project / 'scripts/my/zj_v3_stand.py'

    def allows_client(self, address):
        try:
            ip = ipaddress.ip_address(address)
            if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
                ip = ip.ipv4_mapped
            return any(ip in network for network in self.client_networks)
        except ValueError:
            return False

    def path(self, value):
        p = Path(os.path.expandvars(value)).expanduser()
        return (p if p.is_absolute() else self.filename.parent / p).resolve()

    def environment(self):
        env = os.environ.copy()
        packages = [p for p in (self.project / 'source').iterdir() if p.is_dir() and (p / p.name).is_dir()]
        env['PYTHONPATH'] = os.pathsep.join([str(p) for p in packages] + [str(self.project), env.get('PYTHONPATH', '')])
        env['ZJV3_USD_PATH'] = str(self.usd)
        env['ZJV3_RUNS_DIR'] = str(self.data / 'runs')
        env['WARP_CACHE_PATH'] = str(self.data / 'cache/warp')
        env['PYTHONUNBUFFERED'] = '1'
        env['PYTHONIOENCODING'] = 'utf-8'
        return env
