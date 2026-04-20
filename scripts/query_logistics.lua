-- query_logistics.lua
-- Query logistics network status: robot counts, task stats, charging status,
-- and logistic chest content summaries.
--
-- Usage: /c require("scripts.query_logistics").query("query_type", {params})
--
-- Supported query types:
--   "summary"     - Overview of all logistics networks (robot counts, tasks, charging)
--   "networks"    - Detailed per-network breakdown
--   "robots"      - Robot statistics across all networks
--   "chests"      - Logistic chest content summary
--   "charging"    - Robot charging status per network

local M = {}

-- Helper: format a position
local function fmt_pos(pos)
  if not pos then return "nil" end
  return string.format("(%.1f, %.1f)", pos.x or 0, pos.y or 0)
end

-- Helper: serialize table to readable string
local function dump_table(t, indent)
  indent = indent or 0
  local lines = {}
  local prefix = string.rep("  ", indent)
  for k, v in pairs(t) do
    if type(v) == "table" then
      table.insert(lines, prefix .. tostring(k) .. ":")
      table.insert(lines, dump_table(v, indent + 1))
    elseif type(v) == "number" then
      if v == math.floor(v) then
        table.insert(lines, prefix .. tostring(k) .. ": " .. tostring(v))
      else
        table.insert(lines, prefix .. tostring(k) .. ": " .. string.format("%.2f", v))
      end
    else
      table.insert(lines, prefix .. tostring(k) .. ": " .. tostring(v))
    end
  end
  return table.concat(lines, "\n")
end

-- Collect all unique logistics networks across all surfaces
local function collect_networks(surface_filter)
  local networks = {}
  local seen = {}

  local surfaces
  if surface_filter then
    surfaces = { game.surfaces[surface_filter] }
  else
    surfaces = game.surfaces
  end

  for _, surface in pairs(surfaces) do
    if surface and surface.valid then
      local roboports = surface.find_entities_filtered({ type = "roboport" })
      for _, roboport in pairs(roboports) do
        if roboport and roboport.valid and roboport.logistic_network then
          local net = roboport.logistic_network
          -- Use the network object itself as key (Lua tables are compared by reference)
          if not seen[net] then
            seen[net] = true
            table.insert(networks, {
              network = net,
              surface = surface.name,
              center = roboport.position,
            })
          end
        end
      end
    end
  end

  return networks
end

-- Query: robots - robot statistics across all networks
local function query_robots(params)
  params = params or {}
  local net_list = collect_networks(params.surface)

  local total_logistic = 0
  local total_construction = 0
  local total_available_logistic = 0
  local total_available_construction = 0
  local total_active_logistic = 0
  local total_active_construction = 0
  local total_charging = 0
  local network_count = 0

  for _, net_info in pairs(net_list) do
    local net = net_info.network
    if net and net.valid then
      network_count = network_count + 1
      local log_robots = net.logistic_robots or 0
      local con_robots = net.construction_robots or 0
      local avail_log = net.available_logistic_robots or 0
      local avail_con = net.available_construction_robots or 0
      local active_log = log_robots - avail_log
      local active_con = con_robots - avail_con

      total_logistic = total_logistic + log_robots
      total_construction = total_construction + con_robots
      total_available_logistic = total_available_logistic + avail_log
      total_available_construction = total_available_construction + avail_con
      total_active_logistic = total_active_logistic + active_log
      total_active_construction = total_active_construction + active_con

      -- Count charging robots
      for _, robot in pairs(net.all_logistic_robots or {}) do
        if robot and robot.valid and robot.charging then
          total_charging = total_charging + 1
        end
      end
      for _, robot in pairs(net.all_construction_robots or {}) do
        if robot and robot.valid and robot.charging then
          total_charging = total_charging + 1
        end
      end
    end
  end

  return {
    query = "robots",
    surface_filter = params.surface,
    network_count = network_count,
    total_robots = total_logistic + total_construction,
    logistic_robots = {
      total = total_logistic,
      available = total_available_logistic,
      active = total_active_logistic,
    },
    construction_robots = {
      total = total_construction,
      available = total_available_construction,
      active = total_active_construction,
    },
    charging_robots = total_charging,
  }
end

-- Query: charging - robot charging status per network
local function query_charging(params)
  params = params or {}
  local net_list = collect_networks(params.surface)

  local networks = {}
  for _, net_info in pairs(net_list) do
    local net = net_info.network
    if net and net.valid then
      local charging_logistic = 0
      local charging_construction = 0
      local total_logistic = net.logistic_robots or 0
      local total_construction = net.construction_robots or 0

      for _, robot in pairs(net.all_logistic_robots or {}) do
        if robot and robot.valid and robot.charging then
          charging_logistic = charging_logistic + 1
        end
      end
      for _, robot in pairs(net.all_construction_robots or {}) do
        if robot and robot.valid and robot.charging then
          charging_construction = charging_construction + 1
        end
      end

      if total_logistic > 0 or total_construction > 0 then
        table.insert(networks, {
          surface = net_info.surface,
          center = fmt_pos(net_info.center),
          logistic_robots = {
            total = total_logistic,
            charging = charging_logistic,
            charging_pct = total_logistic > 0 and string.format("%.1f%%", charging_logistic / total_logistic * 100) or "0%",
          },
          construction_robots = {
            total = total_construction,
            charging = charging_construction,
            charging_pct = total_construction > 0 and string.format("%.1f%%", charging_construction / total_construction * 100) or "0%",
          },
        })
      end
    end
  end

  -- Sort by total robots descending
  table.sort(networks, function(a, b)
    return (a.logistic_robots.total + a.construction_robots.total) >
           (b.logistic_robots.total + b.construction_robots.total)
  end)

  return {
    query = "charging",
    surface_filter = params.surface,
    network_count = #networks,
    networks = networks,
  }
end

-- Query: chests - logistic chest content summary
local function query_chests(params)
  params = params or {}
  local net_list = collect_networks(params.surface)

  local networks = {}
  local grand_total_items = {}

  for _, net_info in pairs(net_list) do
    local net = net_info.network
    if net and net.valid then
      local chest_contents = net.get_contents()
      local robot_inventory = net.logistic_robot_inventory or {}

      local network_items = {}
      local total_stored = 0
      local total_in_transit = 0

      -- Merge chest contents
      for name, count in pairs(chest_contents) do
        network_items[name] = { stored = count, in_transit = 0, total = count }
        total_stored = total_stored + count
        if not grand_total_items[name] then grand_total_items[name] = 0 end
        grand_total_items[name] = grand_total_items[name] + count
      end

      -- Merge robot inventory (items in transit)
      for name, count in pairs(robot_inventory) do
        if network_items[name] then
          network_items[name].in_transit = count
          network_items[name].total = network_items[name].stored + count
        else
          network_items[name] = { stored = 0, in_transit = count, total = count }
        end
        total_in_transit = total_in_transit + count
        if not grand_total_items[name] then grand_total_items[name] = 0 end
        grand_total_items[name] = grand_total_items[name] + count
      end

      -- Sort items by total count descending
      local sorted_items = {}
      for name, data in pairs(network_items) do
        table.insert(sorted_items, { name = name, stored = data.stored, in_transit = data.in_transit, total = data.total })
      end
      table.sort(sorted_items, function(a, b) return a.total > b.total end)

      -- Limit to top items if requested
      local max_items = params.max_items or 20
      if #sorted_items > max_items then
        sorted_items = { unpack(sorted_items, 1, max_items) }
      end

      local chest_count = 0
      for _, chest in pairs(net.logistic_chests or {}) do
        if chest and chest.valid then chest_count = chest_count + 1 end
      end

      table.insert(networks, {
        surface = net_info.surface,
        center = fmt_pos(net_info.center),
        chest_count = chest_count,
        total_stored = total_stored,
        total_in_transit = total_in_transit,
        items = sorted_items,
      })
    end
  end

  -- Sort networks by total items descending
  table.sort(networks, function(a, b)
    return (a.total_stored + a.total_in_transit) > (b.total_stored + b.total_in_transit)
  end)

  -- Grand total items sorted
  local grand_sorted = {}
  for name, count in pairs(grand_total_items) do
    table.insert(grand_sorted, { name = name, total = count })
  end
  table.sort(grand_sorted, function(a, b) return a.total > b.total end)

  return {
    query = "chests",
    surface_filter = params.surface,
    network_count = #networks,
    networks = networks,
    grand_total_items = grand_sorted,
  }
end

-- Query: networks - detailed per-network breakdown
local function query_networks(params)
  params = params or {}
  local net_list = collect_networks(params.surface)

  local networks = {}
  for _, net_info in pairs(net_list) do
    local net = net_info.network
    if net and net.valid then
      local log_robots = net.logistic_robots or 0
      local con_robots = net.construction_robots or 0
      local avail_log = net.available_logistic_robots or 0
      local avail_con = net.available_construction_robots or 0
      local active_log = log_robots - avail_log
      local active_con = con_robots - avail_con

      -- Charging counts
      local charging_log = 0
      local charging_con = 0
      for _, robot in pairs(net.all_logistic_robots or {}) do
        if robot and robot.valid and robot.charging then charging_log = charging_log + 1 end
      end
      for _, robot in pairs(net.all_construction_robots or {}) do
        if robot and robot.valid and robot.charging then charging_con = charging_con + 1 end
      end

      -- Roboport count
      local roboport_count = 0
      for _, rp in pairs(net.roboports or {}) do
        if rp and rp.valid then roboport_count = roboport_count + 1 end
      end

      -- Chest count
      local chest_count = 0
      for _, chest in pairs(net.logistic_chests or {}) do
        if chest and chest.valid then chest_count = chest_count + 1 end
      end

      -- Storage summary
      local chest_contents = net.get_contents()
      local robot_inv = net.logistic_robot_inventory or {}
      local total_stored = 0
      local total_in_transit = 0
      for _, count in pairs(chest_contents) do total_stored = total_stored + count end
      for _, count in pairs(robot_inv) do total_in_transit = total_in_transit + count end

      table.insert(networks, {
        surface = net_info.surface,
        center = fmt_pos(net_info.center),
        roboports = roboport_count,
        chests = chest_count,
        logistic_robots = {
          total = log_robots,
          available = avail_log,
          active = active_log,
          charging = charging_log,
        },
        construction_robots = {
          total = con_robots,
          available = avail_con,
          active = active_con,
          charging = charging_con,
        },
        storage = {
          stored = total_stored,
          in_transit = total_in_transit,
        },
      })
    end
  end

  -- Sort by total robots descending
  table.sort(networks, function(a, b)
    return (a.logistic_robots.total + a.construction_robots.total) >
           (b.logistic_robots.total + b.construction_robots.total)
  end)

  return {
    query = "networks",
    surface_filter = params.surface,
    network_count = #networks,
    networks = networks,
  }
end

-- Query: summary - condensed overview
local function query_summary(params)
  params = params or {}
  local net_list = collect_networks(params.surface)

  local total_logistic = 0
  local total_construction = 0
  local total_active_logistic = 0
  local total_active_construction = 0
  local total_charging = 0
  local total_stored = 0
  local total_in_transit = 0
  local total_roboports = 0
  local total_chests = 0
  local network_count = 0

  for _, net_info in pairs(net_list) do
    local net = net_info.network
    if net and net.valid then
      network_count = network_count + 1

      local log_robots = net.logistic_robots or 0
      local con_robots = net.construction_robots or 0
      local avail_log = net.available_logistic_robots or 0
      local avail_con = net.available_construction_robots or 0

      total_logistic = total_logistic + log_robots
      total_construction = total_construction + con_robots
      total_active_logistic = total_active_logistic + (log_robots - avail_log)
      total_active_construction = total_active_construction + (con_robots - avail_con)

      for _, robot in pairs(net.all_logistic_robots or {}) do
        if robot and robot.valid and robot.charging then total_charging = total_charging + 1 end
      end
      for _, robot in pairs(net.all_construction_robots or {}) do
        if robot and robot.valid and robot.charging then total_charging = total_charging + 1 end
      end

      for _, rp in pairs(net.roboports or {}) do
        if rp and rp.valid then total_roboports = total_roboports + 1 end
      end
      for _, chest in pairs(net.logistic_chests or {}) do
        if chest and chest.valid then total_chests = total_chests + 1 end
      end

      local contents = net.get_contents()
      local robot_inv = net.logistic_robot_inventory or {}
      for _, count in pairs(contents) do total_stored = total_stored + count end
      for _, count in pairs(robot_inv) do total_in_transit = total_in_transit + count end
    end
  end

  local total_robots = total_logistic + total_construction
  local total_active = total_active_logistic + total_active_construction
  local total_available = total_robots - total_active

  return {
    query = "summary",
    surface_filter = params.surface,
    network_count = network_count,
    roboports = total_roboports,
    chests = total_chests,
    robots = {
      total = total_robots,
      logistic = total_logistic,
      construction = total_construction,
      active = total_active,
      available = total_available,
      charging = total_charging,
    },
    storage = {
      stored = total_stored,
      in_transit = total_in_transit,
    },
  }
end

-- Main query dispatcher
function M.query(query_type, params)
  local dispatch = {
    summary = query_summary,
    networks = query_networks,
    robots = query_robots,
    chests = query_chests,
    charging = query_charging,
  }

  local fn = dispatch[query_type]
  if not fn then
    local valid = {}
    for k in pairs(dispatch) do table.insert(valid, k) end
    table.sort(valid)
    return { error = "Unknown query type: " .. tostring(query_type), valid_types = valid }
  end

  local result = fn(params)
  rcon.print(dump_table(result))
  return result
end

return M
