"""Standing rewards. All errors are measured against the episode's fixed anchor."""
import torch
from isaaclab.utils.math import euler_xyz_from_quat, wrap_to_pi


def errors(env):
    r = env.scene['robot']
    d = r.data
    _, _, yaw = euler_xyz_from_quat(d.root_quat_w)
    qerr = d.joint_pos - d.default_joint_pos
    # Wheel angle is periodic; do not penalize turns accumulated during recovery.
    qerr = qerr.clone()
    qerr[:, env.wheel_ids] = wrap_to_pi(qerr[:, env.wheel_ids])
    settings = env.cfg.stand_settings['rewards']
    def weighted_norm(value, key, field='joint_weights', mean=False):
        weights = torch.as_tensor(settings[key].get(field, [1.] * value.shape[-1]), device=value.device)
        squared = (value.square() * weights).sum(-1)
        if mean:
            squared = squared / value.shape[-1]
        return squared.sqrt()
    margin = settings['joint_limits'].get('safety_margin_rad', 0.)
    return {
        'orientation': d.projected_gravity_b[:, :2].square().sum(-1).sqrt(),
        'height': (d.root_pos_w[:, 2] - env.scene.env_origins[:, 2] - env.cfg.stand_settings['robot']['height_m']).abs(),
        'horizontal_speed': d.root_lin_vel_w[:, :2].norm(dim=-1),
        'vertical_speed': d.root_lin_vel_w[:, 2].abs(),
        'angular_speed': weighted_norm(d.root_ang_vel_w, 'angular_speed', field='axis_weights'),
        'position': (d.root_pos_w[:, :2] - env.scene.env_origins[:, :2]).norm(dim=-1),
        'heading': wrap_to_pi(yaw).abs(),
        'joint_pose': weighted_norm(qerr[:, env.leg_ids], 'joint_pose', mean=True),
        'action_rate': weighted_norm(env.action_manager.action - env.action_manager.prev_action, 'action_rate'),
        'torque': weighted_norm(d.applied_torque, 'torque'),
        'joint_limits': torch.clamp(d.joint_pos[:, env.leg_ids] - (d.soft_joint_pos_limits[:, env.leg_ids, 1] - margin), min=0).sum(-1)
            + torch.clamp((d.soft_joint_pos_limits[:, env.leg_ids, 0] + margin) - d.joint_pos[:, env.leg_ids], min=0).sum(-1),
        'body_contact': (env.scene['contact_forces'].data.net_forces_w_history[:, :, env.nonfoot_ids].norm(dim=-1).amax(dim=1) > env.cfg.stand_settings['termination']['contact_threshold_n']).float().sum(-1),
        'fall': env.termination_manager.terminated.float(),
    }


def reward(env, kind: str, tolerance: float = 0.0, scale: float = 1.0, cap: float = 1000000.0):
    # Cache for one physics step; all reward terms share the same state.
    if getattr(env, '_stand_error_step', None) != env._sim_step_counter:
        env._stand_errors = errors(env)
        env._stand_error_step = env._sim_step_counter
    e = torch.clamp((env._stand_errors[kind] - tolerance) / scale, min=0.0, max=cap)
    return e if kind in ('fall', 'body_contact') else e.square()


def anchor_error(env):
    """Deployment-visible anchor error; a real robot needs an odometry estimate."""
    d = env.scene['robot'].data
    _, _, yaw = euler_xyz_from_quat(d.root_quat_w)
    return torch.cat((d.root_pos_w[:, :2] - env.scene.env_origins[:, :2], wrap_to_pi(yaw).unsqueeze(-1)), dim=-1)


def outside_anchor(env, maximum_distance: float):
    return anchor_error(env)[:, :2].norm(dim=-1) > maximum_distance
