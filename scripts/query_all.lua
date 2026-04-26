-- query_all.lua
-- Combined game overview query: game state + production + research in one call.
-- Usage: /c require("scripts.query_all").query()
--
-- Returns a single consolidated report covering:
--   - Game tick and pause state
--   - Entity counts by type
--   - Resource patches summary
--   - Player info
--   - Force/research status
--   - Items per minute (top produced)
--   - Furnace throughput summary

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

-- Helper: format a position
local function fmt_pos(pos)
  if not pos then return "nil" end
  return string.format("(%.1f, %.1f)", pos.x or 0, pos.y or 0)
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
  local minutes = game_ticks / 3600
  return total / minutes, consumed / minutes
end

local function get_item_production_statistics(force)
  local ok, stats = pcall(function() return force.item_production_statistics end)
  if ok then
    return stats
  end
  return nil
end

-- Helper: check if a technology's prerequisites are all satisfied
local function prereqs_met(tech, force)
  if not tech.enabled then return false end
  if tech.researched then return false end
  for _, prereq in pairs(tech.prerequisites) do
    if not prereq.researched then
      return false
    end
  end
  return true
end

-- === Section: Game Tick ===
local function get_tick_info()
  local paused_ok, paused_value = pcall(function() return game.tick_paused_value end)
  return {
    tick = game.tick,
    paused = paused_ok and paused_value ~= nil,
    speed = game.speed,
  }
end

-- === Section: Entity Counts ===
local function get_entity_counts()
  local counts = {}
  local total = 0
  for _, surface in pairs(game.surfaces) do
    if surface and surface.valid then
      local entities = surface.find_entities_filtered({})
      for _, entity in pairs(entities) do
        local key = entity.name
        if not counts[key] then
          counts[key] = { count = 0, surface = surface.name }
        end
        counts[key].count = counts[key].count + 1
        total = total + 1
      end
    end
  end

  -- Sort by count descending, take top 20
  local sorted = {}
  for name, data in pairs(counts) do
    table.insert(sorted, { name = name, count = data.count, surface = data.surface })
  end
  table.sort(sorted, function(a, b) return a.count > b.count end)

  local top = {}
  for i = 1, math.min(20, #sorted) do
    table.insert(top, sorted[i])
  end

  return {
    total_entities = total,
    unique_types = #sorted,
    top_entities = top,
  }
end

local function get_force_entity_counts(force)
  local counts = {}
  local ok, get_counts = pcall(function() return force.get_entity_counts end)
  if ok and type(get_counts) == "function" then
    return get_counts()
  end
  for _, surface in pairs(game.surfaces) do
    if surface and surface.valid then
      local entities = surface.find_entities_filtered({ force = force })
      for _, entity in pairs(entities) do
        counts[entity.name] = (counts[entity.name] or 0) + 1
      end
    end
  end
  return counts
end

-- === Section: Resource Patches ===
local function get_resource_summary()
  local patches = {}
  local total_amount = 0
  for _, surface in pairs(game.surfaces) do
    if surface and surface.valid then
      local resource_entities = surface.find_entities_filtered({ type = "resource" })
      local patch_map = {}
      for _, entity in pairs(resource_entities) do
        local rname = entity.name
        if not patch_map[rname] then
          patch_map[rname] = {
            name = rname,
            surface = surface.name,
            total_amount = 0,
            entity_count = 0,
          }
        end
        local patch = patch_map[rname]
        patch.total_amount = patch.total_amount + (entity.amount or 0)
        patch.entity_count = patch.entity_count + 1
      end
      for _, patch in pairs(patch_map) do
        table.insert(patches, patch)
        total_amount = total_amount + patch.total_amount
      end
    end
  end

  table.sort(patches, function(a, b) return a.total_amount > b.total_amount end)

  return {
    total_patches = #patches,
    total_resource_amount = total_amount,
    patches = patches,
  }
end

-- === Section: Player Info ===
local function get_player_info()
  local players = {}
  for _, player in pairs(game.players) do
    if player and player.valid then
      table.insert(players, {
        name = player.name,
        position = fmt_pos(player.position),
        surface = player.surface and player.surface.name or "unknown",
        force = player.force and player.force.name or "unknown",
        online = player.connected,
      })
    end
  end
  return {
    player_count = #players,
    players = players,
  }
end

-- === Section: Force & Research Status ===
local function get_force_research_status(params)
  params = params or {}
  local forces = get_forces(params)
  local force_data = {}

  for _, force in pairs(forces) do
    if force and force.valid then
      local researching = force.current_research
      local researching_info = nil
      if researching then
        researching_info = {
          name = researching.name,
          level = researching.level or 1,
          progress_percentage = researching.progress_percentage or 0,
        }
      end

      local researched_count = 0
      local available_count = 0
      local total_count = 0
      local next_available = {}
      for _, tech in pairs(force.technologies) do
        total_count = total_count + 1
        if tech.researched then
          researched_count = researched_count + 1
        elseif tech.enabled and prereqs_met(tech, force) then
          available_count = available_count + 1
          table.insert(next_available, {
            name = tech.name,
            level = tech.level or 1,
            cost = tech.research_unit_count or 0,
          })
        end
      end

      -- Sort next available by cost
      table.sort(next_available, function(a, b)
        if a.cost ~= b.cost then return a.cost < b.cost end
        return a.name < b.name
      end)

      -- Entity counts per force
      local entity_counts = get_force_entity_counts(force)
      local total_force_entities = 0
      for _, count in pairs(entity_counts) do
        total_force_entities = total_force_entities + count
      end

      table.insert(force_data, {
        name = force.name,
        researching = researching_info,
        technologies = {
          researched = researched_count,
          total = total_count,
          available = available_count,
        },
        next_techs = next_available,
        total_entities = total_force_entities,
      })
    end
  end

  return {
    force_count = #force_data,
    forces = force_data,
  }
end

-- === Section: Items Per Minute ===
local function get_items_per_minute(params)
  params = params or {}
  local forces = get_forces(params)
  local limit = params.limit or 15
  local all_items = {}

  for _, force in pairs(forces) do
    if force and force.valid then
      local stats = get_item_production_statistics(force)
      if stats then
        local names = stats.get_names()
        for _, name in pairs(names) do
          local produced, consumed = stat_to_per_minute(stats, name)
          if produced > 0 or consumed > 0 then
            local key = force.name .. ":" .. name
            if not all_items[key] then
              all_items[key] = {
                item = name,
                force = force.name,
                produced_per_min = 0,
                consumed_per_min = 0,
              }
            end
            all_items[key].produced_per_min = all_items[key].produced_per_min + produced
            all_items[key].consumed_per_min = all_items[key].consumed_per_min + consumed
          end
        end
      end
    end
  end

  local sorted = {}
  for _, data in pairs(all_items) do
    data.net_per_min = data.produced_per_min - data.consumed_per_min
    table.insert(sorted, data)
  end
  table.sort(sorted, function(a, b) return a.produced_per_min > b.produced_per_min end)

  if #sorted > limit then
    sorted = { unpack(sorted, 1, limit) }
  end

  return {
    total_tracked = #all_items,
    top_items = sorted,
  }
end

-- === Section: Furnace Throughput ===
local function get_furnace_throughput(params)
  params = params or {}
  local forces = get_forces(params)
  local surface_name = params.surface or nil

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
      local furnaces = surface.find_entities_filtered({ type = "furnace" })
      for _, furnace in pairs(furnaces) do
        if furnace and furnace.valid then
          local recipe = furnace.get_recipe()
          local recipe_name = recipe and recipe.name or "none"
          local key = furnace.name
          if not furnace_stats[key] then
            furnace_stats[key] = {
              name = key,
              count = 0,
              active_count = 0,
              recipes = {},
            }
          end
          local fs = furnace_stats[key]
          fs.count = fs.count + 1
          if furnace.is_crafting then
            fs.active_count = fs.active_count + 1
            active_furnaces = active_furnaces + 1
          end
          if not fs.recipes[recipe_name] then
            fs.recipes[recipe_name] = 0
          end
          fs.recipes[recipe_name] = fs.recipes[recipe_name] + 1
        end
        total_furnaces = total_furnaces + 1
      end
    end
  end

  local result_list = {}
  for _, fs in pairs(furnace_stats) do
    fs.utilization = fs.count > 0 and (fs.active_count / fs.count * 100) or 0
    table.insert(result_list, fs)
  end
  table.sort(result_list, function(a, b) return a.count > b.count end)

  return {
    total_furnaces = total_furnaces,
    active_furnaces = active_furnaces,
    overall_utilization = total_furnaces > 0 and (active_furnaces / total_furnaces * 100) or 0,
    furnace_types = result_list,
  }
end

-- === Main Combined Query ===
function M.query(params)
  params = params or {}

  local result = {
    query = "all",
    tick_info = get_tick_info(),
    entity_summary = get_entity_counts(),
    resource_summary = get_resource_summary(),
    player_info = get_player_info(),
    force_research = get_force_research_status(params),
    production = {
      items_per_minute = get_items_per_minute(params),
      furnace_throughput = get_furnace_throughput(params),
    },
  }

  rcon.print(dump_table(result))
  return result
end

return M
