# ZJ V3 自有 RL 基线

当前已实现独立抗扰动站立任务 `Isaac-ZJV3-Stand-v0`。
使用 `C:\Users\ROG\.conda\envs\isaacsim\python.exe`，在 `E:\isaac-lab` 下运行：

```powershell
& C:\Users\ROG\.conda\envs\isaacsim\python.exe IsaacLab/scripts/my/zj_v3_stand.py --mode train --num_envs 128 --iterations 300 --headless
```

奖励公式、参数及前端接口说明见
`source/isaaclab_tasks/isaaclab_tasks/manager_based/locomotion/velocity/config/zj_v3/STANDING_GUIDE.md`。
同目录的 `stand_parameters.json` 和 `stand_parameters.schema.json` 是可编辑参数与验证规范。
所有训练、评估与导出记录保存到 `E:\isaac-lab\zj_v3_runs`。

下文是早期速度任务的记录；直线前进将在站立任务之后独立处理。

任务注册名：`Isaac-ZJV3-Velocity-v0`。它使用同一台机器狗的
`ZJ_V3_URDF_V1_1_isaac.usd`，16 个关节位置偏移作为动作，观测包含机体速度、姿态、速度命令、关节状态和上一动作。
初始阶段使用平地和速度跟踪，命令覆盖前后、横移和偏航；后续再切换粗糙地形、坡面、障碍物和围墙。

PD 初值来自 RK3588 快照：ABAD `Kp=60,Kd=1`，髋/膝 `Kp=120,Kd=1`，足端轮 `Kp=60,Kd=0.5`。

## 运行

先确保 Isaac Lab 依赖（`gymnasium`、`rsl-rl-lib` 和 Isaac Sim Python 包）安装在 `isaaclab.bat` 实际使用的 Python 环境中，然后在 IsaacLab 目录执行：

```powershell
$env:ZJV3_USD_PATH = 'D:\xwechat_files\wxid_dw65v2dasu9u22_4b64\msg\file\2026-07\ZJ_V3_URDF_V1_1\ZJ_V3_URDF_V1_1_isaac.usd'
./isaaclab.bat -p scripts/reinforcement_learning/rsl_rl/train.py --task Isaac-ZJV3-Velocity-v0 --num_envs 256 --max_iterations 2000
```

单机可视化检查：

```powershell
./isaaclab.bat -p scripts/reinforcement_learning/rsl_rl/play.py --task Isaac-ZJV3-Velocity-Play-v0 --num_envs 1
```

`zj_v3_import_test.py` 用于只检查 Gym 注册，`zj_v3_raw_model_probe.py` 用于检查 raw 快照中是否有可实际读取的 RKNN 文件。
