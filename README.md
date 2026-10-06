# astrbot_plugin_personated (拟人化综合伴侣插件)

一个为 AstrBot 设计的高可扩展“功能集合”插件。
- 模块一：**拟人化作息日程系统**，让机器人拥有真实生活作息与实时状态流转；
- 模块二：**特定群聊/私聊专属提示词注入系统**，支持为每个群聊/私聊单独配置专属提示词，在对话时每次注入，聊天窗口支持指令配置，WebUI 支持从“数据与日志-对话”中一键抓取并选择（展示群名称与群号/私聊人昵称）。

---

## 🌟 核心特性

### 1. 拟人化作息日程系统 (Personated Daily Schedule)
1. **每日定时生成作息日程**：每天指定时间（默认 `04:00`）根据机器人**人设提示词**由大模型自动规划当天的拟人化作息。若机器人离线，启动后自动补全。
2. **双轨模型指定与自动回退**：支持单独指定生成模型提供商，未指定或离线时自动回退对话大模型。
3. **自由时间段划分**：支持自定义任意时间段数量、名称及起止时间（24小时制 `HH:MM`），支持跨午夜时间段（如 `22:00` 至 `06:00`）。
4. **对话上下文实时注入**：对话时自动识别现实时间落入的时段，将活动内容与心理状态注入对话（推荐 `extra_user_content` 模式，保护 KV Cache 命中）。
5. **本地持久化与容错回退**：持久化保存于 `data/plugin_data/astrbot_plugin_personated/daily_schedules.json`，异常时自动启用拟人化兜底日程。

### 2. 特定群聊/私聊专属提示词注入 (UMO Prompt Injector)
1. **会话级个性化提示词**：每个群聊或私聊（基于 AstrBot `unified_msg_origin` UMO 统一标识）均可单独配置专属定制提示词。
2. **每次对话自动注入**：对话拦截钩子 `@filter.on_llm_request()` 毫秒级匹配当前会话，无感知注入定制提示词。支持多种注入模式：
   - 追加到系统提示词末尾 (`system_prompt`，推荐)；
   - 置于系统提示词开头 (`prepend_system`)；
   - 作为附加用户内容块 (`extra_user_content`)。
3. **聊天窗口便捷指令**：在聊天窗口直接发送 `/umo set <提示词>` 即可瞬间绑定当前群聊或私聊，亦可指定任意 UMO 进行增删改查。
4. **AstrBot 对话一键抓取**：WebUI 专属面板支持直接从 AstrBot 的“数据与日志-对话”及别名库中抓取全部活跃会话：
   - **群聊**：清晰展示【群名称】与【群号】；
   - **私聊**：清晰展示【对话人昵称】与 UMO 来源。
   - 告别繁琐手动查找与输入 UMO，一键点击「一键配置」即可为选定会话绑定提示词。
5. **快捷预设模板**：内置【群聊助手】、【严肃工作】、【幽默密友】、【傲娇角色】、【群规知识】等常用模板，一键套用微调。

---

## ⚙️ 配置说明 (`_conf_schema.json`)

可在 AstrBot WebUI 管理面板的“插件设置”中直接可视化配置：

| 配置项 | 类型 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `daily_generate_time` | string | `04:00` | 每日生成日程时刻（24h制 `HH:MM`） |
| `schedule_provider_id` | string | 空 | 指定生成模型提供商，留空则自动回退使用对话模型 |
| `inject_context_enabled` | bool | `true` | 是否在对话中自动注入当前日程状态 |
| `inject_mode` | string | `extra_user_content` | 日程注入模式：`extra_user_content`（推荐）或 `system_prompt` |
| `schedule_segments` | list | 6个常规时段 | 每日各时间段划分定义（ID、名称、起止时刻） |
| `custom_prompt_template` | text | 默认模板 | 自定义日程生成的 Prompt 模板 |
| `umo_prompt_injector_enabled` | bool | `true` | 是否启用特定群聊/私聊专属提示词注入功能总开关 |
| `umo_prompt_default_mode` | string | `system_prompt` | 专属提示词默认注入位置 (`system_prompt` / `extra_user_content` / `prepend_system`) |
| `umo_prompt_rules` | list | `[]` | 会话专属提示词规则列表（推荐直接在 WebUI 可视化面板中配置） |

---

## 💬 聊天交互指令

### 1. 拟人化日程管理 (`/schedule` 或 `/日程`)
| 指令 | 别名 | 描述 |
| :--- | :--- | :--- |
| `/schedule view` | `/日程 查看` | 查看今日完整的时段日程安排及当前生效状态 |
| `/schedule refresh` | `/日程 重新生成` | 立即强制重新生成今日的日程安排 |
| `/schedule status` | `/日程 状态` | 查看日程系统的运行状态、定时信息与生效模型 |
| `/schedule segments` | `/日程 时间段` | 查看当前配置的时间段划分列表 |

### 2. 特定会话专属提示词管理 (`/umo` 或 `/会话提示词`)
| 指令 | 描述 | 示例 |
| :--- | :--- | :--- |
| `/umo info` | 查看当前会话的 UMO、会话类型、群号/昵称与专属提示词配置 | `/umo info` |
| `/umo set <提示词>` | 为当前群聊/私聊设置专属提示词并立即生效 | `/umo set 请扮演热情贴心的群助手` |
| `/umo setumo <umo> <提示词>` | 显式指定 UMO 设置专属提示词 | `/umo setumo aiocqhttp:GroupMessage:123456 ...` |
| `/umo list` | 查看所有已配置专属提示词的会话列表及生效状态 | `/umo list` |
| `/umo toggle` | 切换当前会话专属提示词的启用/禁用状态 | `/umo toggle` |
| `/umo clear` | 清除当前群聊/私聊已绑定的专属提示词 | `/umo clear` |

---

## 🚀 可视化 WebUI 管理面板

插件内置了基于 AstrBot 官方标准的专属图形化控制台（双向兼容 `pages/` 与 `views/`，自适应 WebUI 亮色/暗色主题）：

1. **今日即时看板 (Live Board)**：
   - 实时呼吸灯状态徽章，高亮标识当前时刻正在生效的时段、具体活动与心理状态。
   - 24 小时流转时间轴卡片流，支持快速编辑当前状态或单项时段活动。
   - 一键触发大模型重新生成今日日程。
2. **日程查看与详细编辑 (Schedule Editor & Archive)**：
   - **日期快速切换**：支持前一天、后一天、回到今天、日期日历选择器以及历史已存档日期的快捷下拉列表。
   - **卡片流与表格双视图**：支持卡片视图与紧凑表格视图自由切换。
   - **全量增删改查 (CRUD)**：支持自由添加新作息条目、拖拽/上下排序、编辑活动 (Activity) 与心情 (State)、单项删除、整日重生成、彻底删除某日存档以及一键保存所有修改并持久化。
3. **作息规则与分段模板 (Rules & Templates)**：
   - 24 小时制每日自动生成时刻配置（`HH:MM`）。
   - 动态识别 AstrBot 可用大模型，一键下拉选择指定生成模型或回退对话模型。
   - 实时上下文注入开关与注入模式切换（`extra_user_content` / `system_prompt`）。
   - 可视化时间段划分模板表格（支持添加、排序、删除、跨夜识别与恢复默认预设）。
   - 高级自定义 Prompt 模板编辑。
4. **会话专属提示词注入 (UMO Prompt Injector)**：
   - **会话规则全景卡片流**：展示已配置会话的群聊/私聊徽标、平台标识、群号、完整 UMO、注入模式与提示词详情。
   - **从 AstrBot 对话中一键抓取**：弹窗自动抓取「数据与日志-对话」记录，群聊展示【群名称】与【群号】，私聊展示【对话人昵称】，支持关键词实时筛选与一键配置。
   - **多注入模式与模板预设**：可自由调整注入模式，并支持一键套用群聊助手、严肃工作、傲娇人设等常用预设。
   - **独立启用开关与全局总开关**：支持单规则即时开关与全局总开关。

---

## 📁 项目目录结构

```text
astrbot_plugin_personated/
├── metadata.yaml             # 插件元信息（支持平台、版本要求、pages/views 声明等）
├── _conf_schema.json         # WebUI 插件设置页 Schema
├── main.py                   # 插件入口（Star 基类、事件钩子、指令组与 Web API 注册）
├── requirements.txt          # 依赖声明
├── README.md                 # 插件文档
├── modules/                  # 功能模块目录（高内聚、易扩展）
│   ├── base.py               # 模块基类
│   ├── schedule/             # 拟人化日程模块
│   │   ├── manager.py        # 日程管理器（调度、生成、持久化、历史CRUD、注入）
│   │   ├── model.py          # 数据结构定义（Segment、DailySchedule）
│   │   ├── prompt.py         # 提示词构建与 LLM 响应解析
│   │   ├── web_api.py        # 视图专属 Web API 后端路由
│   │   └── __init__.py
│   └── prompt_injector/      # 会话专属提示词模块
│       ├── manager.py        # 提示词管理器（规则CRUD、持久化、会话抓取、注入）
│       ├── model.py          # UmoPromptRule 模型与 UMO 解析器
│       ├── web_api.py        # 提示词管理 Web API
│       └── __init__.py
├── utils/                    # 通用工具函数
│   └── time_utils.py         # 24小时制时间解析、跨夜判断与倒计时
├── pages/                    # 兼容 AstrBot <=v4.28.2 的视图结构
│   └── schedule/             # 综合仪表盘（即时看板、日程编辑、规则、会话提示词）
└── views/                    # 兼容 AstrBot >=v4.29.0 的视图结构
    └── schedule/             # 综合仪表盘（即时看板、日程编辑、规则、会话提示词）
```
