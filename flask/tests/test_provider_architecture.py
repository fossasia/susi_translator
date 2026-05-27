"""
Tests covers the translation provider architecture, ensuring that the 
abstract interface is correctly defined and that the provider registry 
behaves as expected
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

# Minimal concrete providers for testing 

class EchoProvider(TranslationProvider):
    """Returns the input text unchanged. Tracks instantiation count."""

    instantiation_count = 0

    def __init__(self, config=None):
        super().__init__(config)
        # enforces threads to collide in the concurrency test
        # to guarantee the double-checked lock is actually tested
        time.sleep(0.05) 
        EchoProvider.instantiation_count += 1

    def translate(self, text, source_lang, target_lang, **kwargs):
        return text

    def is_available(self):
        return True

    @property
    def provider_name(self):
        return "echo"

class UnavailableProvider(TranslationProvider):
    """Always reports itself as unavailable."""
    def __init__(self, config=None):
        super().__init__(config)

    def translate(self, text, source_lang, target_lang, **kwargs):
        raise TranslationError("This provider is unavailable")

    def is_available(self):
        return False

    @property
    def provider_name(self):
        return "unavailable"

class FailingProvider(TranslationProvider):
    """Raises TranslationError on every translate() call."""
    def __init__(self, config=None):
        super().__init__(config)

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



#Fixtures

@pytest.fixture(autouse=True)
def clean_factories():
    with patch("providers.registry._PROVIDER_FACTORIES", {}) as mock_dict:
        yield mock_dict

@pytest.fixture
def registry() -> ProviderRegistry:
    return ProviderRegistry()


#Abstract interface tests
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



#Registration tests
class TestProviderRegistration:
    def test_register_and_list(self) -> None:
        register_provider("echo", lambda config: EchoProvider(config))
        assert "echo" in available_providers()



#Registry configuration tests
class TestRegistryConfigure:
    def test_configure_passes_config_to_provider(self, registry: ProviderRegistry) -> None:
        register_provider("config_capturing", lambda config: ConfigCapturingProvider(config))
        registry.configure("tenant1", "config_capturing", api_key="secret-key")
        
        registry.translate("tenant1", "hello", "en", "de")
        instance = registry._tenants["tenant1"]["instance"]
        assert instance.received_config["api_key"] == "secret-key"


#Lazy instantiation tests

class TestLazyInstantiation:
    def test_provider_created_on_first_translate(self, registry: ProviderRegistry) -> None:
        register_provider("echo", lambda config: EchoProvider(config))
        registry.configure("tenant1", "echo")
        
        # Instance should be None before translation
        assert registry._tenants["tenant1"]["instance"] is None
        
        registry.translate("tenant1", "hello", "en", "de")
        
        # Instance should exist after translation
        assert registry._tenants["tenant1"]["instance"] is not None



# Translation tests
class TestTranslate:
    def test_translate_forwards_kwargs(self, registry: ProviderRegistry) -> None:
        """Ensures kwargs like 'temperature' and 'formality' are passed to the provider"""
        register_provider(
            "kwargs_capturing", 
            lambda config: KwargsCapturingProvider(config)
        )
        registry.configure("tenant1", "kwargs_capturing")
        
        registry.translate(
            "tenant1", 
            "hello", 
            "en", 
            "de", 
            temperature=0.3, 
            formality="informal"
        )
        
        instance = registry._tenants["tenant1"]["instance"]
        assert instance.last_kwargs == {"temperature": 0.3, "formality": "informal"}

    def test_translation_error_propagates(self, registry: ProviderRegistry) -> None:
        """Ensure runtime TranslationErrors from the provider are properly propagated."""
        register_provider("failing", lambda config: FailingProvider(config))
        registry.configure("tenant1", "failing")
        
        # The provider is designed to fail when translate is called
        with pytest.raises(TranslationError, match="intentional failure"):
            registry.translate("tenant1", "hello", "en", "de")

    def test_factory_error_raises_provider_config_error(self, registry: ProviderRegistry) -> None:
        """Ensure errors during lazy initialization are caught and wrapped correctly."""
        def bad_factory(config):
            raise RuntimeError("missing heavy ML weights")

        register_provider("broken", bad_factory)
        registry.configure("tenant1", "broken")
        
        # The initialization happens lazily during the first translate call.
        # It should catch the RuntimeError and wrap it in a ProviderConfigError.
        with pytest.raises(ProviderConfigError, match="Provider initialization failed"):
            registry.translate("tenant1", "hello", "en", "de")


# Translation & Multi-tenant tests

class TestMultiTenantIsolation:
    def test_tenant_config_is_isolated(self, registry: ProviderRegistry) -> None:
        register_provider("config_capturing", lambda config: ConfigCapturingProvider(config))
        
        registry.configure("tenant_a", "config_capturing", api_key="key-a")
        registry.configure("tenant_b", "config_capturing", api_key="key-b")

        registry.translate("tenant_a", "x", "en", "de")
        registry.translate("tenant_b", "x", "en", "de")

        instance_a = registry._tenants["tenant_a"]["instance"]
        instance_b = registry._tenants["tenant_b"]["instance"]

        assert instance_a.received_config["api_key"] == "key-a"
        assert instance_b.received_config["api_key"] == "key-b"
        assert instance_a is not instance_b



# Thread safety test
class TestThreadSafety:
    def test_concurrent_translate_same_tenant(self, registry: ProviderRegistry) -> None:
        """Multiple threads translating for the same tenant must not bypass the lock."""
        EchoProvider.instantiation_count = 0
        register_provider("echo", lambda config: EchoProvider(config))
        registry.configure("tenant1", "echo")

        results = []
        errors = []

        def worker():
            try:
                # Due to the time.sleep in EchoProvider, all 20 threads will 
                # smash into the lock simultaneously here.
                result = registry.translate("tenant1", "hello", "en", "de")
                results.append(result)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Unexpected errors: {errors}"
        assert all(r == "hello" for r in results)
        
        # PROOF: Even with 20 threads colliding, the model was only loaded into RAM exactly once.
        assert EchoProvider.instantiation_count == 1