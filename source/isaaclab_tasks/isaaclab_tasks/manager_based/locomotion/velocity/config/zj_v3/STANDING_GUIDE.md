# ZJ V3 抗扰动站立训练与奖励参数

本任务从带小幅姿态/关节误差的站姿开始，学习承重、保持平衡、抵抗有限时长随机推力。摔倒自动重置。不会从趴卧起身；直线前进仍是独立的下一任务。

前后端接口设计、请求参数、返回字段、错误码、现有CLI与模型输入输出见[接口文档](STANDING_API.md)。HTTP服务已实现；统一启动与可迁移部署入口见项目根目录README_RL.md。

任务名 `Isaac-ZJV3-Stand-v0`。使用 CUDA PhysX、200 Hz 仿真、50 Hz 策略、16 个关节位置偏移动作，动作裁剪到 [-1,1] 后乘 `robot.action_scale_rad`。轮关节继续由 PD 控制，不是机械锁死；12 个腿关节参与姿态与限位惩罚。

## 可编辑配置与前端

同目录 `stand_parameters.json` 是唯一站立参数入口。复制它并通过 `--config 绝对路径` 指定；每次运行保存完整 `parameters.json`、环境/算法 YAML、检查点和日志。修改只在下一次启动生效，续训也会读取新配置，请保留版本记录。前端可以读取 rewards 下的 label、description、unit、formula、editable；enabled/weight/tolerance/scale/cap 是实际计算字段，说明字段不影响计算。

每个普通惩罚采用 `e = min(max((error-tolerance)/scale,0),cap)`，贡献为 `weight * e²`；接触和摔倒为 `weight * e`。所有奖励再乘控制周期 0.02 s，按回合累计。权重绝对值越大惩罚越强；误差容忍范围越大，允许自由调整的空间越大；scale 越小惩罚越强；cap 限制极端状态。alive 项每秒提供 `alive_weight=2`，真实摔倒时不提供。这里的权重是初始实验值，效果以评估结果为准。

## 奖励逐项说明

| 配置键 | 含义 | 原始误差单位 | 权重 | 容忍 | scale | cap |
|---|---|---|---:|---:|---:|---:|
| orientation | 机体重力投影的水平分量，抑制侧倾和俯仰 | sin(rad) | -12.0 | 0 | 1 | 1 |
| height | 避免蹲伏或趴地获得稳定 | m | -30.0 | 0.025 | 1 | 0.5 |
| horizontal_speed | 受推后尽快停止漂移 | m/s | -1 | 0.03 | 1 | 3 |
| vertical_speed | 抑制上下弹跳 | m/s | -1 | 0 | 1 | 3 |
| angular_speed | 抑制滚转、俯仰和偏航晃动 | rad/s | -0.3 | 0.05 | 1 | 10 |
| position | 允许小范围恢复步，之后回到每回合固定锚点 | m | -3.0 | 0.1 | 1 | 2 |
| heading | 回到初始零偏航角 | rad | -1.0 | 0.05 | 1 | 3.142 |
| joint_pose | 只约束12个腿关节，允许轮转动和平衡调整 | rad | -0.5 | 0.1 | 1 | 3 |
| action_rate | 减少相邻控制帧指令突变 | action | -0.008 | 0 | 1 | 20 |
| torque | 惩罚所有关节实际施加力矩平方和 | Nm | -1e-05 | 0 | 1 | 1000 |
| joint_limits | 12个腿关节超出软限位的距离总和 | rad | -2 | 0 | 1 | 10 |
| body_contact | 惩罚机身及腿部触地，四个轮足接触不受罚 | count | -1 | 0 | 1 | 20 |
| fall | 仅真实失败计罚，时间上限重置不计罚 | event | -100 | 0 | 1 | 1 |

orientation 是重力投影水平分量的长度，即倾角正弦；倒置由单独的倾角终止条件处理。joint_pose 是腿关节相对参考角的 RMS。action_rate 是相邻帧裁剪到[-1,1]后的策略动作差的 L2 长度，尚未乘关节动作尺度。torque 是实际 applied_torque 的 L2 长度，所以平方后为所有关节力矩平方和。joint_limits 是12个腿关节越过软限位的角度总和。body_contact 是最近3个物理帧中超过接触阈值的非足端刚体数量。fall 使用 terminated（排除正常时间到期）。

位置/朝向锚点固定在各环境原点和零偏航角；初始化只随机 roll/pitch，不随机锚点位置/yaw。允许10 cm位置误差和少量关节偏移，恢复迈步不单独扣分。没有强制四足常接触或固定步态奖励。

策略观测包含机体线速度、角速度、重力投影、零速度命令、关节相对角/速度、上一动作及锚点 xy/yaw 误差。位置保持需要里程计估计，当前训练使用仿真真值，尚不能直接部署。

## 外力参数（独立于奖励）

| 参数 | 默认 | 意义 |
|---|---|---|
| enabled | true | 是否施加随机推力 |
| warmup_s | 24 | 累计控制仿真时间内不推，约50次PPO迭代 |
| ramp_s | 96 | 从零线性增加到满强度，约200次迭代 |
| interval_s | [2,5] | 每次推力结束后到下次推力的随机间隔，重置后也先等待 |
| duration_s | [0.1,0.4] | 推力持续时长；实际按0.02秒离散 |
| horizontal_force_n | [20,120] | 水平力大小，方向均匀随机0到2π |
| vertical_force_n | [-10,10] | 世界z轴力范围 |
| lever_arm_m | [0.15,0.10,0.08] | 世界系等效作用点相对质心xyz偏移上限；附加力矩为 r×F |

这里通过真正的力与力矩作用于 BASE_LINK，不直接修改机体速度。每环境独立时机/方向；重置立即清除外力。课程按累计时间推进，不是按成功率自动升级；若基线不稳定，应延长预热或先关闭外力。

## 机器人、重置与终止参数

robot.height_m=0.60 是奖励目标高度，spawn_height_m=0.62 是初始高度；hip_rad=0.35、knee_rad=-0.7、abad_rad=0 是初始参考角。PD使用raw中的初始值，ABAD 60/1、髋膝120/1、轮60/0.5，尚未实机标定。reset.joint_offset_rad=0.025 和 tilt_rad=0.025 是对称均匀初始误差上限。

termination.minimum_height_m=0.32、maximum_tilt_rad=0.95、maximum_anchor_distance_m=2.0、contact_threshold_n=10 控制失败条件/接触检测。机身触地、过低、倾角过大、远离锚点均终止；20秒时间到正常重置。终止阈值改变的是任务定义，不仅是奖励强弱。

## 运行（PowerShell，在 E:\isaac-lab 下）

```powershell
$py = 'C:\Users\ROG\.conda\envs\isaacsim\python.exe'
# 无外力固定PD基线
& $py IsaacLab/scripts/my/zj_v3_stand.py --mode pd --pushes off --num_envs 8 --seconds 20 --headless
# 抗扰动训练
& $py IsaacLab/scripts/my/zj_v3_stand.py --mode train --num_envs 128 --iterations 300 --headless
# 独立随机种子和满强度评估；替换检查点路径
& $py IsaacLab/scripts/my/zj_v3_stand.py --mode eval --checkpoint 'E:\isaac-lab\zj_v3_runs\运行目录\model_final.pt' --num_envs 32 --seconds 40 --pushes full --seed 123 --headless
# 去掉 --headless 可以观察；继续训练时传 --checkpoint
```

评估输出 evaluation.json：整段时间无摔倒比例、第一次失败或超时的平均时长、推力次数、连续达到稳定阈值0.3秒的恢复次数/时间，以及高度、倾角、位置、朝向、速度时间序列。恢复定义为推力结束后连续0.3秒同时满足倾角<0.15rad、速度<0.15m/s、角速度<0.3rad/s、位置误差<0.2m、朝向误差<0.2rad；恢复时间包括这0.3秒保持时间。评估仍在摔倒后重置，因此恢复计数覆盖重置后的回合；整体存活率按最初一回合统计。应对相同种子分别测无扰动、轻扰动、满扰动，并比较固定PD与策略。

尚未标定的因素包括电机延迟/饱和、真实摩擦、负载、结构柔顺和关节零偏。这一轮先验证仿真任务与训练，不向真机下发动作。

物理验证命令：`--mode verify --num_envs 2 --headless`。验证80N推力持续0.02秒应产生1.6N·s冲量，并检查撤力、重置清零、奖励容忍区/缩放/上限。参数边界测试运行 `IsaacLab/scripts/my/test_zj_v3_stand_settings.py`。

训练使用力矩型（force）关节驱动。导入USD的加速度型驱动不能直接套用raw中的力矩PD增益，已通过训练配置覆盖，不修改原文件。每次运行的policy_io.json记录观测项、关节状态顺序、动作顺序、参考角、PD和力矩限制。


逐轴/逐关节系数也可以调整：angular_speed.axis_weights 按世界xyz排列；joint_pose.joint_weights 对应 policy_io.json 的 joint_state_order 去掉 FOOT 的12个腿关节；torque.joint_weights 对应完整 joint_state_order；action_rate.joint_weights 对应 action_joint_order。它们在平方误差求和前相乘，默认均为1。joint_limits.safety_margin_rad 在软限位两侧向内收缩，默认0，范围0到0.2rad。修改这些字段同样在下次启动生效。stand_parameters.schema.json 可供前端做类型、长度、数值范围校验；stand_settings.py 额外验证上下界顺序、非有限数和高度关系。

当前第二版训练从零均值残差策略开始，即初始确定性输出等于已验证PD站姿；策略仍保留0.35的随机动作探索，熵系数0.003，动作偏移上限0.2rad。每次训练独立保存参数快照，不会把旧检查点的配置误当作新默认值。
