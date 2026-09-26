-- SendspinRadio bridge — Lua side.
--
-- Why this file exists: BeamNG's Vue page runs under a strict Content Security
-- Policy whose connect-src allows loopback only. A WebSocket aimed at the LAN
-- (ws://<music-assistant>:8927/sendspin) is blocked by the browser, and
-- -nosandbox does not relax CSP. BeamMP works around this with a separate
-- localhost launcher; this relay does the same job, in the other direction.
--
-- The extension owns a local TCP listener on 127.0.0.1 and a single upstream TCP
-- connection to the Music Assistant Sendspin server, pumping bytes between them.
-- The Vue side hands the SDK a ready-made WebSocket pointed at loopback, which
-- satisfies CSP.
--
-- BeamNG ships LuaSocket, but the import path is not stable across builds and
-- is not valid from inside lua/ge/extensions in all of them; see loadSocket()
-- below for the resolved import and the fallbacks it tries.

local M = {}

M.UPSTREAM_HOST = '192.168.1.198'
M.UPSTREAM_PORT = 8927
M.LOCAL_HOST = '127.0.0.1'
M.LOCAL_PORT = 18124

local listener = nil   -- listening socket on loopback
local pageSock = nil    -- connection from the Vue page
local upstream = nil    -- connection to Music Assistant
local partial = ''      -- bytes buffered heading upstream
local READ_SIZE = 65536

local function log(level, fmt, ...)
  local fn = extensions and extensions.core and extensions.core.log
  if not fn then return end
  if select('#', ...) > 0 then
    fn(level, '[SendspinRadio] ' .. string.format(fmt, ...))
  else
    fn(level, '[SendspinRadio] ' .. tostring(fmt))
  end
end

local function closeQuietly(sock, what)
  if not sock then return end
  pcall(function() sock:close() end)
  log('I', '%s closed', what)
end

-- BeamNG ships LuaSocket, but the import path is not stable across builds and
-- is not valid from inside lua/ge/extensions in all of them. Try every known
-- spelling and fail loudly, so the page sees a real reason instead of a silent
-- socket timeout.
local function loadSocket()
  local candidates = {
    'socket',
    'libs/luasocket/socket.socket',
    'libs/luasocket/socket',
  }
  local lastErr
  for _, name in ipairs(candidates) do
    local ok, mod = pcall(require, name)
    if ok and type(mod) == 'table' and mod.tcp then
      log('I', 'LuaSocket loaded via %s', name)
      return mod
    end
    lastErr = mod
  end
  log('E', 'LuaSocket unavailable (%s) — relay cannot start', tostring(lastErr))
  return nil
end

local socket = loadSocket()

local function connectUpstream()
  if upstream then return upstream end
  if not socket then
    log('E', 'connectUpstream: no LuaSocket')
    return nil
  end

  local sock = socket.tcp()
  pcall(function() sock:setoption('keepalive', true) end)
  pcall(function() sock:setoption('tcp-nodelay', true) end)
  -- Bounded connect timeout: a blocking connect to a dead host would hang the game.
  sock:settimeout(0.25)

  local ok, err = sock:connect(M.UPSTREAM_HOST, M.UPSTREAM_PORT)
  if not ok then
    log('E', 'upstream connect to %s:%d failed: %s', M.UPSTREAM_HOST, M.UPSTREAM_PORT, tostring(err))
    pcall(function() sock:close() end)
    return nil
  end

  sock:settimeout(0)
  upstream = sock
  log('I', 'upstream connected: %s:%d', M.UPSTREAM_HOST, M.UPSTREAM_PORT)
  return upstream
end

-- Forward anything buffered on the upstream link back to the page.
local function drainUpstream()
  if not (upstream and pageSock) then return end
  while true do
    local ok, data, err = pcall(upstream.receive, upstream, READ_SIZE)
    if not ok then
      log('E', 'upstream receive failed')
      closeQuietly(upstream, 'upstream')
      return
    end
    if data == nil or data == '' then
      if err and err ~= 'timeout' then
        log('W', 'upstream read ended: %s', tostring(err))
        closeQuietly(upstream, 'upstream')
      end
      return
    end
    local sent = pcall(function() return pageSock:send(data) end)
    if not sent then
      log('W', 'could not deliver to page, dropping upstream')
      closeQuietly(upstream, 'upstream')
      return
    end
  end
end

local function startListener()
  if listener then return listener end
  if not socket then
    log('E', 'startListener: no LuaSocket')
    return nil
  end

  local sock = socket.tcp()
  pcall(function() sock:setoption('reuseaddr', true) end)

  local bound, err = sock:bind(M.LOCAL_HOST, M.LOCAL_PORT)
  if not bound then
    log('E', 'cannot bind %s:%d: %s', M.LOCAL_HOST, M.LOCAL_PORT, tostring(err))
    pcall(function() sock:close() end)
    return nil
  end

  if not sock:listen(8) then
    log('E', 'listen failed on %s:%d', M.LOCAL_HOST, M.LOCAL_PORT)
    pcall(function() sock:close() end)
    return nil
  end

  sock:settimeout(0)
  listener = sock
  log('I', 'relay listening on %s:%d -> %s:%d', M.LOCAL_HOST, M.LOCAL_PORT,
      M.UPSTREAM_HOST, M.UPSTREAM_PORT)
  return listener
end

local function acceptPage()
  if not listener then return end

  local readable = { listener }
  local _, _, err = socket.select(readable, nil, 0)
  if err ~= 'timeout' then
    if err then log('W', 'select on listener failed: %s', tostring(err)) end
    return
  end

  local sock, addr = listener:accept()
  if not sock then return end
  sock:settimeout(0)

  -- A reconnecting page can still be half-closed when it dials back in, so drop
  -- the stale upstream too. Reusing it would strand the new session on a dead
  -- stream, which the page reports as a socket error.
  closeQuietly(pageSock, 'previous page socket')
  closeQuietly(upstream, 'previous upstream')
  pageSock = sock
  upstream = nil
  partial = ''
  log('I', 'page connected (%s), opening upstream', tostring(addr))

  if not connectUpstream() then
    log('E', 'no upstream — the page will see a closed stream')
  end
end

-- One pump per frame, in both directions, never blocking.
local function pump()
  if not pageSock then return end

  -- page -> upstream
  if upstream then
    local readable = { pageSock }
    local _, _, err = socket.select(readable, nil, 0)
    if err == 'timeout' then
      -- nothing waiting, fall through to the other direction
    elseif err then
      log('W', 'select on page socket failed: %s', tostring(err))
      closeQuietly(pageSock, 'page socket')
    else
      local ok, data, rerr = pcall(pageSock.receive, pageSock, READ_SIZE)
      if ok and data and data ~= '' then
        partial = partial .. data
        local sent = pcall(function() return upstream:send(partial) end)
        if sent then
          partial = ''
        else
          log('W', 'upstream send failed, dropping link')
          closeQuietly(upstream, 'upstream')
        end
      elseif not ok then
        closeQuietly(pageSock, 'page socket')
      elseif rerr and rerr ~= 'timeout' and rerr ~= 'closed' then
        log('W', 'page read: %s', tostring(rerr))
      end
    end
  end

  drainUpstream()
end

M.setUpstream = function(host, port)
  if host and host ~= '' then M.UPSTREAM_HOST = tostring(host) end
  if port then M.UPSTREAM_PORT = tonumber(port) or M.UPSTREAM_PORT end
  log('I', 'upstream now %s:%d', M.UPSTREAM_HOST, M.UPSTREAM_PORT)
  closeQuietly(upstream, 'upstream')
  upstream = nil
  return M.UPSTREAM_HOST, M.UPSTREAM_PORT
end

M.getUpstream = function()
  return M.UPSTREAM_HOST, M.UPSTREAM_PORT
end

M.getLocal = function()
  return M.LOCAL_HOST, M.LOCAL_PORT
end

M.isRunning = function()
  return listener ~= nil
end

-- One-line diagnosis for the Vue side. Returning a single string keeps the
-- bridge call cheap, and lets the page show a real reason instead of a bare
-- "connection failed" when the relay is down.
M.getStatus = function()
  if not socket then
    return 'LuaSocket could not be loaded in this build - the relay cannot run'
  end
  if not listener then
    return string.format(
      'relay is not listening on %s:%d (bind or listen failed, see the log)',
      M.LOCAL_HOST, M.LOCAL_PORT)
  end
  if not upstream then
    return string.format(
      'relay is up on %s:%d, no upstream yet',
      M.LOCAL_HOST, M.LOCAL_PORT)
  end
  return string.format('relay %s:%d -> %s:%d ok', M.LOCAL_HOST, M.LOCAL_PORT,
    M.UPSTREAM_HOST, M.UPSTREAM_PORT)
end

M.start = startListener
M.stop = function()
  closeQuietly(pageSock, 'page socket')
  closeQuietly(upstream, 'upstream')
  closeQuietly(listener, 'listener')
  pageSock = nil
  upstream = nil
  listener = nil
  partial = ''
end

M.reconnect = function()
  closeQuietly(upstream, 'upstream')
  upstream = nil
  return connectUpstream() ~= nil
end

-- The modern hook. `onLoad` is deprecated and is not called by current
-- builds, so the listener would never start without this.
M.onExtensionLoaded = function()
  startListener()
  -- Report reachability at load, but do not keep the connection open: the page
  -- may connect much later.
  if connectUpstream() then
    closeQuietly(upstream, 'upstream probe')
  end
end

-- Kept so older builds still work.
M.onLoad = M.onExtensionLoaded

M.onUnload = function()
  M.stop()
end

-- onUpdate runs once per rendered frame, which is far too often for select()
-- and costs frames. onCfxUpdate is driven by the extension scheduler and is the
-- right cadence for pumping a socket: still responsive, but not per-frame.
M.onCfxUpdate = function()
  if not listener then
    startListener()
    return
  end
  acceptPage()
  pump()
end

return M
