"""Finite-duration, independently scheduled physical push pulses."""
import math
import torch
from isaaclab.envs import ManagerBasedRLEnv


class ZJV3StandEnv(ManagerBasedRLEnv):
    def __init__(self, cfg, **kwargs):
        super().__init__(cfg, **kwargs)
        self.base_ids = self.scene['robot'].find_bodies('BASE_LINK')[0]
        self.wheel_ids = self.scene['robot'].find_joints('.*_FOOT_JOINT')[0]
        self.leg_ids = self.scene['robot'].find_joints('.*_(ABAD|HIP|KNEE)_JOINT')[0]
        self.nonfoot_ids = self.scene['contact_forces'].find_bodies('.*_(BASE|ABAD|HIP|KNEE)_LINK|BASE_LINK')[0]
        self.push_force = torch.zeros((self.num_envs, 1, 3), device=self.device)
        self.push_torque = torch.zeros_like(self.push_force)
        self.push_remaining = torch.zeros(self.num_envs, device=self.device)
        self.push_wait = torch.zeros_like(self.push_remaining)
        self.push_count = torch.zeros_like(self.push_remaining)
        self._stand_error_step = None

    def _uniform(self, interval, n):
        return torch.rand(n, device=self.device) * (interval[1] - interval[0]) + interval[0]

    def _reset_idx(self, env_ids):
        super()._reset_idx(env_ids)
        if hasattr(self, 'push_force'):
            self.push_force[env_ids] = 0
            self.push_torque[env_ids] = 0
            self.push_remaining[env_ids] = 0
            self.push_wait[env_ids] = self._uniform(self.cfg.stand_settings['disturbance']['interval_s'], len(env_ids))

    def step(self, action):
        p = self.cfg.stand_settings['disturbance']
        # Time-based curriculum uses total control steps, independent of env count.
        elapsed = self.common_step_counter * self.step_dt
        gain = min(1.0, max(0.0, (elapsed - p['warmup_s']) / max(p['ramp_s'], self.step_dt)))
        active = self.push_remaining > 0
        self.push_wait[~active] -= self.step_dt
        start = (~active) & (self.push_wait <= 0) & (gain > 0) & p['enabled']
        ids = start.nonzero(as_tuple=False).flatten()
        n = len(ids)
        if n:
            angle = self._uniform((0, 2 * math.pi), n)
            magnitude = self._uniform(p['horizontal_force_n'], n) * gain
            f = torch.stack((magnitude * angle.cos(), magnitude * angle.sin(), self._uniform(p['vertical_force_n'], n) * gain), -1)
            # World-frame lever arm creates the same COM moment as an off-center push.
            lever = torch.stack([self._uniform((-a, a), n) for a in p['lever_arm_m']], -1)
            self.push_force[ids, 0] = f
            self.push_torque[ids, 0] = torch.cross(lever, f, dim=-1)
            self.push_remaining[ids] = self._uniform(p['duration_s'], n)
            self.push_wait[ids] = self._uniform(p['interval_s'], n)
            self.push_count[ids] += 1
        active = self.push_remaining > 0
        f = self.push_force * active[:, None, None]
        t = self.push_torque * active[:, None, None]
        self.scene['robot'].permanent_wrench_composer.set_forces_and_torques(
            forces=f, torques=t, body_ids=self.base_ids, is_global=True
        )
        out = super().step(action.clamp(-1., 1.))
        self.push_remaining = torch.clamp(self.push_remaining - self.step_dt, min=0)
        self.extras.setdefault('log', {}).update({
            'Push/curriculum': gain, 'Push/active_fraction': active.float().mean(),
            'Push/force_n': f.norm(dim=-1).mean(), 'Push/count': self.push_count.sum(),
        })
        return out
