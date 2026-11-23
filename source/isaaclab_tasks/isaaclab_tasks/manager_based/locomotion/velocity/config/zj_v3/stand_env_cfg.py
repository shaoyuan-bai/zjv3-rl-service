"""Independent standing task; editable settings are frozen into every run."""
from types import SimpleNamespace

import isaaclab.sim as sim_utils
import isaaclab_tasks.manager_based.locomotion.velocity.mdp as mdp
from isaaclab.managers import ObservationTermCfg, RewardTermCfg, TerminationTermCfg, SceneEntityCfg
from isaaclab.utils import configclass

from .flat_env_cfg import ZJV3FlatEnvCfg
from . import stand_mdp
from .stand_settings import load_settings


@configclass
class ZJV3StandEnvCfg(ZJV3FlatEnvCfg):
    def __post_init__(self):
        super().__post_init__()
        self.stand_settings = p = load_settings()
        self.scene.num_envs = 128
        self.scene.env_spacing = 5.0
        # Local materials avoid downloads during training startup.
        self.scene.terrain.visual_material = sim_utils.PreviewSurfaceCfg(diffuse_color=(.22, .25, .28))
        self.scene.sky_light.spawn = sim_utils.DomeLightCfg(intensity=1000, color=(.8, .85, 1.))
        self.scene.robot.init_state.pos = (0, 0, p['robot']['spawn_height_m'])
        # The imported asset uses acceleration drives. Raw Kp/Kd describe torque PD,
        # so explicitly select force drives in the simulation overlay.
        self.scene.robot.spawn.joint_drive_props = sim_utils.JointDrivePropertiesCfg(drive_type='force')
        self.sim.physx.enable_external_forces_every_iteration = True
        self.scene.robot.init_state.joint_pos = {
            '.*_ABAD_JOINT': p['robot']['abad_rad'], '.*_HIP_JOINT': p['robot']['hip_rad'],
            '.*_KNEE_JOINT': p['robot']['knee_rad'], '.*_FOOT_JOINT': 0.,
        }
        self.actions.joint_pos.scale = p['robot']['action_scale_rad']
        self.actions.joint_pos.clip = None
        self.actions.joint_pos.preserve_order = True
        self.commands.base_velocity.heading_command = False
        self.commands.base_velocity.rel_standing_envs = 1.0
        self.commands.base_velocity.debug_vis = False
        self.commands.base_velocity.ranges.lin_vel_x = (0., 0.)
        self.commands.base_velocity.ranges.lin_vel_y = (0., 0.)
        self.commands.base_velocity.ranges.ang_vel_z = (0., 0.)
        # Explicit anchor observations avoid an unobservable position/heading objective.
        self.observations.policy.anchor_error = ObservationTermCfg(func=stand_mdp.anchor_error)
        self.events.base_external_force_torque = None
        self.events.reset_base.params = {
            'pose_range': {'roll': (-p['reset']['tilt_rad'], p['reset']['tilt_rad']),
                           'pitch': (-p['reset']['tilt_rad'], p['reset']['tilt_rad'])},
            'velocity_range': {},
        }
        self.events.reset_robot_joints.func = mdp.reset_joints_by_offset
        self.events.reset_robot_joints.params = {
            'position_range': (-p['reset']['joint_offset_rad'], p['reset']['joint_offset_rad']),
            'velocity_range': (0., 0.),
        }
        terms = {'alive': RewardTermCfg(func=mdp.is_alive, weight=p['alive_weight'])}
        for key, v in p['rewards'].items():
            terms[key] = RewardTermCfg(func=stand_mdp.reward, weight=v['weight'] if v['enabled'] else 0.,
                params={'kind':key, **{k:v[k] for k in ('tolerance','scale','cap')}})
        self.rewards = SimpleNamespace(**terms)
        self.terminations.base_contact.params['threshold'] = p['termination']['contact_threshold_n']
        self.terminations.base_orientation = TerminationTermCfg(func=mdp.bad_orientation,
            params={'limit_angle':p['termination']['maximum_tilt_rad']})
        self.terminations.root_height_below_minimum = TerminationTermCfg(func=mdp.root_height_below_minimum,
            params={'minimum_height':p['termination']['minimum_height_m']})
        self.terminations.outside_anchor = TerminationTermCfg(func=stand_mdp.outside_anchor,
            params={'maximum_distance':p['termination']['maximum_anchor_distance_m']})
        self.viewer.eye = (2.6, 2.6, 1.7)
        self.viewer.lookat = (0., 0., .4)
