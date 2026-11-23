"""ZJ V3 locomotion configurations."""

import gymnasium as gym

from . import agents

gym.register(
    id="Isaac-ZJV3-Stand-v0",
    entry_point=f"{__name__}.stand_env:ZJV3StandEnv",
    disable_env_checker=True,
    kwargs={
        "env_cfg_entry_point": f"{__name__}.stand_env_cfg:ZJV3StandEnvCfg",
        "rsl_rl_cfg_entry_point": f"{agents.__name__}.rsl_rl_ppo_cfg:ZJV3StandPPORunnerCfg",
    },
)

gym.register(
    id="Isaac-ZJV3-Velocity-v0",
    entry_point="isaaclab.envs:ManagerBasedRLEnv",
    disable_env_checker=True,
    kwargs={
        "env_cfg_entry_point": f"{__name__}.flat_env_cfg:ZJV3FlatEnvCfg",
        "rsl_rl_cfg_entry_point": f"{agents.__name__}.rsl_rl_ppo_cfg:ZJV3PPORunnerCfg",
    },
)

gym.register(
    id="Isaac-ZJV3-Velocity-Play-v0",
    entry_point="isaaclab.envs:ManagerBasedRLEnv",
    disable_env_checker=True,
    kwargs={
        "env_cfg_entry_point": f"{__name__}.flat_env_cfg:ZJV3FlatEnvCfg_PLAY",
        "rsl_rl_cfg_entry_point": f"{agents.__name__}.rsl_rl_ppo_cfg:ZJV3PPORunnerCfg",
    },
)
