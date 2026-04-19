-- query_game_state.lua
-- Unified interface for querying common Factorio game state.
-- Usage: /c require("scripts.query_game_state").query("query_type", {params})
--
-- Supported query types:
--   "entities"    - Count entities by type/name across all surfaces
--   "resources"   - List resource patches with position, amount, and type
--   "players"     - List all players with position, surface, and force
--   "forces"      - List forces with research progress and tech status
--   "summary"     - Quick overview of all above (condensed)

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

-- Helper: format a position table
local function fmt_pos(pos)
  if not pos then return "nil" end
  return string.format("(%.1f, %.1f)", pos.x or 0, pos.y or 0)
end

-- Query: entity counts by type/name
-- Params (optional): { surface = "nauvis", filter = "inserter" }
local function query_entities(params)
  params = params or {}
  local surface_name = params.surface or nil
  local filter = params.filter or nil

  local surfaces
  if surface_name then
    surfaces = { game.surfaces[surface_name] }
  else
    surfaces = game.surfaces
  end

  local counts = {}
  for _, surface in pairs(surfaces) do
    if surface and surface.valid then
      local entities = surface.find_entities_filtered({
        type = filter,
        force = params.force or nil,
        name = params.name or nil,
      })
      for _, entity in pairs(entities) do
        local key = entity.name
        if not counts[key] then
          counts[key] = { count = 0, surface = surface.name }
        end
        counts[key].count = counts[key].count + 1
      end
    end
  end

  -- Sort by count descending
  local sorted = {}
  for name, data in pairs(counts) do
    table.insert(sorted, { name = name, count = data.count, surface = data.surface })
  end
  table.sort(sorted, function(a, b) return a.count > b.count end)

  local result = { query = "entities", filter = filter, surface = surface_name, total = 0, entities = {} }
  for _, entry in ipairs(sorted) do
    table.insert(result.entities, entry)
    result.total = result.total + entry.count
  end
  return result
end

-- Query: resource patch info
-- Params (optional): { surface = "nauvis", resource = "iron-ore" }
local function query_resources(params)
  params = params or {}
  local surface_name = params.surface or nil
  local resource_filter = params.resource or nil

  local surfaces
  if surface_name then
    surfaces = { game.surfaces[surface_name] }
  else
    surfaces = game.surfaces
  end

  local patches = {}
  for _, surface in pairs(surfaces) do
    if surface and surface.valid then
      local resource_entities = surface.find_entities_filtered({
        type = "resource",
        name = resource_filter,
      })
      -- Group by resource name and approximate patch location
      local patch_map = {}
      for _, entity in pairs(resource_entities) do
        local rname = entity.name
        if not patch_map[rname] then
          patch_map[rname] = {
            name = rname,
            surface = surface.name,
            total_amount = 0,
            entity_count = 0,
            min_pos = { x = entity.position.x, y = entity.position.y },
            max_pos = { x = entity.position.x, y = entity.position.y },
          }
        end
        local patch = patch_map[rname]
        patch.total_amount = patch.total_amount + (entity.amount or 0)
        patch.entity_count = patch.entity_count + 1
        if entity.position.x < patch.min_pos.x then patch.min_pos.x = entity.position.x end
        if entity.position.x > patch.max_pos.x then patch.max_pos.x = entity.position.x end
        if entity.position.y < patch.min_pos.y then patch.min_pos.y = entity.position.y end
        if entity.position.y > patch.max_pos.y then patch.max_pos.y = entity.position.y end
      end
      for _, patch in pairs(patch_map) do
        patch.center = {
          x = (patch.min_pos.x + patch.max_pos.x) / 2,
          y = (patch.min_pos.y + patch.max_pos.y) / 2,
        }
        patch.span = {
          x = patch.max_pos.x - patch.min_pos.x,
          y = patch.max_pos.y - patch.min_pos.y,
        }
        table.insert(patches, patch)
      end
    end
  end

  table.sort(patches, function(a, b) return a.total_amount > b.total_amount end)

  return { query = "resources", surface = surface_name, resource_filter = resource_filter, patch_count = #patches, patches = patches }
end

-- Query: player positions and info
-- Params: none
local function query_players()
  local players = {}
  for _, player in pairs(game.players) do
    if player and player.valid then
      local pos = player.position
      local surface = player.surface and player.surface.name or "unknown"
      local force = player.force and player.force.name or "unknown"
      table.insert(players, {
        name = player.name,
        index = player.index,
        position = fmt_pos(pos),
        surface = surface,
        force = force,
        online = player.connected,
        admin = player.admin,
      })
    end
  end
  return { query = "players", player_count = #players, players = players }
end

-- Query: force and research status
-- Params (optional): { force = "player" }
local function query_forces(params)
  params = params or {}
  local force_filter = params.force or nil

  local forces = {}
  local force_list = force_filter and { game.forces[force_filter] } or game.forces

  for _, force in pairs(force_list) do
    if force and force.valid then
      local techs = {}
      -- Get currently researching tech
      local researching = force.current_research
      local researching_info = nil
      if researching then
        researching_info = {
          name = researching.name,
          level = researching.level or 1,
          progress = researching.progress or 0,
          progress_percentage = researching.progress_percentage or 0,
        }
      end

      -- Count researched technologies
      local researched_count = 0
      local available_count = 0
      for _, tech in pairs(force.technologies) do
        if tech.researched then
          researched_count = researched_count + 1
        elseif tech.enabled then
          available_count = available_count + 1
        end
      end

      -- Entity counts per force
      local entity_counts = {}
      for _, surface in pairs(game.surfaces) do
        if surface and surface.valid then
          local entities = surface.find_entities_filtered({ force = force.name })
          for _, entity in pairs(entities) do
            local key = entity.name
            entity_counts[key] = (entity_counts[key] or 0) + 1
          end
        end
      end

      table.insert(forces, {
        name = force.name,
        researching = researching_info,
        technologies = {
          researched = researched_count,
          available = available_count,
        },
        entity_count = #entity_counts,
        total_entities = (function()
          local total = 0
          for _, c in pairs(entity_counts) do total = total + c end
          return total
        end)(),
      })
    end
  end

  return { query = "forces", force_filter = force_filter, force_count = #forces, forces = forces }
end

-- Query: summary (condensed overview)
local function query_summary()
  local entity_result = query_entities()
  local resource_result = query_resources()
  local player_result = query_players()
  local force_result = query_forces()

  return {
    query = "summary",
    total_entities = entity_result.total,
    unique_entity_types = #entity_result.entities,
    resource_patches = resource_result.patch_count,
    player_count = player_result.player_count,
    force_count = force_result.force_count,
  }
end

-- Main query dispatcher
function M.query(query_type, params)
  local handlers = {
    entities = query_entities,
    resources = query_resources,
    players = query_players,
    forces = query_forces,
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
