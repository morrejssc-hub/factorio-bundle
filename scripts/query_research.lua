-- query_research.lua
-- Detailed research status query for Factorio.
-- Usage: /c require("scripts.query_research").query({force = "player", limit = 10})
--
-- Returns:
--   - Currently researching tech (name, level, progress %)
--   - Total researched technology count
--   - Next available technologies that can be researched immediately (top N)

local M = {}

-- Helper: check if a technology's prerequisites are all satisfied
local function prereqs_met(tech, force)
  if not tech.enabled then return false end
  if tech.researched then return false end
  if tech.research_unit_ingredients and #tech.research_unit_ingredients == 0 then
    -- No ingredients means it's an auto-research or already done
  end
  for _, prereq in pairs(tech.prerequisites) do
    if not prereq.researched then
      return false
    end
  end
  return true
end

-- Helper: format a tech entry for display
local function fmt_tech(tech, include_progress)
  local parts = {}
  table.insert(parts, "  " .. tech.name)
  if tech.level and tech.level > 1 then
    parts[#parts] = parts[#parts] .. " (Lv." .. tech.level .. ")"
  end
  if include_progress and tech.progress_percentage then
    parts[#parts] = parts[#parts] .. " - " .. string.format("%.1f%%", tech.progress_percentage)
  end
  if tech.research_unit_ingredients then
    local ingredients = {}
    for _, ing in pairs(tech.research_unit_ingredients) do
      table.insert(ingredients, ing[1] .. " x" .. ing[2])
    end
    if #ingredients > 0 then
      parts[#parts] = parts[#parts] .. " [" .. table.concat(ingredients, ", ") .. "]"
    end
  end
  if tech.research_unit_count then
    parts[#parts] = parts[#parts] .. " (packs: " .. tech.research_unit_count .. ")"
  end
  return table.concat(parts, "")
end

-- Main query function
function M.query(params)
  params = params or {}
  local force_name = params.force or "player"
  local limit = params.limit or 10

  local force = game.forces[force_name]
  if not force or not force.valid then
    return "Error: force '" .. force_name .. "' not found or invalid."
  end

  local lines = {}

  -- === Currently researching ===
  table.insert(lines, "=== Research Status: " .. force_name .. " ===")
  table.insert(lines, "")

  local current = force.current_research
  if current then
    table.insert(lines, "[Currently Researching]")
    table.insert(lines, fmt_tech(current, true))
    table.insert(lines, "  Progress: " .. string.format("%.1f / %.1f  (%.1f%%)",
      current.progress or 0,
      current.research_unit_count or 0,
      current.progress_percentage or 0))
  else
    table.insert(lines, "[Currently Researching]")
    table.insert(lines, "  None (idle)")
  end
  table.insert(lines, "")

  -- === Researched count ===
  local researched_count = 0
  local total_count = 0
  local enabled_count = 0
  for _, tech in pairs(force.technologies) do
    total_count = total_count + 1
    if tech.researched then
      researched_count = researched_count + 1
    elseif tech.enabled then
      enabled_count = enabled_count + 1
    end
  end
  table.insert(lines, "[Technologies]")
  table.insert(lines, "  Researched: " .. researched_count .. " / " .. total_count)
  table.insert(lines, "  Available (unlocked): " .. enabled_count)
  table.insert(lines, "  Locked (prerequisites not met): " .. (total_count - researched_count - enabled_count))
  table.insert(lines, "")

  -- === Next available technologies ===
  table.insert(lines, "[Next Available Technologies (top " .. limit .. ")]")

  local available = {}
  for _, tech in pairs(force.technologies) do
    if not tech.researched and tech.enabled and prereqs_met(tech, force) then
      -- Calculate a simple priority: prefer cheaper techs (fewer packs)
      local cost = tech.research_unit_count or 0
      table.insert(available, {
        tech = tech,
        cost = cost,
        level = tech.level or 1,
      })
    end
  end

  -- Sort by cost ascending (cheaper first), then by name
  table.sort(available, function(a, b)
    if a.cost ~= b.cost then
      return a.cost < b.cost
    end
    return a.tech.name < b.tech.name
  end)

  if #available == 0 then
    table.insert(lines, "  No technologies available to research.")
  else
    local show_count = math.min(#available, limit)
    for i = 1, show_count do
      local entry = available[i]
      table.insert(lines, "  " .. i .. ". " .. fmt_tech(entry.tech, false))
    end
    if #available > limit then
      table.insert(lines, "  ... and " .. (#available - limit) .. " more")
    end
  end

  table.insert(lines, "")
  table.insert(lines, "Total available: " .. #available)

  return table.concat(lines, "\n")
end

return M
