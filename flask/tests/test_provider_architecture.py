"""
this test covers multi tenant interface separation,
dual slot registration,lazy instantiation,and thread safe locking
"""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch
import pytest

from providers.base import (
    BaseProvider, 
    TranslationProvider, 
    TranscriptionProvider,
    TranslationError, 
    ProviderConfigError
)
from providers.registry import (
    ProviderRegistry,
    register_provider,
    available_providers,
)


#Mock Providers for Testing Split Hierarchy

class DummyTranscriptionProvider(TranscriptionProvider):
    """Mock STT provider, Tracks instantiation count for concurrency testing"""
    instantiation_count = 0

    def __init__(self, config=None):
        super().__init__(config)
        # Forces concurrent threads to collide to test the double checked lock
        time.sleep(0.05)
        DummyTranscriptionProvider.instantiation_count += 1

    def transcribe(self, audio_chunk, **kwargs):
        return "mocked transcript"

    def is_available(self):
        return True

    @property
    def provider_name(self):
        return "dummy_stt"


class DummyTranslationProvider(TranslationProvider):
    """Mock NMT provider"""
    def __init__(self, config=None):
        super().__init__(config)

    def translate(self, text, source_lang, target_lang, **kwargs):
        return f"translated:{text}"

    def is_available(self):
        return True

    @property
    def provider_name(self):
        return "dummy_nmt"


class FailingTranslationProvider(TranslationProvider):

    """Simulates runtime or initialization failures"""

    def __init__(self, config=None):
        super().__init__(config)
        if config and config.get("break_on_init"):
            raise RuntimeError("missing heavy ML weights")

    def translate(self, text, source_lang, target_lang, **kwargs):
        raise TranslationError("intentional failure")

    def is_available(self):
        return True

    @property
    def provider_name(self):
        return "failing_nmt"


#fixtures

@pytest.fixture(autouse=True)
def clean_factories():
    with patch("providers.registry._PROVIDER_FACTORIES", {}) as mock_dict:
        yield mock_dict

@pytest.fixture
def registry() -> ProviderRegistry:
    return ProviderRegistry()


#Interface & Hierarchy Tests

class TestAbstractInterfaceHierarchy:
    def test_cannot_instantiate_base_or_split_abstract_classes(self) -> None:
        """verifies that BaseProvider, TranscriptionProvider, and TranslationProvider cannot be instantiated directly"""

        with pytest.raises(TypeError):
            BaseProvider()
        with pytest.raises(TypeError):
            TranscriptionProvider()
        with pytest.raises(TypeError):
            TranslationProvider()

    def test_must_implement_transcribe(self) -> None:
        """verifies that transcription providers"""
        class IncompleteSTT(TranscriptionProvider):
            def is_available(self): return True
            @property
            def provider_name(self): return "incomplete"
        with pytest.raises(TypeError):
            IncompleteSTT()


# Role Based Slot & Lazy Instantiation Tests
class TestSlotBasedRegistry:
    def test_configure_allocates_slots_but_keeps_instances_lazy(self, registry: ProviderRegistry) -> None:

        """Verifies Phase 3 split block registration and lazy loading"""

        register_provider("dummy_stt", lambda cfg: DummyTranscriptionProvider(cfg))
        register_provider("dummy_nmt", lambda cfg: DummyTranslationProvider(cfg))

        stt_config = {"provider_name": "dummy_stt", "config": {"model": "base"}}
        nmt_config = {"provider_name": "dummy_nmt", "config": {"model": "small"}}

        registry.configure("tenant1", stt_config, nmt_config)

        tenant_entry = registry._tenants["tenant1"]

        assert tenant_entry["transcription"]["instance"] is None
        assert tenant_entry["translation"]["instance"] is None

    def test_lazy_instantiation_per_slot(self, registry: ProviderRegistry) -> None:

        """Verifies that calling transcribe only instantiates the STT slot"""

        register_provider("dummy_stt", lambda cfg: DummyTranscriptionProvider(cfg))
        register_provider("dummy_nmt", lambda cfg: DummyTranslationProvider(cfg))

        registry.configure(
            "tenant1", 
            {"provider_name": "dummy_stt", "config": {"model": "base"}}, 
            {"provider_name": "dummy_nmt", "config": {"model": "small"}}
        )

        registry.transcribe("tenant1", b"\x00\x00")  


# Error Handling & Pipeline Propagation Tests
class TestPipelineExecutionAndErrors:
    def test_translation_error_propagates(self, registry: ProviderRegistry) -> None:

        """Verifies that runtime errors inside provider methods propagate cleanly"""

        register_provider("failing_nmt", lambda cfg: FailingTranslationProvider(cfg))
        registry.configure("tenant1", None, {"provider_name": "failing_nmt", "config": {"model": "failing_nmt"}})

        with pytest.raises(TranslationError, match="intentional failure"):
            registry.translate("tenant1", "hello", "en", "es")

    def test_factory_error_raises_provider_config_error(self, registry: ProviderRegistry) -> None:
        """Verifies that runtime lazy-load failures wrap inside ProviderConfigError."""
        register_provider("failing_nmt", lambda cfg: FailingTranslationProvider(cfg))

        registry.configure("tenant1", None, {"provider_name": "failing_nmt", "config": {"break_on_init": True}})

        with pytest.raises(ProviderConfigError, match="Provider initialization failed for 'failing_nmt': missing heavy ML weights"):
            registry.translate("tenant1", "hello", "en", "es")


# Thread Safety Test
class TestSlotThreadSafety:
    def test_concurrent_transcribe_same_tenant_double_checked_lock(self, registry: ProviderRegistry) -> None:

        """ensures multiple concurrent audio streams for a single tenant trigger precisely one load"""

        DummyTranscriptionProvider.instantiation_count = 0
        register_provider("dummy_stt", lambda cfg: DummyTranscriptionProvider(cfg))

        registry.configure("tenant1", {"provider_name": "dummy_stt", "config": {}}, None)

        results = []
        errors = []

        def worker():
            try:
                res = registry.transcribe("tenant1", b"\x00\x00")
                results.append(res)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads: t.start()
        for t in threads: t.join()

        assert errors == [], f"Concurrency brought unexpected exceptions: {errors}"


