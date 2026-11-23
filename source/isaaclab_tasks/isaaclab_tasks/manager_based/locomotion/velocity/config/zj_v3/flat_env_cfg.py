from __future__ import annotations

import math

from isaaclab.managers import SceneEntityCfg
from isaaclab.utils import configclass

import isaaclab_tasks.manager_based.locomotion.velocity.mdp as mdp
from isaaclab_tasks.manager_based.locomotion.velocity.velocity_env_cfg import LocomotionVelocityRoughEnvCfg

from .robot_cfg import ZJV3_CFG, ZJV3_FEET, ZJV3_JOINTS


@configclass
class ZJV3FlatEnvCfg(LocomotionVelocityRoughEnvCfg):
    """ZJ V3 velocity task; first curriculum stage is stable flat-ground locomotion."""

    def __post_init__(self):
        super().__post_init__()
        self.scene.robot = ZJV3_CFG.replace(prim_path="{ENV_REGEX_NS}/Robot")
        self.scene.height_scanner.prim_path = "{ENV_REGEX_NS}/Robot/BASE_LINK"
        self.actions.joint_pos.joint_names = ZJV3_JOINTS
        self.commands.base_velocity.ranges = mdp.UniformVelocityCommandCfg.Ranges(
            lin_vel_x=(-0.7, 0.9), lin_vel_y=(-0.45, 0.45), ang_vel_z=(-1.2, 1.2), heading=(-math.pi, math.pi)
        )
        self.commands.base_velocity.rel_standing_envs = 0.15
        self.commands.base_velocity.heading_command = False
        self.scene.terrain.terrain_type = "plane"
        self.scene.terrain.terrain_generator = None
        self.scene.height_scanner = None
        self.observations.policy.height_scan = None
        self.curriculum.terrain_levels = None
        self.events.add_base_mass = None
        self.events.base_com = None
        self.events.push_robot = None
        self.events.reset_robot_joints.params["position_range"] = (0.95, 1.05)
        self.events.reset_base.params["pose_range"] = {"x": (-0.2, 0.2), "y": (-0.2, 0.2), "yaw": (-math.pi, math.pi)}
        self.events.base_external_force_torque.params["asset_cfg"].body_names = ["BASE_LINK"]
        self.rewards.feet_air_time.params["sensor_cfg"].body_names = ZJV3_FEET
        self.rewards.undesired_contacts = None
        self.rewards.flat_orientation_l2.weight = -2.0
        self.rewards.lin_vel_z_l2.weight = -1.0
        self.rewards.dof_torques_l2.weight = -2.0e-5
        self.rewards.action_rate_l2.weight = -0.015
        self.terminations.base_contact.params["sensor_cfg"].body_names = "BASE_LINK"
        self.terminations.base_orientation = None
        self.terminations.root_height_below_minimum = None
        self.episode_length_s = 20.0


@configclass
class ZJV3FlatEnvCfg_PLAY(ZJV3FlatEnvCfg):
    def __post_init__(self):
        super().__post_init__()
        self.scene.num_envs = 1
        self.scene.env_spacing = 3.0
        self.observations.policy.enable_corruption = False
        self.commands.base_velocity.rel_standing_envs = 0.0
        self.commands.base_velocity.ranges.lin_vel_x = (0.3, 0.3)
        self.commands.base_velocity.ranges.lin_vel_y = (0.0, 0.0)
        self.commands.base_velocity.ranges.ang_vel_z = (0.0, 0.0)
