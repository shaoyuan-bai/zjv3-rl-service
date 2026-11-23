"""Integration checks run in the actual simulator, including force impulse physics."""
from types import SimpleNamespace
import torch
from isaaclab.envs import ManagerBasedRLEnv
from isaaclab_tasks.manager_based.locomotion.velocity.config.zj_v3 import stand_mdp


def verify(env):
    assert env.num_envs >= 2, 'Verification needs at least two environments'
    device = env.device
    # Dead zones, normalization, cap and event semantics have independent expectations.
    mock = SimpleNamespace(_sim_step_counter=9, _stand_error_step=9,
        _stand_errors={'height':torch.tensor([.1,.4,100.], device=device),
                       'fall':torch.tensor([0.,1.,0.], device=device)})
    torch.testing.assert_close(stand_mdp.reward(mock,'height',tolerance=.2,scale=.1,cap=3),
        torch.tensor([0.,4.,9.],device=device))
    torch.testing.assert_close(stand_mdp.reward(mock,'fall'), torch.tensor([0.,1.,0.],device=device))
    robot = env.scene['robot']
    states = robot.data.default_root_state.clone()
    states[:, :3] += env.scene.env_origins
    states[:, 2] = 3.0
    states[:, 3:7] = torch.tensor([1.,0.,0.,0.],device=device)
    states[:, 7:] = 0
    robot.write_root_pose_to_sim(states[:, :7])
    robot.write_root_velocity_to_sim(states[:, 7:])
    robot.write_joint_state_to_sim(robot.data.default_joint_pos.clone(),torch.zeros_like(robot.data.joint_vel))
    mass = robot.root_physx_view.get_masses().to(device)
    forces = torch.zeros((env.num_envs,1,3),device=device)
    forces[0,0,0] = 80.
    robot.permanent_wrench_composer.set_forces_and_torques(forces=forces,torques=torch.zeros_like(forces),body_ids=env.base_ids,is_global=True)
    action = torch.zeros_like(env.action_manager.action)
    # Bypass the pulse scheduler to compare a known physical impulse to a control env.
    ManagerBasedRLEnv.step(env,action)
    momentum = (robot.data.body_com_lin_vel_w * mass.unsqueeze(-1)).sum(dim=1)
    measured = float(momentum[0,0] - momentum[1,0])
    expected = 80. * env.step_dt
    assert abs(measured-expected) < .15, (measured,expected)
    # Scheduling boundaries: finished pulses must clear and reset must cancel pending force.
    env.push_remaining[:] = 0
    env.push_wait[:] = 10
    env.push_force[:] = 80
    env.push_torque[:] = 3
    env.cfg.stand_settings['disturbance']['enabled'] = False
    before = momentum.clone()
    env.step(action)
    after = (robot.data.body_com_lin_vel_w * mass.unsqueeze(-1)).sum(dim=1)
    assert abs(float((after-before)[0,0])) < .15, 'Finished pulse still applying force'
    env._reset_idx(torch.arange(env.num_envs,device=device))
    assert not env.push_force.any() and not env.push_torque.any() and not env.push_remaining.any()
    print('ZJV3_VERIFY_OK', {'measured_impulse_ns':measured,'expected_impulse_ns':expected,
        'reward_deadzone_scale_cap':True,'pulse_clear':True,'reset_clear':True},flush=True)
    return {'measured_impulse_ns':measured,'expected_impulse_ns':expected,'passed':True}
