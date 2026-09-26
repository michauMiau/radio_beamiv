-- Mod script for Sendspin Radio.
--
-- BeamNG does NOT auto-load extensions found in lua/ge/extensions. A mod's
-- extensions only get executed if something asks for them: the official docs
-- state "An extension you create won't be loaded until you write explicit code
-- for it to be loaded."
--
-- The mod manager (core_modmanager) scans /scripts/ for every modScript.lua
-- while initialising, runs it before any extension loads, and treats
-- setExtensionUnloadMode registrations as "keep this alive across level
-- changes". loadManualUnloadExtensions() is what actually triggers the load;
-- without that call nothing happens.
--
-- The extension name must match the file path exactly:
--   lua/ge/extensions/SendspinRadio.lua -> SendspinRadio
--
-- Do NOT move setExtensionUnloadMode into the extension itself. It belongs here.

setExtensionUnloadMode("SendspinRadio", "manual")
loadManualUnloadExtensions()
