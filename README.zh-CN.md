# Hermes 飞书增强插件

[English](README.md)

这是一个**社区直接安装插件**，提供飞书/Lark 原生 `clarify` 卡片和话题根消息引用正文抑制。通过继承官方 `FeishuAdapter` 并替换同名 `feishu` 平台工厂实现；不会修改核心源码、增加模型工具、改写系统提示词、增加流式消息功能或另起一个机器人连接。

**不是 Hermes / Nous Research 官方插件，没有官方背书，也不符合官方插件目录准入。** 使用私有适配器/clarify 接口涉及目录规则 9；同名平台注册替换涉及规则 15。CLI 验证成功不等于目录接纳。原生插件与网关同进程、同权限运行，不是沙箱。

## 功能

- 单选：点击立即回答；多选：勾选、取消，再点击“提交”。
- “其他”：复用官方待回答项，切换到文本捕获。在**原聊天/原话题/原会话**中输入答案。不会把合成命令排到正在等待的 agent 后面。
- 回调必须提供正确的用户、聊天和原始卡片消息；缺失或不匹配时拒绝。群组按用户隔离、话题共享/按用户隔离遵循真实 session key；点击时重新检查官方群策略。
- 多选回调按平台 delivery token 去重；无 token 的多选操作拒绝处理，避免重投递反向切换。空提交、非法/布尔索引、过期、重复回答和被替换的待回答项均拒绝。
- 开放式问题继续使用文本；卡片发送失败时回退到官方编号文本。
- 超时/重置/文本回答结束时，支持网关调用 retirement hook，通过 SDK 的交互消息 patch 更新卡片。断开连接时清理自有状态并委托官方断连。
- 非本插件命名空间的回调完整交给父适配器，包括审批、更新确认及未知回调。普通消息、附件、流式行为和连接逻辑保持继承。

卡片状态仅在内存中；重启不恢复未完成卡片。网络异常可能让过期按钮仍可见，但无法回答失效项。

## 话题根消息上下文

群消息具有原生话题 `thread_id`，且最终解析出的 `reply_to_message_id` 等于原始
`root_id` 时，只清空 `reply_to_text`，让网关不再添加根消息引用前缀。
每一轮都适用，包括显式引用根消息、命令和媒体消息；非根消息引用保留完整正文。
私聊、普通群、缺少 root 或 reply ID 的消息不变，回复锚点和话题会话隔离不变。

multiplex 使用完全相同的无状态规则，不再有特殊路由、标记、sidecar、SQLite、
缓存、生命周期 hook 或上下文补注入。`/new` 正常清空上下文，之后也不会补回根消息。
这是明确接受的取舍：连第一轮也不自动注入根正文；重置后需要的详情请直接粘贴到新消息。
旧 `topic_root_context_once` 配置不再使用。不会迁移或删除现有运行时缓存；
切换版本前应先排空含旧引用标记的队列。详见 [VERIFICATION.md](VERIFICATION.md)。
本次未安装或重启。

最新离线验证：干净核心 `bf0203a794a07aac3ff764972ab9087baa4e4f4e`、受管 Python 3.14.9、
真实 Lark SDK，**42 项插件测试通过**，官方验证器退出 0、`ok: true`。
包括真实适配器规范化/网关引用格式化、无 topic hook 的发现/卸载、真实 SessionStore
和 `/new`；不是线上飞书验收或官方目录准入。

## 复用昨天的实现

`clarify.py` 基于已有 `FeishuClarifyMixin`：复用了卡片结构、每行三个按钮、多选切换/提交、Other、真实 clarify registry 解锁、卡片 retirement 协议。`tests/test_legacy.py` 迁移了原来的回归测试。

必须修改的部分：独立包导入、正式 `plugin.yaml` / `register(ctx)`、同名工厂的作用域登记、非自有回调透传、兼容性保护、严格身份校验、使用真实 session key（不再靠末尾是否 `ou_` 判断所有权）、去重与发送/退役竞态。这些不是重新实现一套网关。

## 兼容性与已有核心补丁

已验证的干净 Hermes 提交：`e06df9c2eae6901f4c88f464e0ae6e753c0428b8`，Windows / Python 3.14.7 / 实际安装的 `lark-oapi` SDK。这是已测试提交，不是跨版本兼容承诺；升级后应重新运行测试。飞书 SDK 依赖由 Hermes 自己的 setup/受管环境提供，本插件不自行安装依赖。

注册时调用官方 `register()`，只替换 `adapter_factory`；保留所有官方授权环境变量、setup、配置校验、依赖探测/安装器、YAML 桥接、独立发送器、消息长度等元数据。使用实际 PluginContext 的作用域和卸载账本，不写私有 registry 表，也不全局 monkeypatch。

若父适配器已有 `send_clarify` 覆盖，本插件不叠加：

- 发现 `plugins.platforms.feishu.clarify` 时明确报告**已有本地核心补丁**，不冒称官方原生支持。
- 其他上游/未知覆盖保持原状。
- 所需方法缺失时警告并不注册；内部导入路径缺失时由插件管理器报告加载错误，官方适配器保留。

当前机器上的旧核心补丁**没有删除或回滚**。请先备份、检查旧 adapter/mixin/测试，再只迁移自己确认的补丁；旧补丁仍在时，本插件故意不生效。旧卡片的回调命名空间不会迁移，切换版本前应完成或过期旧问题。

## 以后安装（本次未执行）

先审阅代码并选择正确的 Hermes profile，确认其实际 `HERMES_HOME`。保留内置飞书平台。把项目文件复制到 `<当前 HERMES_HOME>/plugins/feishu-enhanced/` 后：

```sh
hermes plugins enable feishu-enhanced
hermes plugins list
```

**自行发布 GitHub 后**，把 `YOUR_ACCOUNT` 换成真实账号：

```sh
hermes plugins install YOUR_ACCOUNT/hermes-plugin-feishu-enhanced --no-enable
hermes plugins enable feishu-enhanced
```

这只是操作说明，不代表已经安装、启用或重启。由你安排安全的网关重启时间；修改文件不会改变已运行的适配器。回滚使用 `hermes plugins disable feishu-enhanced`，随后安排重启；不要关闭官方飞书平台。卸载注册不会热替换已经创建的实例。

## 离线验证

用已经具备 Hermes 和飞书 SDK 依赖的受管 Python，以及**没有旧核心补丁的干净 Hermes checkout**：

```sh
/path/to/hermes/python scripts/verify.py \
  --hermes-root /path/to/clean/hermes-agent \
  --scratch /path/to/scratch \
  --report-dir /path/to/test-report
```

Windows / Git Bash 使用带引号的 `C:/.../python.exe` 路径。脚本在 scratch 下建立并清理临时 HERMES_HOME，不安装依赖、不需要凭据；执行 stdlib unittest 和真正的 `hermes plugins validate`，任一失败返回非零。

可用 `git archive HEAD --output=C:/.../scratch/hermes.tar` 导出干净核心并解压，不修改正在使用的 checkout。底层测试命令详见英文 README。测试包含真实 PluginManager 发现、工厂选择、作用域卸载、恢复官方延迟工厂；只模拟网络边界/观察父回调，使用真实 clarify registry。

验证器在已测试提交上退出 0，`ok: true`；仍明确警告私有核心导入（规则 9），平台为进程内运行。其“无运行时重新绑定”检查不证明规则 15 准入。不是完整上游回归测试。见 [VERIFICATION.md](VERIFICATION.md)。

## 仍需真实飞书验收

有意重启后，分别核对实际卡片 UI 与工具返回值：单选/重复点击/过期、多选勾选与取消后提交、Other 后在原话题输入、按用户隔离与共享话题、群策略、发送回退与超时/重置退役；并确认普通消息、附件、审批、更新确认和流式行为没有变化。话题首轮/后续轮及 `/new` 后均不应出现根引用前缀，非根引用完整保留；检查另一话题、私聊、普通群和 multiplex。离线通过不代表线上 UI/回调已经验收。

MIT；用户发布身份未知，因此使用通用 contributors 署名。没有发布仓库、修改运行配置或改动其他 profile。完整说明见 [README.md](README.md)。
