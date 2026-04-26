"""Context provider: detailed documentation for all Lua scripts."""

from yoitsu_contracts.bundle import context_provider


@context_provider(name="script_docs")
def provide_script_docs(goal: str) -> str:
    """Return detailed documentation for all available Lua scripts."""
    return """\
# Lua Script Documentation

## scripts/query_all.lua

**综合游戏概览查询脚本**：将游戏状态、生产统计、研究进度整合到**单次 RCON 调用**中返回。当你需要全面了解游戏当前状态时，这是最优选择——用一次调用替代 `query_game_state` + `query_production` + `query_research` 的多次调用。

使用方式：
```
/c require("scripts.query_all").query({params})
```

可选参数：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `force` | `nil`（所有阵营） | 指定要查询的阵营名称 |
| `limit` | `15` | 物品产出率列表的最大条目数 |

返回信息（一次性包含以下所有部分）：

| 信息部分 | 说明 |
|---------|------|
| `tick_info` | 游戏 tick、暂停状态、游戏速度 |
| `entity_counts` | 实体总数、唯一类型数、Top 20 实体（按数量排序） |
| `resource_summary` | 资源矿点总数、总储量、各资源类型详情 |
| `player_info` | 玩家数量、每个玩家的位置/surface/阵营/在线状态 |
| `force_research` | 阵营数量、每个阵营的当前研究/科技统计/下一批可研究科技/实体总数 |
| `items_per_minute` | 各阵营物品每分钟产出/消耗量（Top N） |
| `furnace_throughput` | 熔炉产出率和利用率汇总 |

使用示例：
```
-- 获取完整游戏概览（所有阵营）
/c require("scripts.query_all").query()

-- 仅查询 player 阵营，限制物品产出率显示前 20 项
/c require("scripts.query_all").query({force = "player", limit = 20})
```

> **💡 优先使用场景**：当你需要了解游戏整体状况（如"现在游戏进展如何？"、"生产是否正常？"、"研究进度怎样？"）时，**始终优先使用 `query_all()`**，而不是分别调用多个查询脚本。这能显著减少工具调用次数和 RCON 连接开销。

---

## scripts/query_tick.lua

查询当前游戏 tick 数，返回 `game.tick`。

使用方式：
```
/c require("scripts.query_tick")
```
或通过 RCON 直接执行脚本内容：
```
/c game.tick
```

---

## scripts/query_game_state.lua

统一的游戏状态查询接口，支持多种查询类型，避免重复编写 RCON 命令。

使用方式：
```
/c require("scripts.query_game_state").query("query_type", {params})
```

支持的查询类型：

| 查询类型 | 参数 | 说明 |
|---------|------|------|
| `"entities"` | `{ surface = "nauvis", filter = "inserter" }` | 按类型/名称统计实体数量，支持按 surface 和类型过滤 |
| `"resources"` | `{ surface = "nauvis", resource = "iron-ore" }` | 列出资源矿点，包含位置、储量、类型 |
| `"players"` | 无 | 列出所有玩家，包含位置、surface、阵营、在线状态 |
| `"forces"` | `{ force = "player" }` | 列出阵营信息，包含研究进度、科技状态、实体统计 |
| `"summary"` | 无 | 快速概览以上所有信息（精简版） |

使用示例：
```
-- 统计所有 inserter 数量
/c require("scripts.query_game_state").query("entities", {filter = "inserter"})

-- 查询 nauvis 上的铁矿资源
/c require("scripts.query_game_state").query("resources", {surface = "nauvis", resource = "iron-ore"})

-- 获取游戏状态概览
/c require("scripts.query_game_state").query("summary")

-- 查看 player 阵营的研究进度
/c require("scripts.query_game_state").query("forces", {force = "player"})
```

> **提示**：当需要同时查询多种游戏状态（如实体数量 + 资源分布 + 玩家信息）时，优先使用 `query("summary")` 一次性获取，而不是分别调用多个 RCON 命令。

---

## scripts/query_logistics.lua

物流网络状态查询接口，支持机器人统计、充电状态、物流箱内容等查询。

使用方式：
```
/c require("scripts.query_logistics").query("query_type", {params})
```

支持的查询类型：

| 查询类型 | 参数 | 说明 |
|---------|------|------|
| `"summary"` | 无 | 所有物流网络概览（机器人数量、任务、充电状态） |
| `"networks"` | `{ surface = "nauvis" }` | 每个物流网络的详细信息，包含机器人数量、任务统计 |
| `"robots"` | `{ surface = "nauvis" }` | 跨所有网络的机器人统计（物流/建筑机器人、可用/活跃/充电数量） |
| `"chests"` | `{ surface = "nauvis" }` | 物流箱内容汇总，包含存储物品和运输中物品 |
| `"charging"` | `{ surface = "nauvis" }` | 每个网络的机器人充电状态和充电百分比 |

使用示例：
```
-- 获取物流网络概览
/c require("scripts.query_logistics").query("summary")

-- 查询所有机器人统计
/c require("scripts.query_logistics").query("robots")

-- 查询特定 surface 的物流箱内容
/c require("scripts.query_logistics").query("chests", {surface = "nauvis"})

-- 查看机器人充电状态
/c require("scripts.query_logistics").query("charging")
```

---

## scripts/query_production.lua

生产/消费统计查询接口，支持物品产出率、熔炉吞吐量、组装机效率等查询。

使用方式：
```
/c require("scripts.query_production").query("query_type", {params})
```

支持的查询类型：

| 查询类型 | 参数 | 说明 |
|---------|------|------|
| `"items_per_minute"` | `{ force = "player", item = "iron-plate", limit = 20 }` | 各阵营物品每分钟产出/消耗量 |
| `"furnace_throughput"` | `{ force = "player", surface = "nauvis", furnace_type = "steel-furnace" }` | 熔炉产出率和利用率 |
| `"assembler_output"` | `{ force = "player", surface = "nauvis", assembler_type = "assembling-machine-3" }` | 组装机生产力和产出率 |
| `"belt_throughput"` | `{ surface = "nauvis" }` | 传送带吞吐量估算 |
| `"summary"` | 无 | 所有生产统计的快速概览（精简版） |

使用示例：
```
-- 获取生产概览
/c require("scripts.query_production").query("summary")

-- 查询铁板每分钟产出
/c require("scripts.query_production").query("items_per_minute", {item = "iron-plate"})

-- 查询熔炉利用率
/c require("scripts.query_production").query("furnace_throughput", {surface = "nauvis"})

-- 查询组装机产出
/c require("scripts.query_production").query("assembler_output")
```

---

## scripts/query_research.lua

研究状态查询接口，返回当前研究进度、已研究科技数量、可研究的下一批科技。

使用方式：
```
/c require("scripts.query_research").query({force = "player", limit = 10})
```

返回信息：

| 信息项 | 说明 |
|-------|------|
| 当前研究 | 正在研究的科技名称、等级、进度百分比、所需科研包 |
| 科技统计 | 已研究/可用/锁定科技数量 |
| 下一批可研究 | 按成本排序的前 N 个可立即研究的科技 |

使用示例：
```
-- 查询 player 阵营研究状态（默认 limit=10）
/c require("scripts.query_research").query({force = "player"})

-- 查询 player 阵营，显示前 20 个可研究科技
/c require("scripts.query_research").query({force = "player", limit = 20})
```

---

## scripts/query_iron_plate_line.lua

最小铁板生产线一次性查询脚本。扫描 burner-mining-drill、stone-furnace、inserter 实体，报告位置、方向、燃料库存、输入/输出库存、采矿目标、拾取/放置目标、铁板数量和阻塞原因。

使用方式：
```
/c require("scripts.query_iron_plate_line").query({surface = "nauvis"})
```

返回信息：

| 信息项 | 说明 |
|-------|------|
| burner_mining_drills | 所有燃烧采矿钻的列表，含位置、方向、燃料库存、输出库存、采矿目标、阻塞原因 |
| stone_furnaces | 所有石炉的列表，含位置、方向、燃料库存、输入库存、输出库存、铁板数量、是否正在熔炼、阻塞原因 |
| inserters | 所有机械臂的列表，含位置、方向、拾取目标、放置目标、手持物品、铁板数量、阻塞原因 |
| total_iron_plates | 所有实体中铁板的总数量 |
| game_tick | 查询时的游戏 tick |

使用示例：
```
-- 查询 nauvis 上的最小铁板生产线状态
/c require("scripts.query_iron_plate_line").query({surface = "nauvis"})
```
"""
