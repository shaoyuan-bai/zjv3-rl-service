# ZJ V3 抗扰动站立训练接口文档

版本：v1.1；日期：2026-10-27；任务：`Isaac-ZJV3-Stand-v0`。

**实现状态：第2至第7节的15个HTTP端点均已实现于`integrations/rl_service`。项目根目录运行`start_rl_service.cmd`，接口默认位于`http://127.0.0.1:8000/api/v1`；Swagger为`/docs`，OpenAPI为`/openapi.json`。服务仅监听本机。** 示例ID/时间为格式示例。第8节是可独立使用的CLI/Python/模型接口。直线前进、趴卧起身和真机控制不在本版本范围内。部署配置与可迁移打包见项目根目录`README_RL.md`和`docs/deployment/RL_DEPLOYMENT.md`。

## 1. 公共约定

- 建议本地地址：`http://127.0.0.1:8000/api/v1`。以下路径均相对该地址。
- JSON 使用 UTF-8，发送请求体时设置 `Content-Type: application/json`；时间使用带时区的 RFC3339，例如 `2026-10-27T10:00:00+08:00`。
- ID 为服务生成的不透明字符串；URL 中的 ID 不能替换为任意文件路径。`null` 表示暂不可用，不能当作0。
- 默认配置可监听训练电脑LAN地址；所有请求都必须同时通过API令牌和`allowed_client_ips`白名单。令牌使用`Authorization: Bearer <token>`或`X-API-Key: <token>`，令牌来自`RL_SERVICE_API_TOKEN`（实际环境变量名由`api_token_env`指定），不得写进JSON或Git。
- 未列出的字段返回422；不允许NaN、Infinity、隐式字符串转数字。参数是否必填以表格为准。
- 成功响应（下载文件除外）：`{"request_id":"req_001","data":...}`。每个接口下文描述的是 `data`。
- 失败响应：`{"request_id":"req_001","error":{"code":"VALIDATION_ERROR","message":"参数校验失败","details":[{"path":"/rewards/orientation/weight","message":"必须小于等于0"}]}}`。
- `request_id:string` 为请求跟踪ID；错误 `code:string`、`message:string` 必返；`details:array<{path:string,message:string}>` 必返，无逐字段错误时为空数组。`path` 使用JSON Pointer。

| HTTP状态 | error.code | 含义 |
|---|---|---|
| 400 | BAD_REQUEST | JSON格式错误或游标非法 |
| 404 | NOT_FOUND | 配置、任务或产物不存在 |
| 409 | REVISION_CONFLICT | 配置已被其他操作修改 |
| 409 | RESOURCE_BUSY | GPU已有活动任务，本版本不排队 |
| 409 | RUN_NOT_READY | 结果/产物尚未生成 |
| 409 | INVALID_STATE | 当前任务状态不允许该操作 |
| 422 | VALIDATION_ERROR | 字段、范围、业务关联校验失败 |
| 500 | INTERNAL_ERROR | 服务内部异常 |
| 503 | SIMULATOR_UNAVAILABLE | Python、Isaac Sim、CUDA或资源根目录不可用 |

## 2. 接口总览（已实现）

| 方法 | 路径 | 用途 | 成功状态 |
|---|---|---|---:|
| GET | /health | 服务与运行环境检查 | 200 |
| GET | /standing/schema | 获取JSON Schema | 200 |
| GET | /standing/defaults | 获取默认参数 | 200 |
| POST | /standing/validate | 校验完整参数 | 200 |
| POST | /standing/configs | 保存新配置 | 201 |
| GET | /standing/configs/{config_id} | 读取配置 | 200 |
| PUT | /standing/configs/{config_id} | 完整替换配置 | 200 |
| POST | /standing/runs | 启动训练/评估/PD/物理验证 | 202 |
| GET | /standing/runs | 分页查询任务 | 200 |
| GET | /standing/runs/{run_id} | 查询任务状态 | 200 |
| POST | /standing/runs/{run_id}/cancel | 取消活动任务 | 202 |
| POST | /standing/runs/{run_id}/restart | 从完整检查点新建续训/评估任务 | 202 |
| GET | /standing/runs/{run_id}/logs | 增量读取日志 | 200 |
| GET | /standing/runs/{run_id}/result | 获取结果 | 200 |
| GET | /standing/runs/{run_id}/artifacts | 枚举产物 | 200 |
| DELETE | /standing/runs/{run_id}/artifacts | 清理终态任务产物 | 200 |
| GET | /standing/runs/{run_id}/artifacts/{artifact_id}/download | 下载产物 | 200 |

## 3. 公共数据结构

### 3.1 Parameters：完整环境参数

对应同目录 `stand_parameters.json`；权威结构与范围为 `stand_parameters.schema.json`。文末附全部数值字段表。

| 字段 | 类型 | 必填 | 意义 |
|---|---|---|---|
| schema_version | integer，固定1 | 是 | 参数格式版本，不等于配置修订号 |
| robot | object | 是 | 高度、参考站姿、动作尺度 |
| disturbance | object | 是 | 外力大小、方向范围、持续时间、课程 |
| termination | object | 是 | 失败阈值 |
| reset | object | 是 | 重置随机偏差 |
| rewards | object | 是 | 13项惩罚，键固定，不能自行增加新奖励 |
| alive_weight | number | 是 | 存活奖励，每秒权重 |

每个 `rewards.{reward_key}` 都包含以下字段：

| 字段 | 类型 | 必填 | 意义/约束 |
|---|---|---|---|
| enabled | boolean | 是 | 是否启用该项 |
| weight | number | 是 | [-1000,0]，越负惩罚越强 |
| tolerance | number | 是 | [0,1000]，原始误差容忍区 |
| scale | number | 是 | (0,10000]，误差归一化尺度 |
| cap | number | 是 | (0,10000]，归一化误差上限 |
| label | string | 是 | 前端显示名称，不参与计算 |
| description | string | 是 | 奖励意义，不参与计算 |
| unit | string | 是 | 原始误差单位，不参与计算 |
| formula | string | 是 | 展示文本，不会作为代码执行 |
| editable | object | 是 | 展示元数据，不是校验的权威依据；服务须以Schema校验 |
| axis_weights | number[3] | 否，仅angular_speed允许 | 世界xyz平方误差权重，[0,10]，缺省均为1 |
| joint_weights | number[12或16] | 否，仅joint_pose、torque、action_rate允许 | 每元素[0,10]，缺省均为1；joint_pose长度12，其他16 |
| safety_margin_rad | number | 否，仅joint_limits允许 | [0,0.2]，软限位向内收缩量，缺省0 |

普通惩罚：`e=clamp((error-tolerance)/scale,0,cap)`，`reward=weight*e²`；body_contact、fall使用`weight*e`。各项按控制周期0.02秒积分。alive单独计算。关节顺序以该次运行`policy_io.json`为准；joint_pose去掉4个FOOT轮关节。

跨字段校验：四组外力区间必须满足下界≤上界；`minimum_height_m < height_m < spawn_height_m+0.1`；所有数字有限；未知字段、奖励键和非法向量长度均拒绝。HTTP部分更新应由前端读完整配置、修改后PUT；本版本不定义PATCH。

### 3.2 Config：已保存配置

| 字段 | 类型/可空 | 意义 |
|---|---|---|
| config_id | string | 服务生成的配置ID |
| name | string | 配置名称，1–100字符 |
| revision | integer≥1 | 每次成功替换增加1，用于并发保护 |
| created_at / updated_at | string | 创建/修改时间 |
| parameters | Parameters | 完整参数，包含显示元数据 |

### 3.3 Run：任务记录

| 字段 | 类型/可空 | 意义 |
|---|---|---|
| run_id | string | API任务ID；实际本地目录名见run_directory |
| mode | train / eval / pd / verify | 模式 |
| status | starting / running / cancelling / succeeded / failed / cancelled | 状态；后三项为终态 |
| created_at | string | 接收时间 |
| started_at / finished_at | string或null | 子进程启动/退出时间 |
| exit_code | integer或null | 子进程退出码；运行中为null |
| config_id / config_revision | string或null / integer或null | 显式配置来源；自动选检查点快照时均为null |
| parameter_source | config / checkpoint_snapshot / defaults | 参数选择来源 |
| parameters_artifact_id | string或null | 本次最终参数快照ID；目录创建前为null |
| request | object | 规范化的启动参数，结构同5.1；缺省值已填充 |
| run_directory | string或null | 本地运行目录；启动未完成时为null |
| progress | object | 见下表 |
| error | object或null | 失败时含code:string、message:string；其他状态为null |

`progress`固定字段：`current_iteration:integer|null`、`target_iterations:integer|null`、`simulation_time_s:number|null`、`target_seconds:number|null`。训练的iteration按**本次请求新增迭代数**计数，从0开始；目标为iterations。非训练迭代字段为null。无法可靠解析时当前值为null，禁止用墙钟时间推算仿真进度。训练的秒数字段为null；评估/PD的秒数目标为seconds；verify均为null。

本地import-run登记的历史任务，其request额外含`imported:true`，mode保持原模式；无法核实的iterations和进度字段为null，不能将其当作0。

成功完成表示主流程完成。训练导出ONNX失败时，训练仍可成功，导出失败通过结果`export_status`报告，不能将不存在的导出文件标为可下载。

## 4. 环境、参数与配置接口

### 4.1 GET /health

无路径、查询参数和请求体。

返回：`status:"ready"|"unavailable"`、`task_id:string`、`python_available:boolean`、`isaacsim_available:boolean`、`cuda_available:boolean`、`gpu_name:string|null`、`active_run_id:string|null`、`message:string|null`。status不可用时返回503，响应体仍为公共错误结构，检查详情置于error.details。ready表示能运行，不表示GPU空闲。

### 4.2 GET /standing/schema

无参数/请求体。返回：`schema_version:integer=1`、`schema:object`（完整Draft 2020-12 Schema）、`cross_field_rules:string[]`（3.1跨字段约束）。服务返回的schema应增加`$schema:"https://json-schema.org/draft/2020-12/schema"`，不改变现有字段约束。失败：500。

### 4.3 GET /standing/defaults

无参数/请求体。返回：`task_id:string`、`parameters:Parameters`。返回项目默认文件的完整内容，未应用任何运行时pushes覆盖。失败：500。

### 4.4 POST /standing/validate

请求体：`parameters:Parameters`，必填。不保存配置，不启动模拟器。

```json
{"request_id":"req_001","data":{"valid":true,"schema_version":1}}
```

返回字段：`valid:boolean`（成功固定true）、`schema_version:integer`。不合法返回422和公共错误体，不使用200+valid=false；JSON错误返回400。示例：`error.details[0].path="/disturbance/duration_s"`。

### 4.5 POST /standing/configs

请求体：`name:string`（必填，1–100字符）、`parameters:Parameters`（必填完整配置）。名称允许重复，以config_id区分。

返回201，`data`为完整Config。失败：400/422/500。

### 4.6 GET /standing/configs/{config_id}

路径参数：`config_id:string`，必填。无查询参数/请求体。返回完整Config。失败：404/500。

### 4.7 PUT /standing/configs/{config_id}

路径参数：`config_id:string`，必填。

请求体：`expected_revision:integer≥1`（必填）、`name:string`（必填，1–100字符）、`parameters:Parameters`（必填完整替换）。更新前先校验再原子保存；revision不符返回409，不覆盖他人改动。

返回完整Config，新revision=旧revision+1。失败：400/404/409/422/500。已有训练的参数快照不受影响；此接口不在线修改正在运行的环境或模型。

## 5. 任务管理接口

### 5.1 POST /standing/runs

请求头：`Authorization: Bearer <token>`或`X-API-Key: <token>`必填；建议必须提供`Idempotency-Key`（1–128字符）。同一Key和相同请求体重复提交返回同一Run；同一Key不同请求体返回409 `IDEMPOTENCY_CONFLICT`。幂等记录持久化于state.json，服务重启后仍有效。

请求体：

| 字段 | 类型 | 必填/默认 | 约束和意义 |
|---|---|---|---|
| mode | string枚举 | 是 | train / eval / pd / verify |
| config_id | string | 否，null | 指定保存配置；不能与config_revision单独出现 |
| config_revision | integer≥1 | config_id非null时必填 | 与当前配置修订不符返回409 |
| checkpoint | object | 否，null | `{source_run_id:string,artifact_id:string}`，两个子字段均必填；仅接受本服务登记的可加载训练检查点，不接受ONNX/TorchScript |
| num_envs | integer | 否，train=128；eval/pd=32；verify=2 | 服务策略限制1–256，verify固定2 |
| iterations | integer | train可选，默认300 | 1–100000，本次新增训练迭代数；非train不得传 |
| seconds | number | eval/pd可选，默认20 | [0.02,3600]，评估仿真时间，必须为0.02整数倍；其他模式不得传 |
| pushes | off / mild / full | 否，full | off关外力；mild强制水平10–35N；full使用配置原值，不会强制enabled=true |
| seed | integer | 否，42 | [0,2147483647]，随机种子 |
| video | boolean | 否，false | 仅eval/pd允许true；HTTP版要求num_envs=1 |
| diagnostics | boolean | 否，false | 输出详细状态到日志 |

上述范围是**已实现HTTP服务的输入限制**，CLI现有argparse不保证全部同样校验。服务固定以headless=true、device=cuda:0启动，不开放任意启动命令/目录参数。

模式规则：eval必须有checkpoint；train可选checkpoint用于续训；pd/verify不得有checkpoint。verify固定关闭随机推力以运行确定性物理检查，故其pushes缺省规范化为off，显式非off拒绝。

配置选择顺序：显式config_id → 检查点所属运行的parameters.json → 默认配置。自动选择检查点快照时若文件缺失，HTTP服务返回422，要求用户显式指定配置，避免误配。显式配置的关节/观测接口必须与检查点兼容，不兼容返回422或在初始化失败时将任务置failed。

服务先冻结配置，再启动子进程；保存的是**最终生效快照**。eval/pd/verify关闭观测噪声，覆盖warmup_s=0、ramp_s=0.02；eval/pd把episode_length_s设为seconds。pushes覆盖最后应用。更改同名配置不会影响已启动任务。全局最多1个活动仿真任务，忙时返回409。

训练请求示例：

```json
{"mode":"train","config_id":"cfg_001","config_revision":1,"num_envs":128,"iterations":300,"pushes":"full","seed":42}
```

评估请求示例：

```json
{"mode":"eval","checkpoint":{"source_run_id":"run_train_001","artifact_id":"artifact_model_final"},"num_envs":32,"seconds":20,"pushes":"full","seed":123,"video":false}
```

返回202，`data`为Run，初始status=starting、未知字段为null。202仅表示请求已接收；Isaac Sim初始化和加载失败通过任务状态返回。失败：400/404/409/422/503。

### 5.2 GET /standing/runs

查询参数：`limit:integer`（可选，默认20，1–100）、`cursor:string`（可选，上一页next_cursor）、`mode:string`（可选，四种模式之一）、`status:string`（可选，七种状态之一）。无请求体。

返回：`items:Run[]`、`next_cursor:string|null`。按created_at倒序，时间相同按run_id排序；游标保留相同筛选条件，新记录不重复插入已读页。没有更多结果时next_cursor=null。失败：400/422/500。

### 5.3 GET /standing/runs/{run_id}

路径参数：`run_id:string`，必填。无查询参数/请求体。返回Run。失败：404/500。建议前端每2秒轮询，终态后停止。

### 5.4 POST /standing/runs/{run_id}/cancel

路径参数：`run_id:string`，必填；无请求体。starting/running变为cancelling；cancelling重复调用幂等，仍返回202和Run。已终态返回409 INVALID_STATE，不将已成功任务改为取消。

只有该run对应子进程可被终止；等待进程退出后标记cancelled。未完成检查点/视频可能不可用，不能保证取消时生成model_final.pt，也不提供暂停或断点续跑保证。失败：404/409/500。

### 5.5 POST /standing/runs/{run_id}/restart

无请求体。原任务必须是终态并拥有ready的`model_final.pt`；服务创建新的Run，不修改原任务。train从检查点续训，eval从检查点重新评估，pd重新运行PD对照；verify无检查点时不支持重启。失败：404/409/503。新任务仍受单GPU锁和配置快照规则约束。

## 6. 日志、结果与下载

以下所有接口均需路径参数`run_id:string`（必填）。

### 6.1 GET /standing/runs/{run_id}/logs

查询参数：`cursor:string`（可选，缺省从头读取，客户端不得自行计算）、`limit:integer`（可选，默认200，1–1000，条数）。无请求体。

返回：`items:array<{sequence:integer,text:string}>`、`next_cursor:string`、`eof:boolean`。sequence从0递增；text包含一条日志文本，非空行亦保留；合并stdout/stderr，不承诺恢复两路之间的绝对时序。eof=true表示任务已终态且日志已全部读取；运行中无新增日志返回空items、原next_cursor、eof=false。进度不依赖日志到达速度。失败：400/404/422/500。

### 6.2 GET /standing/runs/{run_id}/result

无查询参数/请求体。running/starting/cancelling返回409 RUN_NOT_READY；failed/cancelled返回409 INVALID_STATE，详情从Run.error和logs读取。

成功返回共同字段：`mode:string`、`run_id:string`、`metrics:object`、`warnings:string[]`。metrics按模式区分如下；warnings缺省[]。

**eval / pd：metrics对应evaluation.json**

| 字段 | 类型/单位 | 含义 |
|---|---|---|
| mode | eval / pd | 评估控制方式 |
| checkpoint | string或null | 当前文件中为实际本地路径，PD为null；HTTP适配层须改为登记的产物ID或null，不泄漏服务器路径 |
| push_profile | off / mild / full | 启动时外力档位；实际范围以快照为准 |
| num_envs | integer | 并行环境数 |
| duration_s | number，秒 | 请求评估时长 |
| seed | integer | 随机种子 |
| survival_fraction | number，[0,1] | 初始回合整个评估期间未触发失败的比例 |
| mean_first_failure_or_timeout_s | number，秒 | 首次失败时间或评估上限的跨环境平均 |
| pushes_started | integer | 触发的推力次数 |
| recoveries_detected | integer | 撤力后满足稳定判据的次数，包括重置后回合 |
| mean_recovery_s | number或null，秒 | 已成功恢复样本平均恢复耗时；无样本时null |
| recovery_definition | string | 判据文字说明 |
| series | SeriesPoint[] | 每0.5秒采样，首项time_s=0；采样在一步推进后记录，时间标记与状态有最多0.02秒偏差 |

SeriesPoint固定字段：`time_s:number`、`mean_height_m:number`、`mean_tilt_rad:number`、`mean_anchor_error_m:number`、`mean_yaw_error_rad:number`、`mean_speed_mps:number`、`push_active:integer`（当前受推环境数量）。平均值包含失败重置后的状态。

恢复判据为撤力后连续0.3秒：倾角<0.15rad、线速度<0.15m/s、角速度<0.3rad/s、位置误差<0.2m、偏航误差<0.2rad；耗时含0.3秒保持。恢复次数/推力次数不能直接作为严格成功率，因末次推力可能未结束、恢复可能被下次推力打断，且统计包含重置后回合。

**train：metrics由服务汇总产物生成（当前CLI没有train_result.json）**

`requested_iterations:integer|null`、`completed_iterations:integer|null`（导入历史任务时可能未知）（本次新增）、`final_checkpoint_artifact_id:string`、`export_status:"succeeded"|"failed"`、`torchscript_artifact_id:string|null`、`onnx_artifact_id:string|null`、`export_error:string|null`。导出以文件存在且无export_error.txt判定；训练成功不等于抗扰动指标通过，应另外eval。服务尚未独立校验导出数值时warnings须提示“导出一致性未验证”。

**verify：metrics对应verification.json**

`measured_impulse_ns:number`（测量冲量，N·s）、`expected_impulse_ns:number`（预期冲量，N·s）、`passed:boolean`。当前验证还通过断言检查撤力/重置清零和奖励算术；失败会抛异常，任务标failed，不生成成功结果。JSON中的ns表示N·s，不是纳秒。

失败：404/409/500。结果文件损坏返回500，不能伪造默认零值。

### 6.3 GET /standing/runs/{run_id}/artifacts

无查询参数/请求体。返回：`items:Artifact[]`，未生成时可为空；活动任务可以查询。失败：404/500。

Artifact固定字段：`artifact_id:string`、`name:string`（显示用文件名）、`kind:string`、`content_type:string`、`size_bytes:integer≥0`、`sha256:string`（小写64位hex）、`ready:boolean`、`download_url:string|null`（相对API根路径）。ready=false时download_url=null。当前采用保守策略：仿真进程退出前所有产物均不可下载，日志从logs接口读取；视频仅任务成功后ready。平台下载后必须自行复核size_bytes和sha256。

| kind | 文件示例 | content_type |
|---|---|---|
| checkpoint | model_final.pt、model_*.pt | application/octet-stream |
| torchscript | exported/policy.pt | application/octet-stream |
| onnx | exported/policy.onnx | application/octet-stream |
| parameters | parameters.json | application/json |
| policy_io | policy_io.json | application/json |
| evaluation | evaluation.json | application/json |
| verification | verification.json | application/json |
| export_verification | export_verification.json（另行校验后才有） | application/json |
| video | standing.mp4 | video/mp4 |
| environment / agent | env.yaml / agent.yaml | application/yaml |
| export_error | export_error.txt | text/plain; charset=utf-8 |
| log | 服务收集的运行日志 | text/plain; charset=utf-8 |

### 6.4 GET /standing/runs/{run_id}/artifacts/{artifact_id}/download

额外路径参数：`artifact_id:string`（必填）。无查询参数/请求体。返回200，原始文件字节流，**不套JSON成功响应**；Content-Type取产物类型，Content-Length为实际字节数，Content-Disposition提供下载文件名。本版不承诺Range分段请求。

仅可下载登记在该run下且ready=true的产物。404表示ID不属于该run或文件缺失；409 RUN_NOT_READY表示尚在写入；其他500。服务不能将用户输入直接拼接为文件系统路径。

### 6.5 DELETE /standing/runs/{run_id}/artifacts

仅终态任务可清理。请求体可选但必须是对象：`artifact_ids:string[]`指定删除集合；`keep_kinds:string[]`指定保留类型。两者均省略表示删除该Run的全部登记文件；平台应先完成归档和SHA256校验。返回`run_id`、`deleted_artifact_ids:string[]`、`remaining_artifacts:Artifact[]`。删除不可恢复；活动任务返回409 `INVALID_STATE`，未知字段/非数组返回422。

## 7. 前端调用顺序

1. GET /health确认环境；GET /standing/schema和/defaults建立表单。
2. 修改完整parameters，POST /validate校验；POST /configs保存并获得config_id与revision。
3. 后续编辑GET配置、完整PUT并传expected_revision；保存冲突后提示重载。
4. POST /runs启动训练；轮询Run和增量logs，终态后读取result与artifacts。
5. 选择checkpoint产物创建eval请求。固定种子对照PD；记录每次最终parameters.json。
6. 前端显示恢复时间null为“无已恢复样本”，不能显示0秒；训练成功与评估成功分别展示。

## 8. 已实现的本地调用接口

### 8.1 Python参数校验

文件：同目录`stand_settings.py`。该模块不需要启动Isaac Sim。

- `validate_settings(p: dict) -> dict`：传入完整Parameters；成功返回原对象本身，不复制、不保存。失败抛`jsonschema.ValidationError`（结构/字段范围）或`ValueError`（非有限值/关联规则），不是HTTP错误对象。
- `load_settings() -> dict`：无函数参数。先读取环境变量`ZJV3_STAND_CONFIG`指向的JSON，未设置则用同目录默认JSON；返回校验后的Parameters。失败还可能抛`FileNotFoundError`、`PermissionError`、`json.JSONDecodeError`。

### 8.2 CLI入口

工作目录`E:\isaac-lab`，Python：`C:\Users\ROG\.conda\envs\isaacsim\python.exe`，脚本：`IsaacLab/scripts/my/zj_v3_stand.py`。

| 参数 | 类型 | 默认 | 意义 |
|---|---|---|---|
| --mode | train/pd/eval/verify | train | 执行模式 |
| --config | string，本地JSON路径 | 无 | 显式配置；优先级最高 |
| --checkpoint | string，本地.pt路径 | 无 | eval必需，train用于续训；CLI加载失败直接异常退出 |
| --run_dir | string，本地输出目录 | 无 | 后端指定目录；可预先包含input_parameters.json，但拒绝覆盖已有结果 |
| --num_envs | integer | 128 | 并行环境数；verify建议2 |
| --iterations | integer | 300 | train本次新增迭代数；其他模式不使用 |
| --seconds | number | 40 | eval/pd时长；其他模式不使用 |
| --pushes | off/mild/full | full | 与5.1相同覆盖语义；verify实际检查由验证脚本控制 |
| --seed | integer | 42 | 随机种子 |
| --diagnostics | flag | false | 增加物理/关节诊断日志 |
| --video | flag | false | eval/pd输出视频，自动启用相机；CLI不会强制num_envs=1 |
| --headless | AppLauncher flag | 不传则启用GUI | 后端调用需显式传入 |
| --device | AppLauncher string | cuda:0 | 仿真设备，当前验证使用GPU |

AppLauncher还注入其他通用参数，以本机`--help`为准，不属于HTTP公开输入。

CLI参数选择：有--checkpoint且未传--config时，若检查点同目录存在parameters.json自动加载；若不存在，**当前CLI退回默认配置**，与5.1 HTTP服务的严格拒绝策略不同。CLI当前不拒绝所有无效模式组合，HTTP服务已增加5.1校验。

返回：进程退出码0表示主流程正常，异常一般为非0；不是直接返回JSON。stdout的`ZJV3_RUN <绝对路径>`提供运行目录，eval/pd的`ZJV3_RESULT <JSON>`提供不含series的摘要；完整数据从文件读取。训练导出失败会写export_error.txt，主训练仍可能返回0。

CLI默认输出目录：项目内`runtime/rl/runs/YYYYMMDD_HHMMSS_ffffff_MODE_PROFILE`，可通过`ZJV3_RUNS_DIR`覆盖。HTTP使用`data_dir/runs/{run_id}`，不使用时间戳作为目录主键。旧实验目录保持原位。

| 模式 | 主要新增输出 | 内容 |
|---|---|---|
| 全模式 | parameters.json、policy_io.json、env.yaml、agent.yaml | 最终环境参数快照、观测/关节/PD接口、环境/算法配置 |
| train | model_final.pt、周期检查点、exported/policy.pt与policy.onnx | 可续训检查点与推理模型；导出异常改写export_error.txt |
| eval / pd | evaluation.json | 6.2所列评估字段；本地checkpoint字段为路径 |
| eval / pd + --video | standing.mp4 | 环境0，25fps；画面显示实际外力向量 |
| verify | verification.json | 冲量与通过标记；失败抛异常 |

### 8.3 导出检查与参数测试

- `python IsaacLab/scripts/my/zj_v3_check_export.py <run_directory>`：唯一位置参数为训练目录；读取其exported/policy.pt与policy.onnx，校验ONNX结构及8组随机输入的一致性。成功退出0并写`export_verification.json`，字段`input_dim:integer`、`output_dim:integer`、`onnx_valid:boolean`、`samples:integer`、`max_absolute_error:number`；失败抛异常，不能将旧验证文件解释为当前模型的验证。
- `python IsaacLab/scripts/my/test_zj_v3_stand_settings.py`：无业务传参；返回unittest文本摘要和进程退出码，0为通过。

示例（PowerShell）：

```powershell
$py = 'C:\Users\ROG\.conda\envs\isaacsim\python.exe'
& $py IsaacLab/scripts/my/zj_v3_stand.py --mode train --num_envs 128 --iterations 300 --headless
& $py IsaacLab/scripts/my/zj_v3_stand.py --mode eval --checkpoint 'E:\isaac-lab\zj_v3_runs\20261027_101957_train_full\model_final.pt' --num_envs 32 --seconds 20 --seed 123 --pushes full --headless
```

### 8.4 已导出策略的推理接口

此处描述已训练目录`20261027_101957_train_full/exported`的模型文件接口，不是HTTP端点；不新增HTTP实时推理服务。

| 格式 | 调用/输入 | 返回 |
|---|---|---|
| TorchScript policy.pt | `policy(obs)`，obs为float32张量`[N,63]`，当前数值检查覆盖N=1 | float32张量`[N,16]`，确定性动作均值，无循环隐藏状态 |
| ONNX policy.onnx | 输入名`obs`，float32数组`[1,63]` | 输出名`actions`，float32数组`[1,16]`；导出固定batch=1，未启用动态轴 |

输入按下表拼接，索引从0开始、区间包含两端。推理不人工加训练噪声；模型内已包含导出时的观测归一化，不要在外面重复归一化。

| 索引 | 字段 | 长度 | 单位/坐标与计算 |
|---|---|---:|---|
| 0–2 | base_lin_vel | 3 | m/s，机体系xyz线速度 |
| 3–5 | base_ang_vel | 3 | rad/s，机体系xyz角速度 |
| 6–8 | projected_gravity | 3 | 机体系单位重力向量，水平站立约[0,0,-1] |
| 9–11 | velocity_commands | 3 | [vx,vy,wz]，当前站立全部为0 |
| 12–27 | joint_pos | 16 | rad，实际角度减reference_joint_positions_rad，按joint_state_order排列；不额外对轮角wrap |
| 28–43 | joint_vel | 16 | rad/s，实际速度减默认速度（当前默认0），按joint_state_order排列 |
| 44–59 | actions | 16 | 上一控制步已裁剪[-1,1]的动作，按action_joint_order排列；回合重置为0 |
| 60–62 | anchor_error | 3 | [世界x偏差m,世界y偏差m,wrap到[-π,π]的yaw误差rad]；本任务锚点为环境原点、yaw=0 |

输出不是力矩，也不是绝对关节角。先裁剪`a=clip(output,-1,1)`，按动作关节名称取对应参考角，得到`q_target[j]=q_reference[j]+0.2*a[j]`，送入关节位置PD。下一帧actions观测保存裁剪后的a，不能存q_target。控制周期0.02秒。实际动作尺度必须以该模型同目录policy_io.json为准。

**关节状态顺序与动作顺序不同，不能直接按相同数组下标套用参考角或PD参数。** 当前状态顺序为：先4个ABAD，再4个HIP，再4个KNEE，最后4个FOOT，每组腿序FAR/FBL/RAR/RBL。动作顺序为：每条腿ABAD/HIP/KNEE/FOOT，再按FAR/FBL/RAR/RBL排列。

policy_io.json文件结构：

| 字段 | 类型 | 含义 |
|---|---|---|
| observation_terms | string[8] | 上表观测项顺序 |
| observation_shapes | integer[8][1] | 每项形状，当前[[3],[3],[3],[3],[16],[16],[16],[3]] |
| joint_state_order | string[16] | 关节状态、参考角、PD及限制的排列顺序 |
| action_joint_order | string[16] | 输出动作及上一动作观测顺序 |
| reference_joint_positions_rad | number[16] | 参考关节角，按状态顺序 |
| stiffness_nm_per_rad | number[16] | PD比例增益，按状态顺序 |
| damping_nm_s_per_rad | number[16] | PD微分增益，按状态顺序 |
| effort_limits_nm | number[16] | 力矩限制，按状态顺序 |
| action_clip | number[2] | 动作裁剪下界、上界，当前[-1,1] |
| action_scale_rad | number | 动作角度尺度，当前0.2rad |
| control_dt_s | number | 策略周期，当前0.02秒 |
| drive_type | string | 当前force，力矩型PD驱动 |

模型自身不返回状态码；形状、类型或设备不匹配会由Torch/ONNX运行时抛异常。加载前校验维度，调用前检查输入有限，输出后检查有限并裁剪。实机还需里程计、零偏/坐标标定和独立控制保护；此文件接口不代表实机已适配。

## 9. 配置字段明细

下表按本次项目默认JSON与Schema生成。范围是Schema允许范围，不代表每组组合都能稳定训练；关联约束仍需执行。对象字段均必填，奖励额外字段的必填性见3.1。

### 9.1 机器人、扰动、重置、终止

| 字段路径 | 类型 | 默认值 | 允许范围 | 意义 |
|---|---|---|---|---|
| robot.height_m | number | 0.6 | [0.3,0.7] | 奖励目标高度，m |
| robot.spawn_height_m | number | 0.62 | [0.3,0.8] | 生成高度，m |
| robot.hip_rad | number | 0.35 | [-2.4,2.4] | 髋参考角，rad |
| robot.knee_rad | number | -0.7 | [-2.7,2.7] | 膝参考角，rad |
| robot.abad_rad | number | 0.0 | [-0.5,0.5] | 外展参考角，rad |
| robot.action_scale_rad | number | 0.2 | [0.01,0.8] | 动作位置偏移尺度，rad |
| disturbance.enabled | boolean | true | true / false | 启用随机外力 |
| disturbance.warmup_s | number | 24.0 | [0,100000] | 无推力预热累计仿真时间，秒 |
| disturbance.ramp_s | number | 96.0 | [0,100000] | 推力强度线性增长时间，秒 |
| disturbance.interval_s | array | [2.0,5.0] | 长度2，元素[0.02,60] | 推力结束后间隔[下界,上界]，秒 |
| disturbance.duration_s | array | [0.1,0.4] | 长度2，元素[0.02,2] | 推力持续时间[下界,上界]，秒 |
| disturbance.horizontal_force_n | array | [20.0,120.0] | 长度2，元素[0,1000] | 水平力大小[下界,上界]，N；方向均匀随机 |
| disturbance.vertical_force_n | array | [-10.0,10.0] | 长度2，元素[-500,500] | 竖直力[下界,上界]，N |
| disturbance.lever_arm_m | array | [0.15,0.1,0.08] | 长度3，元素[0,0.5] | 世界xyz作用点偏移上限，m |
| termination.minimum_height_m | number | 0.32 | [0.1,0.6] | 失败最低高度，m |
| termination.maximum_tilt_rad | number | 0.95 | [0.1,1.5] | 失败最大倾角，rad |
| termination.maximum_anchor_distance_m | number | 2.0 | [0.2,2] | 失败锚点距离，m |
| termination.contact_threshold_n | number | 10.0 | [1,1000] | 机身失败及非足端接触检测阈值，N |
| reset.joint_offset_rad | number | 0.025 | [0,0.15] | 初始关节角对称随机偏差，rad |
| reset.tilt_rad | number | 0.025 | [0,0.15] | 初始roll/pitch对称随机偏差，rad |
| alive_weight | number | 2.0 | [0,20] | 存活奖励每秒权重 |

### 9.2 各奖励默认值

| rewards下的键 | 原始误差意义 | 单位 | enabled | weight | tolerance | scale | cap |
|---|---|---|---|---|---|---|---|
| orientation | 重力投影水平分量范数，抑制侧倾/俯仰 | sin(rad) | true | -12.0 | 0 | 1 | 1 |
| height | 与目标高度的绝对误差 | m | true | -30.0 | 0.025 | 1 | 0.5 |
| horizontal_speed | 水平速度范数 | m/s | true | -1 | 0.03 | 1 | 3 |
| vertical_speed | 竖直速度绝对值 | m/s | true | -1 | 0 | 1 | 3 |
| angular_speed | 世界系角速度加权范数 | rad/s | true | -0.3 | 0.05 | 1 | 10 |
| position | 到固定锚点的水平距离 | m | true | -3.0 | 0.1 | 1 | 2 |
| heading | 零偏航角误差的绝对值 | rad | true | -1.0 | 0.05 | 1 | 3.142 |
| joint_pose | 12个腿关节参考角偏差的加权RMS | rad | true | -0.5 | 0.1 | 1 | 3 |
| action_rate | 相邻裁剪后动作差的加权范数 | action | true | -0.008 | 0 | 1 | 20 |
| torque | 实际关节力矩的加权范数 | Nm | true | -1e-05 | 0 | 1 | 1000 |
| joint_limits | 腿关节超软限位距离之和 | rad | true | -2 | 0 | 1 | 10 |
| body_contact | 超过阈值的非足端接触刚体数 | count | true | -1 | 0 | 1 | 20 |
| fall | 真实失败事件（排除时间到期） | event | true | -100 | 0 | 1 | 1 |

### 9.3 额外逐轴/关节参数

| 字段路径 | 类型 | 默认值 | 范围 |
|---|---|---|---|
| rewards.angular_speed.axis_weights | array | [1.0,1.0,1.0] | 长度3，元素[0,10] |
| rewards.joint_pose.joint_weights | array | [1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0] | 长度12，元素[0,10] |
| rewards.action_rate.joint_weights | array | [1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0] | 长度16，元素[0,10] |
| rewards.torque.joint_weights | array | [1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0,1.0] | 长度16，元素[0,10] |
| rewards.joint_limits.safety_margin_rad | number | 0.0 | [0,0.2] |

### 9.4 校验边界与修改生效

weight=0与enabled=false均可使惩罚为零；scale=0非法。tolerance/scale的单位与该项原始误差一致；cap无量纲。逐轴/关节系数乘在误差平方上，不直接乘角度/力矩本身。单位或formula说明文字被更改不会改变实际计算。

本版配置接口不开放网络结构、PPO学习率/熵系数、物理步长、PD增益和力矩上限的修改。它们在Python配置中定义，实际PD等由policy_io.json返回。未来若需调整，应扩展版本化Schema和服务校验，不能向现有JSON任意加键。
