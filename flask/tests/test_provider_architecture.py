"""
Tests covering the base translation provider architecture and 
basic registry functionality for susi_translator.
"""

from __future__ import annotations
import pytest

from providers.base import TranslationProvider, TranslationError
from providers.registry import ProviderRegistry

#concrete providers
class EchoProvider(TranslationProvider):
    """Returns the input text unchanged."""
    def translate(self, text, source_lang, target_lang, **kwargs):
        return text

    def is_available(self):
        return True

    @property
    def provider_name(self):
        return "echo"

class UnavailableProvider(TranslationProvider):
    """Always reports itself as unavailable."""
    def translate(self, text, source_lang, target_lang, **kwargs):
        raise TranslationError("This provider is unavailable")

    def is_available(self):
        return False

    @property
    def provider_name(self):
        return "unavailable"

class KwargsCapturingProvider(TranslationProvider):
    """Stores the kwargs passed to translate() so tests can assert on them."""
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


#Abstract interfaces

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


#Registry Tests

class TestBasicRegistry:
    def test_register_and_retrieve(self):
        registry = ProviderRegistry()
        provider = EchoProvider()
        
        registry.register(provider)
        retrieved = registry.get_provider("echo")
        
        assert retrieved is provider

    def test_unregistered_provider_raises_error(self):
        registry = ProviderRegistry()
        with pytest.raises(ValueError, match="is not registered"):
            registry.get_provider("missing")

    def test_translate_routes_correctly(self):
        registry = ProviderRegistry()
        registry.register(EchoProvider())
        
        result = registry.translate("echo", "hello", "en", "es")
        assert result == "hello"

    def test_translate_checks_availability(self):
        registry = ProviderRegistry()
        registry.register(UnavailableProvider())
        
        # It should check `is_available()` and throw an error before trying to translate
        with pytest.raises(RuntimeError, match="currently unavailable"):
            registry.translate("unavailable", "hello", "en", "es")

    def test_translate_forwards_kwargs(self):
        registry = ProviderRegistry()
        provider = KwargsCapturingProvider()
        registry.register(provider)
        
        registry.translate("kwargs_capturing", "hello", "en", "es", temperature=0.7)
        assert provider.last_kwargs == {"temperature": 0.7}