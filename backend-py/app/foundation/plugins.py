"""Plugin system mirroring the Node foundation plugins.js."""
from .event_bus import event_bus
from .logger import logger


class PluginSystem:
    def __init__(self):
        self.plugins = {}
        self.hooks = {}

    def install(self, plugin):
        if not plugin.get("id"):
            raise ValueError("Plugin requires id")
        if plugin["id"] in self.plugins:
            raise ValueError(f"Plugin {plugin['id']} already installed")
        self.plugins[plugin["id"]] = {**plugin, "installedAt": int(__import__("time").time() * 1000)}
        init_fn = plugin.get("init")
        if init_fn:
            try:
                init_fn(self)
            except Exception as e:  # noqa: BLE001
                logger.error(f"Plugin {plugin['id']} init failed", {"error": str(e)})
        event_bus.emit("quantos:plugin:installed", {"pluginId": plugin["id"]})
        logger.info(f"Plugin installed: {plugin['id']} v{plugin.get('version', '1.0.0')}")
        return plugin

    def register_hook(self, name, plugin_id, handler):
        self.hooks.setdefault(name, []).append({"pluginId": plugin_id, "handler": handler})

    def run_hook(self, name, payload=None):
        import asyncio
        payload = payload or {}
        results = []
        for h in self.hooks.get(name, []):
            try:
                result = h["handler"](payload, self)
                if asyncio.iscoroutine(result):
                    result = asyncio.run(result)
                results.append({"pluginId": h["pluginId"], "result": result})
            except Exception as e:  # noqa: BLE001
                logger.error(f"Hook {name} failed for plugin {h['pluginId']}", {"error": str(e)})
        return results

    def list(self):
        return [{"id": p["id"], "version": p.get("version"), "installedAt": p["installedAt"]} for p in self.plugins.values()]


plugins = PluginSystem()


def init_plugins():
    logger.info("Plugin system initialized")
    return plugins
