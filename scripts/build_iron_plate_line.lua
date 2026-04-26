-- Build a deterministic minimal iron-ore -> iron-plate furnace line.
-- Factorio 2.x inventory constants are not always exposed through
-- defines.inventory in the RCON Lua environment, so use verified stone-furnace
-- numeric indexes: 1=fuel, 2=source, 3=result.

local M = {}

local function count(inv, name)
  if not inv or not inv.valid then return 0 end
  return inv.get_item_count(name)
end

local function clear_area(surface, area)
  for _, entity in pairs(surface.find_entities_filtered{area = area}) do
    if entity.valid and entity.force and entity.force.name == "player" then
      entity.destroy()
    end
  end
end

function M.query(params)
  params = params or {}
  local surface = game.surfaces[params.surface or "nauvis"] or game.surfaces[1]
  if not surface or not surface.valid then
    rcon.print("error=surface_not_found")
    return { error = "surface_not_found" }
  end

  local x = tonumber(params.x) or 0
  local y = tonumber(params.y) or 0
  clear_area(surface, {{x - 2, y - 2}, {x + 2, y + 2}})

  game.tick_paused = false
  game.speed = tonumber(params.speed) or 100

  local furnace = surface.create_entity{
    name = "stone-furnace",
    position = {x, y},
    force = "player",
    raise_built = false,
  }
  if not furnace or not furnace.valid then
    rcon.print("error=furnace_create_failed")
    return { error = "furnace_create_failed" }
  end

  local fuel_inv = furnace.get_inventory(1)
  local source_inv = furnace.get_inventory(2)
  local result_inv = furnace.get_inventory(3)
  local inserted_ore = source_inv and source_inv.insert{name = "iron-ore", count = tonumber(params.ore) or 10} or 0
  local inserted_fuel = fuel_inv and fuel_inv.insert{name = "coal", count = tonumber(params.coal) or 10} or 0

  local report = {
    query = "build_iron_plate_line",
    tick = game.tick,
    speed = game.speed,
    furnace = furnace.name,
    position = string.format("(%.1f, %.1f)", furnace.position.x, furnace.position.y),
    inserted_ore = inserted_ore,
    inserted_fuel = inserted_fuel,
    has_input_ore = count(source_inv, "iron-ore") > 0,
    has_fuel = count(fuel_inv, "coal") > 0,
    result_iron_plate = count(result_inv, "iron-plate"),
    is_crafting = furnace.is_crafting or false,
  }

  rcon.print(
    "query=build_iron_plate_line\n" ..
    "tick=" .. tostring(report.tick) .. "\n" ..
    "speed=" .. tostring(report.speed) .. "\n" ..
    "furnace=" .. tostring(report.furnace) .. "\n" ..
    "position=" .. report.position .. "\n" ..
    "inserted_ore=" .. tostring(report.inserted_ore) .. "\n" ..
    "inserted_fuel=" .. tostring(report.inserted_fuel) .. "\n" ..
    "has_input_ore=" .. tostring(report.has_input_ore) .. "\n" ..
    "has_fuel=" .. tostring(report.has_fuel) .. "\n" ..
    "result_iron_plate=" .. tostring(report.result_iron_plate) .. "\n" ..
    "is_crafting=" .. tostring(report.is_crafting)
  )
  return report
end

return M
