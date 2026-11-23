"""Train or measure ZJ V3 standing. Use the existing isaacsim Conda Python."""
import argparse
import json
import os
import time
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[2]
RUNS_ROOT = Path(os.environ.get('ZJV3_RUNS_DIR', ROOT / 'runtime/rl/runs')).resolve()
os.environ.setdefault('WARP_CACHE_PATH', str(RUNS_ROOT / 'warp'))
from isaaclab.app import AppLauncher

parser = argparse.ArgumentParser()
parser.add_argument('--mode', choices=('train', 'pd', 'eval', 'verify', 'play'), default='train')
parser.add_argument('--config', help='Editable standing parameters JSON')
parser.add_argument('--checkpoint')
parser.add_argument('--run_dir', help='Explicit output directory (backend); existing results are never overwritten')
parser.add_argument('--num_envs', type=int, default=128)
parser.add_argument('--iterations', type=int, default=300)
parser.add_argument('--seconds', type=float, default=40.)
parser.add_argument('--pushes', choices=('off', 'mild', 'full'), default='full')
parser.add_argument('--seed', type=int, default=42)
parser.add_argument('--diagnostics', action='store_true')
parser.add_argument('--video', action='store_true', help='Record env 0 during evaluation (25 FPS).')
AppLauncher.add_app_launcher_args(parser)
args = parser.parse_args()
if args.video:
    args.enable_cameras = True
if args.checkpoint and not args.config:
    saved_settings = Path(args.checkpoint).resolve().parent / 'parameters.json'
    if saved_settings.is_file():
        args.config = str(saved_settings)
if args.config:
    os.environ['ZJV3_STAND_CONFIG'] = str(Path(args.config).resolve())
launcher = AppLauncher(args)


def main():
    import gymnasium as gym
    import torch
    import isaaclab_tasks
    from isaaclab_tasks.utils import load_cfg_from_registry
    from isaaclab_rl.rsl_rl import RslRlVecEnvWrapper, export_policy_as_jit, export_policy_as_onnx
    from rsl_rl.runners import OnPolicyRunner
    from isaaclab.utils.io import dump_yaml
    from isaaclab.utils.math import euler_xyz_from_quat

    torch.manual_seed(args.seed)
    cfg = load_cfg_from_registry('Isaac-ZJV3-Stand-v0', 'env_cfg_entry_point')
    agent = load_cfg_from_registry('Isaac-ZJV3-Stand-v0', 'rsl_rl_cfg_entry_point')
    cfg.scene.num_envs = args.num_envs
    cfg.sim.device = args.device
    cfg.seed = agent.seed = args.seed
    run = Path(args.run_dir).resolve() if args.run_dir else RUNS_ROOT / (datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '_' + args.mode + '_' + args.pushes)
    if args.run_dir and any((run / name).exists() for name in ('parameters.json', 'model_final.pt', 'evaluation.json', 'verification.json')):
        raise ValueError('Output directory already contains results')
    run.mkdir(parents=True, exist_ok=bool(args.run_dir))
    def progress(**values):
        target = run / 'progress.json'
        # This tiny, best-effort status file is polled by the API.  On Windows,
        # replacing an open file can block indefinitely when a LAN client is
        # polling rapidly, freezing the trainer after its log line is emitted.
        target.write_text(json.dumps(values), encoding='utf-8')
    cfg.log_dir = str(run)
    if args.mode != 'train':
        cfg.observations.policy.enable_corruption = False
        cfg.episode_length_s = args.seconds
        cfg.stand_settings['disturbance']['warmup_s'] = 0.
        cfg.stand_settings['disturbance']['ramp_s'] = cfg.sim.dt * cfg.decimation
    if args.pushes == 'off':
        cfg.stand_settings['disturbance']['enabled'] = False
    elif args.pushes == 'mild':
        cfg.stand_settings['disturbance']['horizontal_force_n'] = [10., 35.]
    (run / 'parameters.json').write_text(json.dumps(cfg.stand_settings, ensure_ascii=False, indent=2), encoding='utf-8')
    print('ZJV3_RUN', run, flush=True)
    cfg.viewer.resolution = (960, 640)
    if args.mode == 'play':
        cfg.viewer.eye = (2.5, 2.5, 1.8)
        cfg.viewer.lookat = (0., 0., 0.5)
    env = gym.make('Isaac-ZJV3-Stand-v0', cfg=cfg, render_mode='rgb_array' if args.video else None)
    raw = env.unwrapped
    wrapped = RslRlVecEnvWrapper(env, clip_actions=1.)
    robot = raw.scene['robot']
    io = {
        'observation_terms': raw.observation_manager._group_obs_term_names['policy'],
        'observation_shapes': [list(x) for x in raw.observation_manager._group_obs_term_dim['policy']],
        'joint_state_order':robot.joint_names,
        'action_joint_order':raw.action_manager.get_term('joint_pos')._joint_names,
        'reference_joint_positions_rad':robot.data.default_joint_pos[0].tolist(),
        'stiffness_nm_per_rad':robot.data.joint_stiffness[0].tolist(),
        'damping_nm_s_per_rad':robot.data.joint_damping[0].tolist(),
        'effort_limits_nm':robot.data.joint_effort_limits[0].tolist(),
        'action_clip':[-1.,1.], 'action_scale_rad':cfg.stand_settings['robot']['action_scale_rad'],
        'control_dt_s':raw.step_dt, 'drive_type':'force',
    }
    (run / 'policy_io.json').write_text(json.dumps(io, indent=2),encoding='utf-8')
    if args.diagnostics:
        from pxr import UsdPhysics, UsdGeom, Usd
        stage = raw.sim.stage
        robot = raw.scene['robot']
        print('DIAG_JOINTS', robot.joint_names, robot.data.default_joint_pos[0].tolist(), flush=True)
        print('DIAG_BODIES', robot.body_names, robot.data.body_pos_w[0].tolist(), flush=True)
        print('DIAG_MASS', robot.root_physx_view.get_masses()[0].tolist(), flush=True)
        print('DIAG_GAINS', robot.data.joint_stiffness[0].tolist(), robot.data.joint_damping[0].tolist(), robot.data.joint_effort_limits[0].tolist(), flush=True)
        prims = [x for x in stage.Traverse() if str(x.GetPath()).startswith('/World/envs/env_0/Robot')]
        print('DIAG_COLLIDERS', [(str(x.GetPath()), UsdPhysics.CollisionAPI(x).GetCollisionEnabledAttr().Get()) for x in prims if x.HasAPI(UsdPhysics.CollisionAPI)], flush=True)
        print('DIAG_BOUNDS', UsdGeom.BBoxCache(Usd.TimeCode.Default(), ['default','render','proxy']).ComputeWorldBound(stage.GetPrimAtPath('/World/envs/env_0/Robot')).ComputeAlignedRange(), flush=True)
    runner = None
    if args.mode in ('train', 'eval', 'play'):
        agent.device = cfg.sim.device
        runner = OnPolicyRunner(wrapped, agent.to_dict(), log_dir=str(run), device=agent.device)
        if args.checkpoint:
            runner.load(args.checkpoint)
        elif args.mode in ('eval', 'play'):
            raise ValueError('--checkpoint is required for eval/play')
        else:
            # Start from a tested PD equilibrium; PPO learns residual corrections.
            with torch.no_grad():
                runner.alg.policy.actor[-1].weight.zero_()
                runner.alg.policy.actor[-1].bias.zero_()
            print('ZJV3_INITIAL_POLICY zero residual mean; PD baseline preserved', flush=True)
    dump_yaml(str(run / 'env.yaml'), cfg)
    dump_yaml(str(run / 'agent.yaml'), agent)
    if args.mode == 'verify':
        from zj_v3_stand_verify import verify
        result = verify(raw)
        (run / 'verification.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    elif args.mode == 'train':
        initial_iteration = runner.current_learning_iteration
        original_log = runner.log
        def log_progress(locs, *positional, **keyword):
            result = original_log(locs, *positional, **keyword)
            progress(current_iteration=locs['it'] - initial_iteration + 1)
            return result
        runner.log = log_progress
        progress(current_iteration=0)
        runner.learn(num_learning_iterations=args.iterations, init_at_random_ep_len=False)
        runner.save(str(run / 'model_final.pt'))
        try:
            export_policy_as_jit(runner.alg.policy, normalizer=runner.alg.policy.actor_obs_normalizer, path=str(run / 'exported'))
            export_policy_as_onnx(runner.alg.policy, normalizer=runner.alg.policy.actor_obs_normalizer, path=str(run / 'exported'))
        except Exception as exc:
            (run / 'export_error.txt').write_text(str(exc), encoding='utf-8')
    else:
        obs = wrapped.get_observations()
        policy = runner.get_inference_policy(device=cfg.sim.device) if runner else None
        failed = torch.zeros(raw.num_envs, dtype=torch.bool, device=raw.device)
        first_failure = torch.full((raw.num_envs,), args.seconds, device=raw.device)
        pushes = recovered = 0
        waiting = torch.zeros_like(failed)
        recovery_timer = torch.zeros(raw.num_envs, device=raw.device)
        stable_hold = torch.zeros_like(recovery_timer)
        recovery_times = []
        series = []
        video = None
        if args.video:
            import imageio.v2 as imageio
            video = imageio.get_writer(str(run / 'standing.mp4'), fps=25, codec='libx264', macro_block_size=None)
        completed_steps = 0
        for i in range(round(args.seconds / raw.step_dt)):
            if args.mode == 'play' and not launcher.app.is_running():
                break
            step_started = time.monotonic()
            with torch.inference_mode():
                before = raw.push_remaining.clone()
                count = raw.push_count.clone()
                action = policy(obs) if policy else torch.zeros_like(raw.action_manager.action)
                obs, rew, done, extras = wrapped.step(action)
                d = raw.scene['robot'].data
                terminated = raw.reset_terminated.clone()
                if args.diagnostics and i < 30:
                    print('DIAG_STEP', i, 'root', d.root_pos_w[0].tolist(), 'feet',d.body_pos_w[0, robot.find_bodies('.*_FOOT_LINK')[0], 2].tolist(),
                        'q', d.joint_pos[0].tolist(), 'torque', d.applied_torque[0].tolist(),
                        'contacts',raw.scene['contact_forces'].data.net_forces_w[0].norm(dim=-1).tolist(),
                        'fail', {k:v[0].item() for k,v in raw.termination_manager._term_dones.items()} if isinstance(raw.termination_manager._term_dones, dict) else raw.termination_manager._term_dones[0].tolist(), flush=True)
                first_failure[(~failed) & terminated] = (i + 1) * raw.step_dt
                failed |= terminated
                started = raw.push_count > count
                pushes += int(started.sum())
                waiting[started] = False
                ended = (before > 0) & (raw.push_remaining <= 0) & (~terminated)
                waiting[ended] = True
                recovery_timer[ended] = 0
                stable_hold[ended] = 0
                waiting[terminated] = False
                recovery_timer[waiting] += raw.step_dt
                pos = (d.root_pos_w[:, :2] - raw.scene.env_origins[:, :2]).norm(dim=-1)
                tilt = torch.acos((-d.projected_gravity_b[:, 2]).clamp(-1, 1))
                _, _, yaw = euler_xyz_from_quat(d.root_quat_w)
                stable = (tilt < .15) & (d.root_lin_vel_w.norm(dim=-1) < .15) & (d.root_ang_vel_w.norm(dim=-1) < .3) & (pos < .2) & (yaw.abs() < .2)
                stable_hold = torch.where(waiting & stable, stable_hold + raw.step_dt, 0.)
                success = waiting & (stable_hold >= .3)
                recovery_times.extend(recovery_timer[success].cpu().tolist())
                recovered += int(success.sum())
                waiting[success] = False
                if not torch.isfinite(rew).all() or not torch.isfinite(d.root_pos_w).all():
                    raise RuntimeError('Non-finite simulation values')
                if i % 25 == 0:
                    progress(simulation_time_s=(i + 1) * raw.step_dt)
                    series.append({'time_s':i * raw.step_dt, 'mean_height_m':float(d.root_pos_w[:, 2].mean()),
                        'mean_tilt_rad':float(tilt.mean()), 'mean_anchor_error_m':float(pos.mean()),
                        'mean_yaw_error_rad':float(yaw.abs().mean()), 'mean_speed_mps':float(d.root_lin_vel_w.norm(dim=-1).mean()),
                        'push_active':int((raw.push_remaining > 0).sum())})
                if video and i % 2 == 0:
                    from PIL import Image, ImageDraw
                    frame = Image.fromarray(env.render())
                    draw = ImageDraw.Draw(frame)
                    force = raw.push_force[0,0] * (raw.push_remaining[0] > 0)
                    text = f't={(i+1)*raw.step_dt:.2f}s  push force(N): {[round(x,1) for x in force.tolist()]}'
                    draw.rectangle((0,0,960,28), fill=(20,20,20))
                    draw.text((8,8),text,fill=(255,255,255))
                    video.append_data(__import__('numpy').asarray(frame))
            completed_steps = i + 1
            if args.mode == 'play':
                time.sleep(max(0., raw.step_dt - (time.monotonic() - step_started)))
        if video:
            video.close()
        result = {'mode':args.mode, 'checkpoint':args.checkpoint, 'push_profile':args.pushes, 'num_envs':raw.num_envs,
            'duration_s':completed_steps * raw.step_dt, 'seed':args.seed, 'survival_fraction':float((~failed).float().mean()),
            'mean_first_failure_or_timeout_s':float(first_failure.mean()), 'pushes_started':pushes,
            'recoveries_detected':recovered, 'mean_recovery_s':sum(recovery_times)/len(recovery_times) if recovery_times else None,
            'recovery_definition':'post-push thresholds sustained for 0.3s: tilt<0.15rad, linear speed<0.15m/s, angular speed<0.3rad/s, position error<0.2m, yaw error<0.2rad; recovery time includes hold interval',
            'series':series}
        (run / 'evaluation.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        progress(simulation_time_s=completed_steps * raw.step_dt)
        print('ZJV3_RESULT', json.dumps({k:v for k,v in result.items() if k != 'series'}), flush=True)
    wrapped.close()


try:
    main()
finally:
    launcher.app.close()
