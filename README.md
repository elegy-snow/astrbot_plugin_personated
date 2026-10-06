# astrbot_plugin_personated (拟人化综合伴侣插件)

一个为 AstrBot 设计的高可扩展“功能集合”插件。首期核心实现**拟人化作息日程系统**，让机器人拥有真实生活作息与实时状态流转，未来将持续扩增更多拟人化陪伴能力。

---

## 🌟 核心特性（第一阶段：拟人化日程系统）

1. **每日定时生成作息日程**
   - 每天在指定时间（默认凌晨 `04:00`，24小时制精确到分钟）根据机器人的**人设提示词**，由大模型自动规划当天的拟人化作息安排。
   - 若机器人在设定时间离线，启动后会自动检测并补全今日日程。

2. **双轨模型指定与自动回退**
   - 支持在插件设置中为日程规划**单独指定专属模型提供商**。
   - 若未指定或该模型离线，系统自动无缝回退使用当前的对话大模型。

3. **自由度极高的时间段划分**
   - 支持自定义一天划分几个时间段、每个时间段的名称及起止时间（24小时制 `HH:MM`，精确到分钟）。
   - 完美支持跨午夜时间段（如夜间就寝 `22:00` 至次日 `06:00`）。

4. **对话上下文实时注入**
   - 在用户与 Bot 对话时，系统自动识别现实时间落在哪一时段。
   - 提取该时段的活动内容与心理状态，将其自然注入大模型请求（默认使用 `extra_user_content` 模式，保护服务端 KV Cache 命中，不额外增加延迟与成本）。
   - 让 Bot 在闲聊和日常问候中，自然表现出正在做的事情与当下心情，极大增强拟人沉浸感。

5. **本地持久化与容错回退**
   - 生成的日程持久化保存在 `data/plugin_data/astrbot_plugin_personated/daily_schedules.json`，重启 AstrBot 不丢失今日日程。
   - 若遭遇网络中断或模型解析异常，自动启用拟人化兜底日程，确保服务稳定不崩溃。

---

## ⚙️ 配置说明 (`_conf_schema.json`)

可在 AstrBot WebUI 管理面板的“插件设置”中直接可视化配置：

| 配置项 | 类型 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `daily_generate_time` | string | `04:00` | 每日生成日程时刻（24h制 `HH:MM`） |
| `schedule_provider_id` | string | 空 | 指定生成模型提供商，留空则自动回退使用对话模型 |
| `inject_context_enabled` | bool | `true` | 是否在对话中自动注入当前日程状态 |
| `inject_mode` | string | `extra_user_content` | 注入模式：`extra_user_content`（推荐）或 `system_prompt` |
| `schedule_segments` | list | 6个常规时段 | 每日各时间段划分定义（ID、名称、起止时刻） |
| `custom_prompt_template` | text | 默认模板 | 自定义日程生成的 Prompt 模板 |

---

## 💬 指令列表

| 指令 | 别名 | 描述 |
| :--- | :--- | :--- |
| `/schedule view` | `/日程 查看` | 查看今日完整的时段日程安排及当前生效状态 |
| `/schedule refresh` | `/日程 重新生成` | 立即强制重新生成今日的日程安排 |
| `/schedule status` | `/日程 状态` | 查看日程系统的运行状态、定时信息与生效模型 |
| `/schedule segments` | `/日程 时间段` | 查看当前配置的时间段划分列表 |

> 直接发送 `/schedule` 或 `/日程` 时，AstrBot 将自动展开指令帮助树。

---

## 📁 项目目录结构

```text
astrbot_plugin_personated/
├── metadata.yaml             # 插件元信息（支持平台、版本要求等）
├── _conf_schema.json         # 可视化配置 Schema
├── main.py                   # 插件入口（Star 基类、事件钩子与指令组）
├── requirements.txt          # 依赖声明
├── README.md                 # 插件文档
├── modules/                  # 功能模块目录（高内聚、易扩展）
│   ├── base.py               # 模块基类
│   └── schedule/             # 拟人化日程模块
│       ├── manager.py        # 日程管理器（调度、生成、持久化、注入）
│       ├── model.py          # 数据结构定义（Segment、DailySchedule）
│       └── prompt.py         # 提示词构建与 LLM 响应解析
└── utils/                    # 通用工具函数
    └── time_utils.py         # 24小时制时间解析、跨夜判断与倒计时
```

---

## 🚀 后续规划（第二阶段）

- 插件自定义可视化 UI 界面（基于 AstrBot `views/` 机制）：
  - 可视化日程看板与时间轴时间线
  - 动态可视化增删改各时段与作息规则
  - 手动修改某一时段活动内容与即时预览
