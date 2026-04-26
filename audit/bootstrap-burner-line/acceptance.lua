local force = game.forces.player
local produced = 0

for _, surface in pairs(game.surfaces) do
  if force.get_item_production_statistics then
    local stats = force.get_item_production_statistics(surface)
    if stats then
      produced = produced + stats.get_input_count("iron-plate")
    end
  end
end

local must_complete = produced >= 10

rcon.print(
  string.format(
    '{"iron_plate_produced":%d,"must_complete":%s,"game_tick":%d}',
    produced,
    must_complete and "true" or "false",
    game.tick
  )
)
