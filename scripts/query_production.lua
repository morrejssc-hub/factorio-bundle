-- query_production.lua
-- Unified interface for querying Factorio production/consumption statistics.
-- Usage: /c require("scripts.query_production").query("query_type", {params})
--
-- Supported query types:
--   "items_per_minute"  - Items produced/consumed per minute across all forces
--   "furnace_throughput" - Furnace output rates and utilization
--   "assembler_output"   - Assembler productivity and output rates
--   "belt_throughput"    - Belt throughput estimates
--   "summary"            - Quick overview of all production stats (condensed)

local M = {}

-- Helper: serialize a table to a readable string for rcon.print
local function dump_table(t, indent)
  indent = indent or 0
  local lines = {}
  local prefix = string.rep("  ", indent)
  for k, v in pairs(t) do
    if type(v) == "table" then
      table.insert(lines, prefix .. tostring(k) .. ":")
      table.insert(lines, dump_table(v, indent + 1))
    elseif type(v) == "number" then
      table.insert(lines, prefix .. tostring(k) .. ": " .. string.format("%.2f", v))
    else
      table.insert(lines, prefix .. tostring(k) .. ": " .. tostring(v))
    end
  end
  return table.concat(lines, "\n")
end

-- Helper: get or create a force list
local function get_forces(params)
  local force_filter = params and params.force or nil
  if force_filter then
    local f = game.forces[force_filter]
    return f and { f } or {}
  end
  return game.forces
end

-- Helper: calculate items per minute from a production statistic
local function stat_to_per_minute(stat, name)
  local total = stat.get_output_count(name) or 0
  local consumed = stat.get_input_count(name) or 0
  local game_ticks = game.tick
  if game_ticks == 0 then return 0, 0 end
  local minutes = game_ticks / 3600  -- 60 ticks/sec * 60 sec/min
  return total / minutes, consumed / minutes
end

local function get_item_production_statistics(force)
  local ok, stats = pcall(function() return force.item_production_statistics end)
  if ok then
    return stats
  end
  return nil
end

-- Query: items produced/consumed per minute
-- Params (optional): { force = "player", item = "iron-plate", limit = 20 }
local function query_items_per_minute(params)
  params = params or {}
  local item_filter = params.item or nil
  local limit = params.limit or 20
  local forces = get_forces(params)

  local all_items = {}

  for _, force in pairs(forces) do
    if force and force.valid then
      local stats = get_item_production_statistics(force)
      if stats then
        local names = stats.get_names()
        for _, name in pairs(names) do
          if not item_filter or name == item_filter then
            local produced, consumed = stat_to_per_minute(stats, name)
            if produced > 0 or consumed > 0 then
              local key = force.name .. ":" .. name
              if not all_items[key] then
                all_items[key] = {
                  item = name,
                  force = force.name,
                  produced_per_min = 0,
                  consumed_per_min = 0,
                  net_per_min = 0,
                }
              end
              all_items[key].produced_per_min = all_items[key].produced_per_min + produced
              all_items[key].consumed_per_min = all_items[key].consumed_per_min + consumed
              all_items[key].net_per_min = all_items[key].produced_per_min - all_items[key].consumed_per_min
            end
          end
        end
      end
    end
  end

  -- Convert to sorted list
  local sorted = {}
  for _, data in pairs(all_items) do
    table.insert(sorted, data)
  end
  table.sort(sorted, function(a, b) return a.produced_per_min > b.produced_per_min end)

  -- Apply limit
  if #sorted > limit then
    sorted = { unpack(sorted, 1, limit) }
  end

  return {
    query = "items_per_minute",
    force_filter = params.force,
    item_filter = item_filter,
    total_items = #sorted,
    items = sorted,
  }
end

-- Query: furnace throughput
-- Params (optional): { force = "player", surface = "nauvis", furnace_type = "steel-furnace" }
local function query_furnace_throughput(params)
  params = params or {}
  local forces = get_forces(params)
  local surface_name = params.surface or nil
  local furnace_type = params.furnace_type or nil

  local surfaces
  if surface_name then
    surfaces = { game.surfaces[surface_name] }
  else
    surfaces = game.surfaces
  end

  local furnace_stats = {}
  local total_furnaces = 0
  local active_furnaces = 0

  for _, surface in pairs(surfaces) do
    if surface and surface.valid then
      local filter = { type = "furnace" }
      if furnace_type then filter.name = furnace_type end
      local furnaces = surface.find_entities_filtered(filter)

      for _, furnace in pairs(furnaces) do
        if furnace and furnace.valid then
          local is_active = false
          for _, f in pairs(forces) do
            if f and f.valid and furnace.force == f then
              is_active = true
              break
            end
          end

          local recipe = furnace.get_recipe()
          local recipe_name = recipe and recipe.name or "none"
          local crafting_speed = furnace.prototype.crafting_speed or 1
          local productivity = furnace.get_productivity_bonus() or 0

          local key = furnace.name
          if not furnace_stats[key] then
            furnace_stats[key] = {
              name = key,
              surface = surface.name,
              count = 0,
              active_count = 0,
              recipes = {},
              total_crafting_speed = 0,
              avg_productivity_bonus = 0,
            }
          end
          local fs = furnace_stats[key]
          fs.count = fs.count + 1
          if furnace.is_crafting then
            fs.active_count = fs.active_count + 1
            active_furnaces = active_furnaces + 1
          end
          fs.total_crafting_speed = fs.total_crafting_speed + crafting_speed
          fs.avg_productivity_bonus = fs.avg_productivity_bonus + productivity

          if not fs.recipes[recipe_name] then
            fs.recipes[recipe_name] = 0
          end
          fs.recipes[recipe_name] = fs.recipes[recipe_name] + 1
        end
        total_furnaces = total_furnaces + 1
      end
    end
  end

  -- Convert to list and compute averages
  local result_list = {}
  for _, fs in pairs(furnace_stats) do
    if fs.count > 0 then
      fs.avg_productivity_bonus = fs.avg_productivity_bonus / fs.count
      fs.avg_crafting_speed = fs.total_crafting_speed / fs.count
      fs.utilization = fs.count > 0 and (fs.active_count / fs.count * 100) or 0
      fs.total_crafting_speed = nil  -- remove intermediate value
      table.insert(result_list, fs)
    end
  end
  table.sort(result_list, function(a, b) return a.count > b.count end)

  return {
    query = "furnace_throughput",
    surface = surface_name,
    furnace_type = furnace_type,
    total_furnaces = total_furnaces,
    active_furnaces = active_furnaces,
    overall_utilization = total_furnaces > 0 and (active_furnaces / total_furnaces * 100) or 0,
    furnace_types = result_list,
  }
end

-- Query: assembler output rates
-- Params (optional): { force = "player", surface = "nauvis", assembler_type = "assembling-machine-3" }
local function query_assembler_output(params)
  params = params or {}
  local forces = get_forces(params)
  local surface_name = params.surface or nil
  local assembler_type = params.assembler_type or nil

  local surfaces
  if surface_name then
    surfaces = { game.surfaces[surface_name] }
  else
    surfaces = game.surfaces
  end

  local assembler_stats = {}
  local total_assemblers = 0
  local active_assemblers = 0

  for _, surface in pairs(surfaces) do
    if surface and surface.valid then
      local filter = { type = "assembling-machine" }
      if assembler_type then filter.name = assembler_type end
      local assemblers = surface.find_entities_filtered(filter)

      for _, assembler in pairs(assemblers) do
        if assembler and assembler.valid then
          local recipe = assembler.get_recipe()
          local recipe_name = recipe and recipe.name or "none"
          local crafting_speed = assembler.prototype.crafting_speed or 1
          local productivity = assembler.get_productivity_bonus() or 0

          local key = assembler.name
          if not assembler_stats[key] then
            assembler_stats[key] = {
              name = key,
              surface = surface.name,
              count = 0,
              active_count = 0,
              recipes = {},
              total_crafting_speed = 0,
              avg_productivity_bonus = 0,
            }
          end
          local as = assembler_stats[key]
          as.count = as.count + 1
          if assembler.is_crafting then
            as.active_count = as.active_count + 1
            active_assemblers = active_assemblers + 1
          end
          as.total_crafting_speed = as.total_crafting_speed + crafting_speed
          as.avg_productivity_bonus = as.avg_productivity_bonus + productivity

          if not as.recipes[recipe_name] then
            as.recipes[recipe_name] = 0
          end
          as.recipes[recipe_name] = as.recipes[recipe_name] + 1
        end
        total_assemblers = total_assemblers + 1
      end
    end
  end

  -- Convert to list and compute averages
  local result_list = {}
  for _, as in pairs(assembler_stats) do
    if as.count > 0 then
      as.avg_productivity_bonus = as.avg_productivity_bonus / as.count
      as.avg_crafting_speed = as.total_crafting_speed / as.count
      as.utilization = as.count > 0 and (as.active_count / as.count * 100) or 0
      as.total_crafting_speed = nil
      table.insert(result_list, as)
    end
  end
  table.sort(result_list, function(a, b) return a.count > b.count end)

  return {
    query = "assembler_output",
    surface = surface_name,
    assembler_type = assembler_type,
    total_assemblers = total_assemblers,
    active_assemblers = active_assemblers,
    overall_utilization = total_assemblers > 0 and (active_assemblers / total_assemblers * 100) or 0,
    assembler_types = result_list,
  }
end

-- Query: belt throughput
-- Params (optional): { surface = "nauvis", belt_type = "transport-belt" }
local function query_belt_throughput(params)
  params = params or {}
  local surface_name = params.surface or nil
  local belt_type = params.belt_type or nil

  local surfaces
  if surface_name then
    surfaces = { game.surfaces[surface_name] }
  else
    surfaces = game.surfaces
  end

  local belt_stats = {}
  local total_belts = 0

  for _, surface in pairs(surfaces) do
    if surface and surface.valid then
      local filter = { type = "transport-belt" }
      if belt_type then filter.name = belt_type end
      local belts = surface.find_entities_filtered(filter)

      for _, belt in pairs(belts) do
        if belt and belt.valid then
          local belt_speed = belt.prototype.belt_speed or 0
          -- Items per second = belt_speed * 2 (two lanes) * 60 ticks/sec
          -- Items per minute = belt_speed * 2 * 60 * 60
          local theoretical_max_per_min = belt_speed * 2 * 3600

          local key = belt.name
          if not belt_stats[key] then
            belt_stats[key] = {
              name = key,
              surface = surface.name,
              count = 0,
              belt_speed = belt_speed,
              theoretical_max_per_min = theoretical_max_per_min,
              total_length = 0,
            }
          end
          local bs = belt_stats[key]
          bs.count = bs.count + 1
          bs.total_length = bs.total_length + 1
        end
        total_belts = total_belts + 1
      end
    end
  end

  -- Convert to list
  local result_list = {}
  for _, bs in pairs(belt_stats) do
    table.insert(result_list, bs)
  end
  table.sort(result_list, function(a, b) return a.count > b.count end)

  return {
    query = "belt_throughput",
    surface = surface_name,
    belt_type = belt_type,
    total_belts = total_belts,
    belt_types = result_list,
  }
end

-- Query: summary (condensed production overview)
local function query_summary(params)
  params = params or {}
  local items_result = query_items_per_minute(params)
  local furnace_result = query_furnace_throughput(params)
  local assembler_result = query_assembler_output(params)
  local belt_result = query_belt_throughput(params)

  -- Top produced items
  local top_produced = {}
  for i = 1, math.min(5, #items_result.items) do
    table.insert(top_produced, {
      item = items_result.items[i].item,
      produced_per_min = items_result.items[i].produced_per_min,
    })
  end

  return {
    query = "production_summary",
    force_filter = params.force,
    items_tracked = items_result.total_items,
    top_produced = top_produced,
    total_furnaces = furnace_result.total_furnaces,
    furnace_utilization = string.format("%.1f%%", furnace_result.overall_utilization),
    total_assemblers = assembler_result.total_assemblers,
    assembler_utilization = string.format("%.1f%%", assembler_result.overall_utilization),
    total_belts = belt_result.total_belts,
  }
end

-- Main query dispatcher
function M.query(query_type, params)
  local handlers = {
    items_per_minute = query_items_per_minute,
    furnace_throughput = query_furnace_throughput,
    assembler_output = query_assembler_output,
    belt_throughput = query_belt_throughput,
    summary = query_summary,
  }

  local handler = handlers[query_type]
  if not handler then
    local available = {}
    for k in pairs(handlers) do table.insert(available, k) end
    table.sort(available)
    rcon.print("Unknown query type: " .. tostring(query_type) .. "\nAvailable: " .. table.concat(available, ", "))
    return nil
  end

  local result = handler(params)
  if result then
    rcon.print(dump_table(result))
  end
  return result
end

return M
