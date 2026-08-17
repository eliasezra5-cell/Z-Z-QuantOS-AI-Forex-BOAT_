"""Provider framework mirroring the Node foundation providerFramework.js."""
from .event_bus import event_bus
from .logger import logger


class ProviderFramework:
    def __init__(self):
        self.providers = {}
        self.registrations = []

    def register(self, provider):
        if not provider.get("id"):
            raise ValueError("Provider requires id")
        self.providers[provider["id"]] = {**provider, "enabled": provider.get("enabled", True) is not False}
        self.registrations.append({"id": provider["id"], "category": provider.get("category"), "name": provider.get("name"), "at": __import__("time").time()})
        event_bus.emit("quantos:provider:registered", {"providerId": provider["id"]})
        logger.info(f"Provider registered: {provider['id']} ({provider.get('category')})")
        return provider

    def get(self, provider_id):
        return self.providers.get(provider_id)

    def list(self, category=None):
        all_providers = list(self.providers.values())
        if category:
            return [p for p in all_providers if p.get("category") == category]
        return all_providers

    def call(self, provider_id, method, *args):
        p = self.providers.get(provider_id)
        if not p:
            raise ValueError(f"Provider {provider_id} not registered")
        if not p["enabled"]:
            raise ValueError(f"Provider {provider_id} is disabled")
        fn = p.get(method)
        if not callable(fn):
            raise ValueError(f"Provider {provider_id} has no method {method}")
        return fn(*args)


providers = ProviderFramework()


def init_providers():
    logger.info("AI Provider Framework initialized")
    return providers
