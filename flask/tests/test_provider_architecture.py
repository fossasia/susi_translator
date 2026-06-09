"""
tests covering the translation provider architecture, 
ensuring the abstract interface, tenant isolation, and double-checked locking behave as expected
"""

from __future__ import annotations

import threading
import time
from unittest.mock import patch
import pytest

from providers.base import TranslationProvider, TranslationError, ProviderConfigError
from providers.registry import (
    ProviderRegistry,
    register_provider,
    available_providers,
)

#providers used in test
class EchoProvider(TranslationProvider):
    """Returns the input text unchanged. Tracks instantiation count."""
    instantiation_count = 0

    def __init__(self, config=None):
        super().__init__(config)
        time.sleep(0.05) 
        EchoProvider.instantiation_count += 1

    def translate(self, text, source_lang, target_lang, **kwargs):
        return text

    def is_available(self):
        return True

    @property
    def provider_name(self):
        return "echo"

class FailingProvider(TranslationProvider):
    """Raises TranslationError on every translate() call."""
    def translate(self, text, source_lang, target_lang, **kwargs):
        raise TranslationError("intentional failure")

    def is_available(self):
        return True

    @property
    def provider_name(self):
        return "failing"

class ConfigCapturingProvider(TranslationProvider):
    """Stores the config it receives so tests can assert on it."""
    def __init__(self, config=None):
        super().__init__(config)
        self.received_config = dict(self.config)

    def translate(self, text, source_lang, target_lang, **kwargs):
        return f"translated:{text}"

    def is_available(self):
        return True

    @property
    def provider_name(self):
        return "config_capturing"
    
class KwargsCapturingProvider(TranslationProvider):
    """Stores the kwargs passed to translate() so tests can assert on them"""
    def __init__(self, config=None):
        super().__init__(config)
        self.last_kwargs = {}

    def translate(self, text, source_lang, target_lang, **kwargs):
        self.last_kwargs = kwargs
        return f"translated:{text}"

    def is_available(self):
        return True

    @property
    def provider_name(self):
        return "kwargs_capturing"


# --- Fixtures ---
@pytest.fixture(autouse=True)
def clean_factories():
    with patch("providers.registry._PROVIDER_FACTORIES", {}) as mock_dict:
        yield mock_dict

@pytest.fixture
def registry() -> ProviderRegistry:
    return ProviderRegistry()


# --- Tests ---
class TestAbstractInterface:
    def test_cannot_instantiate_abstract_class(self) -> None:
        with pytest.raises(TypeError):
            TranslationProvider()

    def test_must_implement_translate(self) -> None:
        class Incomplete(TranslationProvider):
            def is_available(self): return True
            @property
            def provider_name(self): return "incomplete"

        with pytest.raises(TypeError):
            Incomplete()

    def test_config_stored_as_copy(self) -> None:
        config = {"api_key": "secret"}
        provider = EchoProvider(config=config)
        config["api_key"] = "mutated"
        assert provider.config["api_key"] == "secret"


class TestProviderRegistration:
    def test_register_and_list(self) -> None:
        register_provider("echo", lambda config: EchoProvider(config))
        assert "echo" in available_providers()
class TestRegistryConfigure:
    def test_configure_passes_config_to_provider(self, registry: ProviderRegistry) -> None:
        register_provider("config_capturing", lambda config: ConfigCapturingProvider(config))
        # UPDATED: Added tenant_id
        registry.configure(tenant_id="test_room", provider_name="config_capturing", api_key="secret-key")
        
        registry.translate(tenant_id="test_room", provider_name="config_capturing", text="hello", source_lang="en", target_lang="de")
        
        # UPDATED: Replaced _providers with _tenants
        instance = registry._tenants["test_room"]["config_capturing"]["instance"]
        assert instance.received_config["api_key"] == "secret-key"


class TestLazyInstantiation:
    def test_provider_created_on_first_translate(self, registry: ProviderRegistry) -> None:
        register_provider("echo", lambda config: EchoProvider(config))
        registry.configure(tenant_id="test_room", provider_name="echo")
        
        # Instance should be None before translation
        assert registry._tenants["test_room"]["echo"]["instance"] is None
        
        registry.translate(tenant_id="test_room", provider_name="echo", text="hello", source_lang="en", target_lang="de")
        
        # Instance should exist after translation
        assert registry._tenants["test_room"]["echo"]["instance"] is not None


class TestTranslate:
    def test_translate_forwards_kwargs(self, registry: ProviderRegistry) -> None:
        register_provider("kwargs_capturing", lambda config: KwargsCapturingProvider(config))
        registry.configure(tenant_id="test_room", provider_name="kwargs_capturing")
        
        registry.translate(
            tenant_id="test_room",
            provider_name="kwargs_capturing", 
            text="hello", 
            source_lang="en", 
            target_lang="de", 
            temperature=0.3, 
            formality="informal"
        )
        
        instance = registry._tenants["test_room"]["kwargs_capturing"]["instance"]
        assert instance.last_kwargs == {"temperature": 0.3, "formality": "informal"}

    def test_translation_error_propagates(self, registry: ProviderRegistry) -> None:
        register_provider("failing", lambda config: FailingProvider(config))
        registry.configure(tenant_id="test_room", provider_name="failing")
        
        with pytest.raises(TranslationError, match="intentional failure"):
            registry.translate(tenant_id="test_room", provider_name="failing", text="hello", source_lang="en", target_lang="de")

    def test_factory_error_raises_provider_config_error(self, registry: ProviderRegistry) -> None:
        def bad_factory(config):
            raise RuntimeError("missing heavy ML weights")

        register_provider("broken", bad_factory)
        registry.configure(tenant_id="test_room", provider_name="broken")
        
        with pytest.raises(ProviderConfigError, match="Provider initialization failed"):
            registry.translate(tenant_id="test_room", provider_name="broken", text="hello", source_lang="en", target_lang="de")


class TestThreadSafety:
    def test_concurrent_translate_same_provider(self, registry: ProviderRegistry) -> None:
        EchoProvider.instantiation_count = 0
        register_provider("echo", lambda config: EchoProvider(config))
        registry.configure(tenant_id="test_room", provider_name="echo")

        results = []
        errors = []

        def worker():
            try:
                result = registry.translate(tenant_id="test_room", provider_name="echo", text="hello", source_lang="en", target_lang="de")
                results.append(result)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Unexpected errors: {errors}"
        assert len(results) == 20
        assert all(r == "hello" for r in results)
        assert EchoProvider.instantiation_count == 1

#tenant isolation test to ensure no data leakage 
class TestTenantIsolation:
    def test_tenant_isolation_prevents_data_leakage(self, registry: ProviderRegistry) -> None:
        """Prove that two tenants get completely isolated provider instances in memory."""
        register_provider("config_capturing", lambda config: ConfigCapturingProvider(config))
        
        tenant_a = "room_uuid_A"
        tenant_b = "room_uuid_B"

        #configure room A and room B with different API keys
        registry.configure(tenant_id=tenant_a, provider_name="config_capturing", api_key="KEY_FOR_A")
        registry.configure(tenant_id=tenant_b, provider_name="config_capturing", api_key="KEY_FOR_B")

        #Translate to force lazy instantiation for both tenants
        registry.translate(tenant_id=tenant_a, provider_name="config_capturing", text="test", source_lang="en", target_lang="es")
        registry.translate(tenant_id=tenant_b, provider_name="config_capturing", text="test", source_lang="en", target_lang="es")

        #Peek directly into the registry's nested memory
        config_a = registry._tenants[tenant_a]["config_capturing"]["config"]
        config_b = registry._tenants[tenant_b]["config_capturing"]["config"]

        instance_a = registry._tenants[tenant_a]["config_capturing"]["instance"]
        instance_b = registry._tenants[tenant_b]["config_capturing"]["instance"]
        assert instance_a is not None, "Tenant A provider was never instantiated!"
        assert instance_b is not None, "Tenant B provider was never instantiated!"
        assert instance_a is not instance_b, "Tenants share the same provider instance!"

        #Assert that the configurations remain perfectly isolated
        assert config_a["api_key"] == "KEY_FOR_A", "Tenant A lost its API key!"
        assert config_b["api_key"] == "KEY_FOR_B", "Tenant B lost its API key!"
        assert config_a["api_key"] != config_b["api_key"], "Tenants are sharing memory!"