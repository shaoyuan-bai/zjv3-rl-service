from __future__ import annotations

import os
from pathlib import Path

import isaaclab.sim as sim_utils
from isaaclab.actuators import ImplicitActuatorCfg
from isaaclab.assets import ArticulationCfg

ZJV3_USD_PATH = os.getenv(
    "ZJV3_USD_PATH",
    str(Path(__file__).resolve().parents[8] / 'assets/robots/zj_v3/robot.usd'),
)

ZJV3_JOINTS = [
    "FAR_ABAD_JOINT", "FAR_HIP_JOINT", "FAR_KNEE_JOINT", "FAR_FOOT_JOINT",
    "FBL_ABAD_JOINT", "FBL_HIP_JOINT", "FBL_KNEE_JOINT", "FBL_FOOT_JOINT",
    "RAR_ABAD_JOINT", "RAR_HIP_JOINT", "RAR_KNEE_JOINT", "RAR_FOOT_JOINT",
    "RBL_ABAD_JOINT", "RBL_HIP_JOINT", "RBL_KNEE_JOINT", "RBL_FOOT_JOINT",
]

ZJV3_FEET = ["FAR_FOOT_LINK", "FBL_FOOT_LINK", "RAR_FOOT_LINK", "RBL_FOOT_LINK"]

ZJV3_CFG = ArticulationCfg(
    prim_path="{ENV_REGEX_NS}/Robot",
    spawn=sim_utils.UsdFileCfg(
        usd_path=ZJV3_USD_PATH,
        activate_contact_sensors=True,
        rigid_props=sim_utils.RigidBodyPropertiesCfg(
            disable_gravity=None, max_depenetration_velocity=10.0, enable_gyroscopic_forces=True
        ),
        articulation_props=sim_utils.ArticulationRootPropertiesCfg(
            enabled_self_collisions=False, solver_position_iteration_count=8, solver_velocity_iteration_count=2
        ),
    ),
    init_state=ArticulationCfg.InitialStateCfg(
        pos=(0.0, 0.0, 0.62), joint_pos={".*": 0.0}, joint_vel={".*": 0.0}
    ),
    actuators={
        "abad": ImplicitActuatorCfg(joint_names_expr=[".*_ABAD_JOINT"], stiffness=60.0, damping=1.0),
        "hip_knee": ImplicitActuatorCfg(
            joint_names_expr=[".*_(HIP|KNEE)_JOINT"], stiffness=120.0, damping=1.0
        ),
        "wheel": ImplicitActuatorCfg(joint_names_expr=[".*_FOOT_JOINT"], stiffness=60.0, damping=0.5),
    },
)
