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
local bindError = nil   -- last bind failure, so it is only logged once
local READ_SIZE = 65536

-- BeamNG provides the global log(level, origin, msg). extensions.core.log does
-- not exist, and calling it with two arguments would drop the origin anyway, so
-- every log line was being discarded silently - which is exactly why the game
-- log showed nothing from this extension.
local LOG_ORIGIN = 'sendspinRadio'

local function log(level, fmt, ...)
  if type(_G.log) ~= 'function' then return end
  local msg
  if select('#', ...) > 0 then
    local ok, formatted = pcall(string.format, fmt, ...)
    msg = ok and formatted or tostring(fmt)
  else
    msg = tostring(fmt)
  end
  pcall(_G.log, level, LOG_ORIGIN, msg)
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
--
-- luasocket's receive() returns (line|nil, err, partial). On a non-blocking
-- socket that has data waiting it returns (line, nil, partial) - the payload is
-- the THIRD value. Wrapping that in pcall shifts EVERYTHING right by one, so
-- through pcall the payload lands in the FOURTH return and reading the third
-- yielded nil, which this loop then treated as "nothing to do".
local function drainUpstream()
  if not (upstream and pageSock) then return end
  while true do
    -- Only read what select says is actually there. Reading speculatively on a
    -- non-blocking socket returns err='closed' for a perfectly healthy
    -- connection that simply has nothing queued yet, and that error then tore
    -- down the link in a loop.
    local readable, _, _, err = socket.select({ upstream }, nil, 0)
    if err then
      log('W', 'select on upstream failed: %s', tostring(err))
      closeQuietly(upstream, 'upstream')
      return
    end
    if #readable == 0 then return end

    local ok, line, rerr, chunk = pcall(upstream.receive, upstream, READ_SIZE)
    if not ok then
      log('E', 'upstream receive raised: %s', tostring(line))
      closeQuietly(upstream, 'upstream')
      return
    end
    if not chunk or chunk == '' then chunk = line end
    if not chunk or chunk == '' then
      if rerr and rerr ~= 'timeout' and rerr ~= 'closed' then
        log('W', 'upstream read ended: %s', tostring(rerr))
        closeQuietly(upstream, 'upstream')
      end
      return
    end
    local sent, serr = pageSock:send(chunk)
    if not sent and serr ~= 'timeout' then
      log('W', 'could not deliver to page (%s), dropping upstream', tostring(serr))
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
    -- startListener is retried from the update hook, so a failure that is
    -- logged every single tick would flood the console with thousands of
    -- identical lines and cost frames. Report it once, then stay quiet.
    if bindError ~= tostring(err) then
      bindError = tostring(err)
      log('E', 'cannot bind %s:%d: %s', M.LOCAL_HOST, M.LOCAL_PORT, bindError)
    end
    pcall(function() sock:close() end)
    return nil
  end
  bindError = nil

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

  -- socket.select returns (readable, writable, exceptional, err). With a zero
  -- timeout the third result carries the string 'timeout' when nothing is
  -- pending, NOT the fourth. Reading err here made this always look like a
  -- real error, so the accept below was never reached.
  local readable, _, exceptional, err = socket.select({ listener }, nil, 0)
  if err then
    log('W', 'select on listener failed: %s', tostring(err))
    return
  end
  if #readable == 0 then return end

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
    -- Same select contract as above: 'timeout' arrives in the third result.
    local readable, _, exceptional, err = socket.select({ pageSock }, nil, 0)
    if err then
      log('W', 'select on page socket failed: %s', tostring(err))
      closeQuietly(pageSock, 'page socket')
    elseif #readable == 0 then
      -- nothing waiting, fall through to the other direction
    else
      -- receive() through pcall returns (ok, line, err, partial): the pcall
      -- boolean shifts the real values right by one. Data waiting on a
      -- non-blocking socket lands in slot 4.
      local ok, line, rerr, chunk = pcall(pageSock.receive, pageSock, READ_SIZE)
      if not ok then
        log('W', 'page receive raised: %s', tostring(line))
        closeQuietly(pageSock, 'page socket')
        return
      end
      if not chunk or chunk == '' then chunk = line end
      if chunk and chunk ~= '' then
        partial = partial .. chunk
        -- send() returns the number of bytes written; a would-block write
        -- returns nil,'timeout'. Keep the unwritten remainder for the next pump
        -- and only give up on a real error.
        local sent, serr = upstream:send(partial)
        if type(sent) == 'number' then
          partial = partial:sub(sent + 1)
        elseif serr ~= 'timeout' then
          log('W', 'upstream send failed (%s), dropping link', tostring(serr))
          closeQuietly(upstream, 'upstream')
        end
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
  -- Anything buffered belonged to the old link; forwarding it to a different
  -- server would corrupt the new stream from the first byte.
  partial = ''
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

-- BeamNG calls onExtensionUnloaded. `onUnload` is never fired, so without this
-- the listener and both sockets would survive a level change and the bind would
-- fail on reload.
M.onExtensionUnloaded = function()
  M.stop()
end
M.onUnload = M.onExtensionUnloaded

-- BeamNG's GE frame hook is onUpdate ("called once per GFX frame"); onGuiUpdate
-- runs at UI rate. There is no onCfxUpdate in BeamNG - that is a FiveM name -
-- so with it the accept/pump pair was never called at all.
--
-- onGuiUpdate is the one that matters: the page's WebSocket lives in the UI
-- thread, so this is what keeps audio flowing while the game is paused.
M.onGuiUpdate = function()
  if not listener then
    startListener()
    return
  end
  acceptPage()
  pump()
end

-- Also pump on graphics frames so the relay keeps working with no UI open, but
-- only every few frames: a socket does not need graphics-frame cadence and
-- select() on every rendered frame costs frames for nothing.
local frameCounter = 0
local FRAME_STRIDE = 6

M.onUpdate = function()
  if not listener then
    startListener()
    return
  end
  frameCounter = frameCounter + 1
  if frameCounter < FRAME_STRIDE then return end
  frameCounter = 0
  acceptPage()
  pump()
end

return M
