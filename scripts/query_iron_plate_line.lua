-- query_iron_plate_line.lua
-- One-shot query for the minimal iron-plate production line.
-- Scans burner-mining-drill, stone-furnace, and inserter entities,
-- reporting position, direction, fuel inventory, input/output inventory,
-- mining_target, pickup/drop target, iron-plate count, and blocked_reason.
--
-- Usage: /c require("scripts.query_iron_plate_line").query({surface = "nauvis"})
--
-- IMPORTANT NOTE for workers:
--   Stone furnaces do NOT use set_recipe like assembling-machines.
--   They auto-smelt iron-ore → iron-plate when ore is in the input
--   inventory and fuel is in the fuel inventory.
--   Validation should check input/output inventories and actual output,
--   NOT get_recipe (which returns nil/none for stone furnaces).

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

-- Helper: get direction name from direction index
local function fmt_dir(dir)
  local dirs = {"north", "east", "south", "west"}
  return dirs[(dir or 0) + 1] or "unknown"
end

-- Helper: read inventory contents as a summary string
local function inventory_summary(inv)
  if not inv or not inv.valid then return "empty" end
  local items = {}
  for i = 1, #inv do
    local stack = inv[i]
    if stack and stack.valid_for_read and stack.count > 0 then
      table.insert(items, string.format("%s x%d", stack.name, stack.count))
    end
  end
  if #items == 0 then return "empty" end
  return table.concat(items, ", ")
end

-- Helper: get iron-plate count from an inventory
local function count_iron_plate(inv)
  if not inv or not inv.valid then return 0 end
  local total = 0
  for i = 1, #inv do
    local stack = inv[i]
    if stack and stack.valid_for_read and stack.name == "iron-plate" then
      total = total + stack.count
    end
  end
  return total
end

-- Helper: determine blocked reason for an entity
local function get_blocked_reason(entity)
  if not entity or not entity.valid then return "entity_invalid" end

  -- Check if entity is disabled by circuit network
  if entity.get_control_behavior and entity.get_control_behavior() then
    local cb = entity.get_control_behavior()
    if cb.disabled then return "circuit_disabled" end
  end

  -- For inserters: check if pickup or drop target is missing/blocked
  if entity.type == "inserter" then
    local pickup = entity.pickup_target
    local drop = entity.drop_target
    if not pickup or not pickup.valid then return "no_pickup_target" end
    if not drop or not drop.valid then return "no_drop_target" end
    -- Check if inserter is holding an item but can't drop
    if entity.held_stack and entity.held_stack.valid_for_read then
      if drop.get_inventory(defines.inventory.chest) then
        local chest_inv = drop.get_inventory(defines.inventory.chest)
        if chest_inv and not chest_inv.can_insert(entity.held_stack) then
          return "drop_target_full"
        end
      end
    end
    -- Check if pickup source has items
    if pickup.get_inventory(defines.inventory.chest) then
      local src_inv = pickup.get_inventory(defines.inventory.chest)
      if src_inv and src_inv.is_empty() then return "pickup_source_empty" end
    end
  end

  -- For furnaces: check fuel and input
  if entity.type == "furnace" then
    local fuel_inv = entity.get_inventory(defines.inventory.furnace_fuel)
    local src_inv = entity.get_inventory(defines.inventory.furnace_source)
    local result_inv = entity.get_inventory(defines.inventory.furnace_result)

    if fuel_inv and fuel_inv.is_empty() then return "no_fuel" end
    if src_inv and src_inv.is_empty() then return "no_input_ore" end
    if result_inv and result_inv and result_inv.is_full() then return "result_full" end
  end

  -- For mining drills: check if mining target exists and has resources
  if entity.type == "mining-drill" then
    local mining_target = entity.mining_target
    if not mining_target or not mining_target.valid then return "no_mining_target" end
    if mining_target.amount and mining_target.amount <= 0 then return "resource_depleted" end
  end

  return "none"
end

-- Query burner mining drills
local function query_burner_mining_drills(surface_name)
  local surface = game.surfaces[surface_name or "nauvis"]
  if not surface or not surface.valid then
    return { error = "surface_not_found", surface = surface_name }
  end

  local drills = surface.find_entities_filtered({ name = "burner-mining-drill" })
  local results = {}

  for _, drill in pairs(drills) do
    if drill and drill.valid then
      local mining_target = drill.mining_target
      local target_info = nil
      if mining_target and mining_target.valid then
        target_info = {
          name = mining_target.name,
          position = fmt_pos(mining_target.position),
          amount = mining_target.amount or 0,
        }
      end

      local fuel_inv = drill.get_inventory(defines.inventory.fuel)
      local result_inv = drill.get_inventory(defines.inventory.drill_result)

      table.insert(results, {
        entity = "burner-mining-drill",
        name = drill.name,
        position = fmt_pos(drill.position),
        direction = fmt_dir(drill.direction),
        fuel_inventory = inventory_summary(fuel_inv),
        output_inventory = inventory_summary(result_inv),
        iron_plate_count = count_iron_plate(result_inv),
        mining_target = target_info,
        blocked_reason = get_blocked_reason(drill),
        is_mining = drill.is_mining or false,
      })
    end
  end

  return {
    type = "burner-mining-drill",
    count = #results,
    entities = results,
  }
end

-- Query stone furnaces
local function query_stone_furnaces(surface_name)
  local surface = game.surfaces[surface_name or "nauvis"]
  if not surface or not surface.valid then
    return { error = "surface_not_found", surface = surface_name }
  end

  local furnaces = surface.find_entities_filtered({ name = "stone-furnace" })
  local results = {}

  for _, furnace in pairs(furnaces) do
    if furnace and furnace.valid then
      local fuel_inv = furnace.get_inventory(defines.inventory.furnace_fuel)
      local src_inv = furnace.get_inventory(defines.inventory.furnace_source)
      local result_inv = furnace.get_inventory(defines.inventory.furnace_result)

      -- NOTE: stone-furnace does NOT use set_recipe.
      -- get_recipe() returns nil for stone furnaces — this is NORMAL.
      -- The furnace auto-smelts iron-ore → iron-plate when:
      --   1. iron-ore is in the source inventory
      --   2. fuel is in the fuel inventory
      -- Validation should check inventories and output, NOT get_recipe.
      local recipe = furnace.get_recipe()
      local recipe_name = recipe and recipe.name or "none (stone-furnace auto-smelts)"

      table.insert(results, {
        entity = "stone-furnace",
        name = furnace.name,
        position = fmt_pos(furnace.position),
        direction = fmt_dir(furnace.direction),
        fuel_inventory = inventory_summary(fuel_inv),
        input_inventory = inventory_summary(src_inv),
        output_inventory = inventory_summary(result_inv),
        iron_plate_count = count_iron_plate(result_inv),
        recipe = recipe_name,
        is_crafting = furnace.is_crafting or false,
        blocked_reason = get_blocked_reason(furnace),
        -- Key diagnostic fields for stone furnace:
        has_fuel = fuel_inv and not fuel_inv.is_empty(),
        has_input_ore = src_inv and not src_inv.is_empty(),
        result_full = result_inv and result_inv.is_full(),
      })
    end
  end

  return {
    type = "stone-furnace",
    count = #results,
    entities = results,
  }
end

-- Query inserters
local function query_inserters(surface_name)
  local surface = game.surfaces[surface_name or "nauvis"]
  if not surface or not surface.valid then
    return { error = "surface_not_found", surface = surface_name }
  end

  local inserters = surface.find_entities_filtered({ type = "inserter" })
  local results = {}

  for _, inserter in pairs(inserters) do
    if inserter and inserter.valid then
      local pickup = inserter.pickup_target
      local drop = inserter.drop_target

      local pickup_info = nil
      if pickup and pickup.valid then
        pickup_info = {
          name = pickup.name,
          position = fmt_pos(pickup.position),
        }
      end

      local drop_info = nil
      if drop and drop.valid then
        drop_info = {
          name = drop.name,
          position = fmt_pos(drop.position),
        }
      end

      -- Check held item for iron-plate
      local held_item = "none"
      local held_iron_plate = 0
      if inserter.held_stack and inserter.held_stack.valid_for_read then
        held_item = string.format("%s x%d", inserter.held_stack.name, inserter.held_stack.count)
        if inserter.held_stack.name == "iron-plate" then
          held_iron_plate = inserter.held_stack.count
        end
      end

      table.insert(results, {
        entity = "inserter",
        name = inserter.name,
        position = fmt_pos(inserter.position),
        direction = fmt_dir(inserter.direction),
        pickup_target = pickup_info,
        drop_target = drop_info,
        held_item = held_item,
        iron_plate_count = held_iron_plate,
        blocked_reason = get_blocked_reason(inserter),
        is_inserter_active = inserter.inserter_target or false,
      })
    end
  end

  return {
    type = "inserter",
    count = #results,
    entities = results,
  }
end

-- Main query function
function M.query(params)
  params = params or {}
  local surface_name = params.surface or "nauvis"

  local drill_result = query_burner_mining_drills(surface_name)
  local furnace_result = query_stone_furnaces(surface_name)
  local inserter_result = query_inserters(surface_name)

  -- Total iron-plate count across all entities
  local total_iron_plates = 0
  if drill_result.entities then
    for _, e in pairs(drill_result.entities) do
      total_iron_plates = total_iron_plates + (e.iron_plate_count or 0)
    end
  end
  if furnace_result.entities then
    for _, e in pairs(furnace_result.entities) do
      total_iron_plates = total_iron_plates + (e.iron_plate_count or 0)
    end
  end
  if inserter_result.entities then
    for _, e in pairs(inserter_result.entities) do
      total_iron_plates = total_iron_plates + (e.iron_plate_count or 0)
    end
  end

  local result = {
    query = "iron_plate_line",
    surface = surface_name,
    game_tick = game.tick,
    total_iron_plates = total_iron_plates,
    burner_mining_drills = drill_result,
    stone_furnaces = furnace_result,
    inserters = inserter_result,
  }

  rcon.print(dump_table(result))
  return result
end

return M
