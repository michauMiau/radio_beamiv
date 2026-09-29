-- Luacheck configuration for the Sendspin Radio mod.
--
-- BeamNG runs every Lua extension inside the GELua sandbox, where `log` and the
-- extension loader helpers are injected globals that no Lua distribution ships.
-- Declaring them here keeps the lint signal about OUR code instead of about
-- the host we run in.

std = "lua51"

-- Injected by the GELua host at runtime; not defined by any Lua library.
read_globals = {
    "log",
    "setExtensionUnloadMode",
    "loadManualUnloadExtensions",
    "extensions",
    "core",
    "ge",
}

-- _G.log is deliberately shadowed by a local wrapper in the relay so that a
-- missing global degrades to silence instead of raising. The local `socket` is
-- loaded through pcall(require) and may legitimately be nil.
globals = {
    "UPS",
}

max_line_length = 100

files["mod/scripts/**/*.lua"] = {
    -- The mod script talks to the loader, which returns values we ignore.
    ignore = { "212/_unused" },
}
