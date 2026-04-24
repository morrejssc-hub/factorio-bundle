local force = game.forces.player
local wooden_chest_count = 0

for _, surface in pairs(game.surfaces) do
  local chests = surface.find_entities_filtered{name = "wooden-chest", force = force}
  wooden_chest_count = wooden_chest_count + #chests
end

local must_complete = wooden_chest_count >= 1

rcon.print(
  string.format(
    '{"wooden_chest_count":%d,"must_complete":%s,"game_tick":%d}',
    wooden_chest_count,
    must_complete and "true" or "false",
    game.tick
  )
)
