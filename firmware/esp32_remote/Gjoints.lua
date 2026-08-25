--[[
  toc_menu_lvgl.lua
  EdgeTX standalone Tools script, LVGL UI
  Target: Jumper T15 (Names Restored, Overview Fixed, Trim Removed)
]]

local CMD_TYPE = 0x32
local REALM    = 0x50
local DEST     = 0xEE
local ORIG     = 0xEA

local SUB_REQUEST_COUNT = 0x01
local SUB_COUNT_RESP    = 0x02
local SUB_REQUEST_ENTRY = 0x03
local SUB_ENTRY_RESP    = 0x04
local SUB_SELECT_PLAY   = 0x05
local SUB_ACK           = 0x06
local SUB_SET_FAVORITE  = 0x07
local SUB_REQUEST_JOINT = 0x10
local SUB_JOINT_RESP    = 0x11
local SUB_WRITE_JOINT   = 0x12
local SUB_WRITE_ACK     = 0x13

local CAT_JOINTS = 0
local CAT_ANIM  = 1
local CAT_AUDIO = 2
local CAT_IMAGE = 3
local catNames  = { [1] = "Animations", [2] = "Audio", [3] = "Images" }
local jointTypeNames = { "servo", "virtual", "continuous" }
local jointModeNames = { "angle", "rate" }

local ASSIGN_FILE = "/SCRIPTS/TOOLS/toc_assign.cfg"

local data = {
  counts = { [1] = 0, [2] = 0, [3] = 0 },
  entries = { [1] = {}, [2] = {}, [3] = {} },
  loaded  = { [1] = false, [2] = false, [3] = false },
  category = CAT_ANIM,
  cursor = 1,
  lastPlayed = nil,
  assignments = {},   
  prevActive = {},    
  dirty = true,
  exit = false,
  joints = {},
  jointCount = 0,
  jointsLoaded = false,
  jointsRequested = false,
  jointCursor = 1,
  pageState = "PLAY", -- Strict router to protect background redraws
}

local deferJoints = false
local deferOverview = false
local deferEdit = false

-- ---------------- wire helpers ----------------

local txQueue = {}

local function queueCmd(subcmd, payload)
  local d = { DEST, ORIG, REALM, subcmd }
  if payload then
    for _, b in ipairs(payload) do d[#d + 1] = b end
  end
  txQueue[#txQueue + 1] = d
end

local function pumpTxQueue()
  if #txQueue == 0 then return end
  if crossfireTelemetryPush(CMD_TYPE, txQueue[1]) then
    table.remove(txQueue, 1)
  end
end

local function requestCount(category)
  queueCmd(SUB_REQUEST_COUNT, { category })
end

local function requestEntry(category, idx)
  queueCmd(SUB_REQUEST_ENTRY, { category, idx % 256, math.floor(idx / 256) })
end

local function sendPlay(category, idx)
  queueCmd(SUB_SELECT_PLAY, { category, idx % 256, math.floor(idx / 256) })
end

local function sendSetFavorite(category, idx, fav)
  queueCmd(SUB_SET_FAVORITE, { category, idx % 256, math.floor(idx / 256), fav and 1 or 0 })
end

local function requestJointCount()
  queueCmd(SUB_REQUEST_COUNT, { CAT_JOINTS })
end

local function requestJoint(idx)
  queueCmd(SUB_REQUEST_JOINT, { idx % 256, math.floor(idx / 256) })
end

local function sendWriteJoint(j)
  if not j then return end
  
  -- Pads 6 dummy bytes (0,0) at the end so the current C++ firmware accepts the frame
  queueCmd(SUB_WRITE_JOINT, {
    j.id % 256, math.floor(j.id / 256),
    j.type,
    (j.channel == nil) and 0xFF or j.channel,
    j.reverse and 1 or 0,
    j.mode,
    j.min_us % 256, math.floor(j.min_us / 256),
    j.max_us % 256, math.floor(j.max_us / 256),
    0, 0, -- Dummy min_limit
    0, 0, -- Dummy max_limit
    0, 0, -- Dummy trim
  })
end

local function triggerNextCategory(currentCat)
  if currentCat == CAT_ANIM then requestCount(CAT_AUDIO)
  elseif currentCat == CAT_AUDIO then requestCount(CAT_IMAGE) end
end

local function bytesToName(d, startIdx)
  local chars = {}
  for i = startIdx, #d do
    if d[i] == 0 then break end
    chars[#chars + 1] = string.char(d[i])
  end
  return table.concat(chars)
end

local function handleRx(d)
  if #d < 4 or d[3] ~= REALM then return end
  local subcmd = d[4]

  if subcmd == SUB_COUNT_RESP then
    local category = d[5]
    local count = d[6] + d[7] * 256
    if category == CAT_JOINTS and not data.jointsLoaded then
      data.jointCount = count
      data.joints = {}
      if count == 0 then data.jointsLoaded = true
      else requestJoint(0) end
      data.dirty = true
    elseif category >= 1 and category <= 3 and not data.loaded[category] then
      data.counts[category] = count
      data.entries[category] = {}
      if count == 0 then
        data.loaded[category] = true
        triggerNextCategory(category)
      else
        requestEntry(category, 0)
      end
      if category == data.category then data.dirty = true end
    end

  elseif subcmd == SUB_JOINT_RESP then
    local idx = d[5] + d[6] * 256
    
    -- Restored byte index 21 so it correctly parses names from current ESP32 firmware
    data.joints[idx + 1] = {
      id = idx,
      name = bytesToName(d, 21), 
      type = d[7],
      channel = (d[8] == 0xFF) and nil or d[8],
      reverse = (d[9] % 2) == 1,
      mappable = (math.floor(d[9] / 2) % 2) == 1,
      mode = d[10],
      min_us = d[11] + d[12] * 256,
      max_us = d[13] + d[14] * 256,
      -- Limits and trim bytes (15 through 20) are strictly ignored
    }
    local nextIdx = idx + 1
    if nextIdx < data.jointCount then requestJoint(nextIdx)
    else data.jointsLoaded = true end
    data.dirty = true

  elseif subcmd == SUB_ENTRY_RESP then
    local category = d[5]
    local idx = d[6] + d[7] * 256
    local flags = d[8]
    local name = bytesToName(d, 9)
    if category >= 1 and category <= 3 then
      data.entries[category][idx + 1] = { id = idx, name = name, favorite = (flags % 2) == 1 }
      local nextIdx = idx + 1
      if nextIdx < data.counts[category] then
        requestEntry(category, nextIdx)
      else
        data.loaded[category] = true
        triggerNextCategory(category)
      end
      if category == data.category then data.dirty = true end
    end
  end
end

local function pollRx()
  for _ = 1, 8 do
    local cmd, pkt = crossfireTelemetryPop()
    if not cmd then break end
    if cmd == CMD_TYPE and pkt then handleRx(pkt) end
  end
end

-- ---------------- assignment persistence ----------------

local function loadAssignments()
  local f = io.open(ASSIGN_FILE, "r")
  if not f then return end
  while true do
    local line = io.read(f, 200)
    if not line or line == "" then break end
    local sw, cat, idx = string.match(line, "(%-?%d+),(%d+),(%d+)")
    if sw then
      data.assignments[tonumber(sw)] = { category = tonumber(cat), index = tonumber(idx) }
    end
  end
  io.close(f)
end

local function saveAssignments()
  local f = io.open(ASSIGN_FILE, "w")
  if not f then return end
  for swId, a in pairs(data.assignments) do
    io.write(f, tostring(swId) .. "," .. a.category .. "," .. a.index .. "\n")
  end
  io.close(f)
end

local function watchSwitches()
  for swId, a in pairs(data.assignments) do
    local active = (getValue(swId) == true)
    local wasActive = (data.prevActive[swId] == true)
    if active and not wasActive then sendPlay(a.category, a.index) end
    data.prevActive[swId] = active
  end
end

-- ---------------- LVGL UI ----------------

local showPlayPage

local function sliderRow(pg, x, y, w, label, getter, setter, minV, maxV)
  pg:label({
    x = x, y = y, w = w,
    text = function() return label .. ": " .. getter() end
  })
  pg:slider({
    x = x, y = y + 25, w = w, h = 20,
    min = minV, max = maxV,
    get = getter,
    set = setter
  })
end

local function openJointsPage()
  if lvgl == nil then return end
  data.pageState = "JOINTS"
  lvgl.clear()
  
  local j = data.joints[data.jointCursor]

  local pg = lvgl.page({
    title = "Joint Mapping",
    back = function()
      data.pageState = "PLAY"
      showPlayPage()
    end
  })

  if not data.jointsRequested then
    data.jointsRequested = true
    requestJointCount()
  end

  if not data.jointsLoaded then
    pg:label({ x = 10, y = 10, text = "Loading joints..." })
    return
  end
  if data.jointCount == 0 then
    pg:label({ x = 10, y = 10, text = "No joints configured." })
    return
  end

  local names = {}
  for i = 1, data.jointCount do
    names[i] = data.joints[i] and data.joints[i].name or "?"
  end

  pg:choice({
    x = 10, y = 10, w = 300, h = 40,
    title = "Joint: ",
    values = names,
    get = function() return data.jointCursor end,
    set = function(i)
      data.jointCursor = i
      openJointsPage()
    end
  })

  pg:button({ x = 320, y = 10, w = 140, h = 40, text = "Overview", press = function() deferOverview = true end })

  if not j then return end

  pg:label({ x = 10, y = 60, text = "Type: " .. (jointTypeNames[j.type + 1] or "?") .. (j.mappable and "" or "  (fixed, not mappable)") })

  local lo, hi = 500, 2500
  if j.type ~= 0 then lo, hi = 0, 255 end

  if j.mappable then
    local chOptions = {"None"}
    for i=1,16 do chOptions[i+1] = "CH" .. i end
    
    pg:choice({
      x = 10, y = 100, w = 200, h = 40,
      title = "Channel: ",
      values = chOptions,
      get = function() return (j.channel == nil) and 0 or (j.channel + 1) end,
      set = function(v) j.channel = (v == 0) and nil or (v - 1) end
    })
  end

  pg:label({ x = 10, y = 160, text = "Reverse:" })
  pg:toggle({
    x = 120, y = 155, w = 80, h = 40,
    get = function() return j.reverse end,
    set = function(s) j.reverse = (s == true or s == 1) end
  })

  pg:label({ x = 220, y = 160, text = "Rate mode:" })
  pg:toggle({
    x = 340, y = 155, w = 80, h = 40,
    get = function() return j.mode == 1 end,
    set = function(s) j.mode = (s == true or s == 1) and 1 or 0 end
  })

  sliderRow(pg, 10, 210, 200, "Min", function() return j.min_us end, function(v) j.min_us = v end, lo, hi)
  sliderRow(pg, 250, 210, 200, "Max", function() return j.max_us end, function(v) j.max_us = v end, lo, hi)

  -- Manual Sync Button
  pg:button({
    x = 10, y = 280, w = 440, h = 45,
    text = "Sync to Robot",
    press = function()
      if j then
        sendWriteJoint(j)
        playTone(800, 150, 50, PLAY_NOW)
      end
    end
  })
end

local function openJointsOverview()
  if lvgl == nil then return end
  data.pageState = "OVERVIEW"
  lvgl.clear()
  
  local pg = lvgl.page({ title = "Joint Mapping Overview", back = function() deferJoints = true end })

  local y = 10
  for i = 1, data.jointCount do
    local j = data.joints[i]
    if j then
      local chText
      if not j.mappable then chText = "fixed"
      elseif j.channel == nil then chText = "none"
      else chText = "CH" .. (j.channel + 1) end
      pg:label({ x = 10, y = y, text = j.name .. "  ->  " .. chText .. "  (" .. jointTypeNames[j.type + 1] .. ")" })
      y = y + 30
    end
  end
end

local function assignmentFor(category, id)
  for swId, a in pairs(data.assignments) do
    if a.category == category and a.index == id then return swId end
  end
  return nil
end

local function clearAssignmentsFor(category, id)
  for k, a in pairs(data.assignments) do
    if a.category == category and a.index == id then data.assignments[k] = nil end
  end
end

local function openAssignFor(category)
  if lvgl == nil then return end
  data.pageState = "ASSIGN"
  lvgl.clear()
  
  local pg = lvgl.page({ 
    title = "Settings", 
    subtitle = catNames[category], 
    back = function() 
      data.dirty = true 
      showPlayPage() 
    end 
  })

  local count = data.counts[category]
  if count == 0 then
    pg:label({ x = 10, y = 10, text = "List is empty." })
    return
  end

  local options = {}
  for i = 1, count do
    options[i] = data.entries[category][i].name
  end

  pg:choice({
    x = 10, y = 10, w = 450, h = 45,
    title = "Item: ",
    values = options,
    get = function() return data.cursor end,
    set = function(idx)
      data.cursor = idx
      openAssignFor(category) 
    end
  })

  local e = data.entries[category][data.cursor]
  if not e then return end

  pg:label({ x = 10, y = 80, text = "Shortcut:" })
  pg:switch({
    x = 100, y = 70, w = 180, h = 45,
    get = function() return assignmentFor(category, e.id) or 0 end,
    set = function(swId)
      clearAssignmentsFor(category, e.id)
      if swId and swId ~= 0 then
        data.assignments[swId] = { category = category, index = e.id }
      end
      saveAssignments()
    end
  })

  pg:label({ x = 10, y = 130, text = "Favorite:" })
  pg:toggle({
    x = 100, y = 120, w = 80, h = 45,
    get = function() return e.favorite end,
    set = function(state)
      local isFav = (state == true or state == 1)
      e.favorite = isFav
      sendSetFavorite(category, e.id, isFav)
    end
  })
end

local function switchDisplayName(swId)
  local ok, name = pcall(getSwitchName, swId)
  if ok and name then return name end
  return "SW" .. tostring(swId)
end

local function rowLabel(e)
  local fav = e.favorite and "* " or "  "
  local name = e.name or "?"
  local swId = assignmentFor(data.category, e.id)
  local mapStr = swId and ("    [" .. switchDisplayName(swId) .. "]") or ""
  return fav .. name .. mapStr
end

showPlayPage = function()
  if lvgl == nil then return end
  data.pageState = "PLAY"
  lvgl.clear()
  
  local pg = lvgl.page({ title = "TOC Play", subtitle = "Tap row to play, Edit for settings", back = function() data.exit = true end })

  local bx = 10
  for c = 1, 3 do
    local isSel = (c == data.category)
    local tabProps = {
      x = bx, y = 10, w = 110,
      text = isSel and ("[" .. catNames[c] .. "]") or catNames[c],
      press = function()
        data.category = c
        showPlayPage()
      end
    }
    if isSel then tabProps.color = COLOR_THEME_ACTIVE end
    pg:button(tabProps)
    bx = bx + 120
  end

  pg:button({
    x = 370, y = 10, w = 100,
    text = "Edit",
    press = function() deferEdit = true end
  })

  pg:button({
    x = 370, y = 55, w = 100,
    text = "Joints",
    press = function() deferJoints = true end
  })

  pg:label({ x = 10, y = 40, text = function() return "Last played: " .. (data.lastPlayed or "-") end })

  local count = data.counts[data.category]
  local loaded = data.loaded[data.category]
  local y = 105 

  if not loaded then
    pg:label({ x = 10, y = y, text = "Loading " .. catNames[data.category] .. "..." })
  elseif count == 0 then
    pg:label({ x = 10, y = y, text = "(empty)" })
  else
    local cat = data.category
    for i = 1, count do
      local e = data.entries[cat][i]
      local btnProps = {
        x = 10, y = y, w = 430, h = 45,
        text = rowLabel(e),
        press = function()
          data.cursor = i
          if e then
            sendPlay(cat, e.id)
            data.lastPlayed = e.name
            playHaptic(20, 0)
          end
          showPlayPage()
        end,
        longpress = function()
          data.cursor = i
          deferEdit = true
        end
      }
      if i == data.cursor then btnProps.color = COLOR_THEME_ACTIVE end
      pg:button(btnProps)
      y = y + 45
    end
  end
end

-- ---------------- lifecycle ----------------

local function init()
  if lvgl == nil then return end
  loadAssignments()
  requestCount(CAT_ANIM) 
  showPlayPage()
end

local function run(event, touchState)
  pollRx()
  pumpTxQueue()
  watchSwitches()

  -- Strict page routing based on state variables
  if deferJoints then
    deferJoints = false
    openJointsPage()
  end

  if deferOverview then
    deferOverview = false
    openJointsOverview()
  end

  if deferEdit then
    deferEdit = false
    openAssignFor(data.category)
  end

  if data.dirty then
    data.dirty = false
    if data.pageState == "JOINTS" then 
      openJointsPage() 
    elseif data.pageState == "OVERVIEW" then
      openJointsOverview()
    elseif data.pageState == "ASSIGN" then
      openAssignFor(data.category)
    else 
      showPlayPage() 
    end
  end

  if lvgl == nil then
    lcd.clear()
    lcd.drawText(0, 0, "Requires EdgeTX 2.11+ with LVGL", COLOR_THEME_WARNING)
  end

  if data.exit then return 2 end
  return 0
end

return { init = init, run = run, useLvgl = true }