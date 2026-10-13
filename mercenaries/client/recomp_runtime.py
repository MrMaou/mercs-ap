'''
Lua 5.0 runtime installed into the Mercenaries Recompiled script VM.

This replaces the bytecode patching that the PCSX2 backend does. Instead of
hijacking constant slots in existing functions, we define an AP table and a few
global functions, and swap three game globals for wrappers:

- gameflow_GetIntelTotal  -> returns the intel total the client sets
- AttemptFactionMoodClamp -> applies the reputation floors the client sets
- Shop_UnlockItem         -> ignores vanilla unlocks; AP unlocks go through

The game can re-run its own scripts (for example after a load), which can put
the original functions back. AP_EnsureHooks re-applies the wrappers and is
called on every poll, so that is harmless.

The VM is rebuilt when the player loads a save. All AP state lives in the VM, so
the client detects the rebuild (AP_Version is nil again) and reinstalls this
runtime, then re-sends intel, floors and shop unlocks; those are idempotent.

Save binding (used by the in-game client): a few number keys in scribble memory,
which the game stores in the save file, so they always describe the loaded save.
  ap_seed      stamp of the seed/team/slot this save belongs to (0 = unbound)
  ap_n<id>     copies of one-shot item <id> (cash, free samples) delivered to it
  ap_tick      written on every sync; a different value read back means the
               save data was replaced (a load) even if the VM was not rebuilt
Number keys only: string length limits in scribble memory are not known.

The game's VM has only the base and table libraries: no string, no math. Keep
this code to the core language, tostring/tonumber and table.*; anything that
needs string work (matching shop template names) is done by the client.
'''

RUNTIME_VERSION = 'ap-recomp-4'

RUNTIME = r'''
AP = AP or {}
AP.version = '@VERSION@'
AP.intel = AP.intel or 0
AP.floors = AP.floors or {}
AP.shop = AP.shop or {}
AP.unlocked = AP.unlocked or {}
AP.delivered = AP.delivered or {}
AP.allow_shop = false

function AP_Version()
  return AP.version
end

function AP_IntelTotal(chapter)
  return AP.intel
end

function AP_MoodClamp()
  if type(Faction_SetMinimumRelation) ~= 'function' then return end
  for faction, floor in pairs(AP.floors) do
    Faction_SetMinimumRelation(faction, floor)
  end
end

-- Hook bookkeeping lives outside AP so it survives a runtime reinstall into
-- the same VM: a wrapper from an earlier install must never be mistaken for the
-- game's original function (the wrapper would then call itself forever).
AP_WRAPPERS = AP_WRAPPERS or {}
AP_ORIGINALS = AP_ORIGINALS or {}

function AP_ShopUnlock(template)
  local real = AP_ORIGINALS.Shop_UnlockItem
  if AP.allow_shop and real then
    return real(template)
  end
  -- Vanilla unlock (e.g. after selling an ODF): suppressed, AP owns the shop.
  AP.blocked = (AP.blocked or 0) + 1
end

AP_WRAPPERS[AP_IntelTotal] = true
AP_WRAPPERS[AP_MoodClamp] = true
AP_WRAPPERS[AP_ShopUnlock] = true

local function ap_hook(name, wrapper)
  local current = _G[name]
  if type(current) ~= 'function' or current == wrapper then return end
  if not AP_WRAPPERS[current] then
    AP_ORIGINALS[name] = current
  end
  _G[name] = wrapper
end

function AP_EnsureHooks()
  ap_hook('gameflow_GetIntelTotal', AP_IntelTotal)
  ap_hook('AttemptFactionMoodClamp', AP_MoodClamp)
  ap_hook('Shop_UnlockItem', AP_ShopUnlock)
end

-- Location data, as "key=value" lines.
function AP_Poll()
  AP_EnsureHooks()
  local out = {}
  local function put(key, value)
    table.insert(out, key .. '=' .. tostring(value))
  end
  put('version', AP.version)
  local quadrant_name = quadrant
  if type(quadrant_name) ~= 'string' and type(Utility_ReadStringFromScribbleMemory) == 'function' then
    quadrant_name = Utility_ReadStringFromScribbleMemory('SkipTo_Map')
  end
  put('quadrant', quadrant_name or '')
  put('blocked_shop', AP.blocked or 0)
  if type(Utility_ReadNumberFromScribbleMemory) == 'function' then
    local factions = {'allies', 'china', 'mafia', 'sk'}
    for _, faction in ipairs(factions) do
      put('mission.' .. faction, Utility_ReadNumberFromScribbleMemory('current_' .. faction .. '_mission') or 0)
    end
  end
  if type(suit_sequence) == 'table' and type(gameflow_GetCardScribbleMemoryVariableName) == 'function'
      and type(Utility_ReadStringFromScribbleMemory) == 'function'
      and type(CARD_RANK_MIN) == 'number' and type(CARD_RANK_MAX) == 'number' then
    local seen = {}
    for _, suit in pairs(suit_sequence) do
      if type(suit) == 'string' and not seen[suit] then
        seen[suit] = true
        for rank = CARD_RANK_MIN, CARD_RANK_MAX do
          local key = gameflow_GetCardScribbleMemoryVariableName(suit, rank)
          local state = Utility_ReadStringFromScribbleMemory(key)
          local code = 1
          if state ~= nil and state == stateKilled then
            code = 2
          elseif state ~= nil and state == stateCaptured then
            code = 3
          end
          -- At large (1) is the default; leaving it out keeps the reply and
          -- the garbage it makes small.
          if code ~= 1 then put('card.' .. suit .. '.' .. rank, code) end
        end
      end
    end
  end
  return table.concat(out, '\n')
end

-- Called regularly during normal gameplay: keeps hooks and floors applied and
-- lets the game notice when AP intel is enough for the Ace mission.
function AP_Tick()
  AP_EnsureHooks()
  AP_MoodClamp()
  if type(gameflow_AttemptAceMissionUnlock) == 'function' then
    gameflow_AttemptAceMissionUnlock()
  end
  return 'ok'
end

function AP_SetIntel(value)
  AP.intel = value
  return 'ok'
end

function AP_SetFloors(floors)
  AP.floors = floors
  AP_MoodClamp()
  return 'ok'
end

-- templates: exact shop template names (the client matches them against
-- AP_ShopTable). Unlocks each at most once per VM. Returns how many were
-- unlocked now, followed by '|' and the failures if the game refused some.
function AP_SetShop(templates)
  AP_EnsureHooks()
  local real_unlock = AP_ORIGINALS.Shop_UnlockItem
  if not real_unlock then return 'nohook' end
  local applied = 0
  local failed = {}
  AP.shop = {}
  for _, template in ipairs(templates) do
    AP.shop[template] = true
    if not AP.unlocked[template] then
      AP.allow_shop = true
      local ok, err = pcall(real_unlock, template)
      AP.allow_shop = false
      if ok then
        AP.unlocked[template] = true
        applied = applied + 1
      else
        -- Keep going: one unlock the game refuses must not block the others.
        -- It is retried next time.
        table.insert(failed, template .. ': ' .. tostring(err))
      end
    end
  end
  if table.getn(failed) > 0 then return applied .. '|' .. table.concat(failed, '; ') end
  return applied
end

local function ap_read_number(key)
  local value = Utility_ReadNumberFromScribbleMemory(key)
  if type(value) ~= 'number' then return 0 end
  return value
end

-- ids: one-shot item ids. Returns "stamp=..", "tick=.." and "<id>=<count>"
-- lines (the tick read before tick is replaced by new_tick), or "" when
-- scribble memory is unavailable.
function AP_SyncSave(ids, new_tick)
  if type(Utility_ReadNumberFromScribbleMemory) ~= 'function'
      or type(Utility_WriteNumberToScribbleMemory) ~= 'function' then
    return ''
  end
  local out = {'stamp=' .. ap_read_number('ap_seed'), 'tick=' .. ap_read_number('ap_tick')}
  for _, id in ipairs(ids) do
    local count = ap_read_number('ap_n' .. id)
    if count > 0 then table.insert(out, id .. '=' .. count) end
  end
  Utility_WriteNumberToScribbleMemory('ap_tick', new_tick)
  return table.concat(out, '\n')
end

-- Binds an unbound save to a seed. 'fail' if the value does not read back.
function AP_StampSave(stamp)
  Utility_WriteNumberToScribbleMemory('ap_seed', stamp)
  if ap_read_number('ap_seed') ~= stamp then return 'fail' end
  return 'ok'
end

-- The save data changed under us: forget what this VM believes it applied.
function AP_ForgetApplied()
  AP.unlocked = {}
  return 'ok'
end

-- counts (optional): {[item id] = copies delivered}, written to the save after
-- the delivery, so cash and the record of it are saved (or lost) together.
function AP_Deliver(id, money, message, support, counts)
  if AP.delivered[id] then return 'dup' end
  if money and money ~= 0 then
    Player_SetMoney(Player_GetMoney() + money)
  end
  if message and message ~= '' and type(Ui_PrintHudMessage) == 'function' then
    Ui_PrintHudMessage(message)
  end
  if support and support ~= '' then
    Support_AddItem('template_support_' .. support, 1)
  end
  if counts then
    for item, count in pairs(counts) do
      Utility_WriteNumberToScribbleMemory('ap_n' .. item, count)
    end
  end
  AP.delivered[id] = true
  return 'ok'
end

-- Shop entries as "index=template" lines, for checking the template names.
function AP_ShopTable()
  local out = {}
  if type(tMafiaShop) ~= 'table' then return '' end
  for index, entry in pairs(tMafiaShop) do
    if type(entry) == 'table' then
      table.insert(out, tostring(index) .. '=' .. tostring(entry.template))
    end
  end
  return table.concat(out, '\n')
end

AP_EnsureHooks()
return AP.version
'''.replace('@VERSION@', RUNTIME_VERSION)
