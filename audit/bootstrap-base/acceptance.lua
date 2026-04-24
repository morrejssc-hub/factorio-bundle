local force = game.forces.player
local produced = 0
local in_world = 0

for _, surface in pairs(game.surfaces) do
  if force.get_item_production_statistics then
    local stats = force.get_item_production_statistics(surface)
    if stats then
      produced = produced + stats.get_input_count("automation-science-pack")
    end
  end

  for _, entity in pairs(surface.find_entities_filtered{force = force}) do
    if entity.valid and entity.get_inventory then
      for _, inventory_id in pairs(defines.inventory) do
        local inventory = entity.get_inventory(inventory_id)
        if inventory and inventory.valid then
          in_world = in_world + inventory.get_item_count("automation-science-pack")
        end
      end
    end
  end
end

local red_science_pack = produced + in_world
local must_complete = red_science_pack >= 500

rcon.print(
  string.format(
    '{"red_science_pack":%d,"must_complete":%s,"game_tick":%d}',
    red_science_pack,
    must_complete and "true" or "false",
    game.tick
  )
)
