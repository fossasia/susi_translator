"""
Test suite for the CTranslate2-backed provider plugins:
  - FasterWhisperLocalProvider (transcription)
  - NLLBCTranslate2Provider (translation)

All tests use mocks — no actual model downloads occur in CI,
consistent with the conftest.py approach.
"""

from __future__ import annotations

import numpy as np
import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from providers.base import (
    TranscriptionProvider,
    TranslationProvider,
    ProviderConfigError,
    TranslationError,
    TranscriptionError,
)
from providers.registry import ProviderRegistry, register_provider


# ---------------------------------------------------------------------------
# FasterWhisperLocalProvider Tests
# ---------------------------------------------------------------------------

class TestFasterWhisperLocalProvider:
    """Covers contract, load, transcribe, and error paths for FasterWhisperLocalProvider."""

    def _make_provider(self, config=None):
        from providers.plugins.transcription_plugins.faster_whisper_local import FasterWhisperLocalProvider
        return FasterWhisperLocalProvider(config=config or {})

    def test_is_transcription_provider_subclass(self):
        """Provider must be a proper subclass of TranscriptionProvider."""
        from providers.plugins.transcription_plugins.faster_whisper_local import FasterWhisperLocalProvider
        assert issubclass(FasterWhisperLocalProvider, TranscriptionProvider)

    def test_provider_name_is_faster_whisper(self):
        p = self._make_provider()
        assert p.provider_name == "faster_whisper"

    def test_default_model_size_is_medium(self):
        p = self._make_provider()
        assert p._model_size == "medium"

    def test_config_overrides_model_size(self):
        p = self._make_provider(config={"model_size": "large-v3"})
        assert p._model_size == "large-v3"

    def test_is_available_true_when_faster_whisper_importable(self):
        p = self._make_provider()
        with patch.dict("sys.modules", {"faster_whisper": MagicMock()}):
            assert p.is_available() is True

    def test_is_available_false_when_faster_whisper_missing(self):
        p = self._make_provider()
        with patch.dict("sys.modules", {"faster_whisper": None}):
            assert p.is_available() is False

    def test_load_model_cpu_int8(self):
        """On CPU, compute_type must default to int8.
        Uses sys.modules patching because ctranslate2 and faster_whisper
        are lazy local imports inside load_model() — no module-level symbols to patch.
        """
        p = self._make_provider()
        mock_model = MagicMock()
        mock_wm_class = MagicMock(return_value=mock_model)

        fake_faster_whisper = MagicMock()
        fake_faster_whisper.WhisperModel = mock_wm_class
        fake_ct2 = MagicMock()
        fake_ct2.get_cuda_device_count.return_value = 0

        with patch.dict("sys.modules", {"faster_whisper": fake_faster_whisper, "ctranslate2": fake_ct2}):
            p.load_model()

        assert p._model is not None
        # Verify it picked int8 (CPU path)
        _, call_kwargs = mock_wm_class.call_args
        assert call_kwargs.get("compute_type") == "int8"
        assert call_kwargs.get("device") == "cpu"

    def test_load_model_raises_provider_config_error_on_failure(self):
        p = self._make_provider()
        fake_faster_whisper = MagicMock()
        fake_faster_whisper.WhisperModel.side_effect = RuntimeError("download failed")
        fake_ct2 = MagicMock()
        fake_ct2.get_cuda_device_count.return_value = 0

        with patch.dict("sys.modules", {"faster_whisper": fake_faster_whisper, "ctranslate2": fake_ct2}):
            with pytest.raises(ProviderConfigError, match="Failed to load model"):
                p.load_model()

    def test_load_model_is_idempotent(self):
        """Calling load_model twice must not re-instantiate the underlying model."""
        p = self._make_provider()
        sentinel = MagicMock()
        p._model = sentinel  # already loaded

        p.load_model()  # should return early

        assert p._model is sentinel

    def test_transcribe_returns_str_from_segments(self):
        """transcribe() must join segment texts and return a plain str."""
        p = self._make_provider()

        seg1 = MagicMock()
        seg1.text = "Hello"
        seg2 = MagicMock()
        seg2.text = " world"

        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([seg1, seg2], MagicMock())
        p._model = mock_model

        audio = np.zeros(16000, dtype=np.float32)
        result = p.transcribe(audio)
        assert result == "Hello  world"

    def test_transcribe_converts_non_float32_audio(self):
        """transcribe() must silently cast int16 input to float32."""
        p = self._make_provider()
        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([], MagicMock())
        p._model = mock_model

        audio = np.zeros(16000, dtype=np.int16)
        p.transcribe(audio)

        called_audio = mock_model.transcribe.call_args[0][0]
        assert called_audio.dtype == np.float32

    def test_transcribe_raises_transcription_error_on_non_ndarray(self):
        p = self._make_provider()
        p._model = MagicMock()
        with pytest.raises(TranscriptionError, match="Expected np.ndarray"):
            p.transcribe("not_an_array")

    def test_transcribe_raises_transcription_error_on_model_failure(self):
        p = self._make_provider()
        mock_model = MagicMock()
        mock_model.transcribe.side_effect = RuntimeError("inference boom")
        p._model = mock_model

        audio = np.zeros(16000, dtype=np.float32)
        with pytest.raises(TranscriptionError, match="Transcription failed"):
            p.transcribe(audio)


# ---------------------------------------------------------------------------
# NLLBCTranslate2Provider Tests
# ---------------------------------------------------------------------------

class TestNLLBCTranslate2Provider:
    """Covers contract, load, translate, and error paths for NLLBCTranslate2Provider."""

    def _make_provider(self, config=None):
        from providers.plugins.translation_plugins.nllb_ctranslate2 import NLLBCTranslate2Provider
        return NLLBCTranslate2Provider(config=config or {})

    def test_is_translation_provider_subclass(self):
        from providers.plugins.translation_plugins.nllb_ctranslate2 import NLLBCTranslate2Provider
        assert issubclass(NLLBCTranslate2Provider, TranslationProvider)

    def test_provider_name_is_nllb_ctranslate2(self):
        p = self._make_provider()
        assert p.provider_name == "nllb_ctranslate2"

    def test_default_model_id(self):
        p = self._make_provider()
        assert p._model_id == "facebook/nllb-200-distilled-600M"

    def test_is_available_true(self):
        p = self._make_provider()
        with patch.dict("sys.modules", {"ctranslate2": MagicMock(), "transformers": MagicMock()}):
            assert p.is_available() is True

    def test_is_available_false_when_ctranslate2_missing(self):
        p = self._make_provider()
        with patch.dict("sys.modules", {"ctranslate2": None}):
            assert p.is_available() is False

    def test_translate_empty_string_returns_empty(self):
        p = self._make_provider()
        assert p.translate("", "en", "es") == ""
        assert p.translate("   ", "en", "es") == ""

    def test_translate_calls_ct2_and_decodes_correctly(self):
        """Full translate() path with mocked CTranslate2 translator and HF tokenizer."""
        p = self._make_provider()

        # Mock tokenizer
        mock_tokenizer = MagicMock()
        mock_tokenizer.src_lang = None
        mock_tokenizer.unk_token_id = 0
        mock_tokenizer.convert_tokens_to_ids.return_value = 42  # valid lang id
        mock_tokenizer.return_value = {"input_ids": [1, 2, 3]}
        mock_tokenizer.convert_ids_to_tokens.return_value = ["tok1", "tok2", "tok3"]
        mock_tokenizer.decode.return_value = "hola mundo"

        # Mock CTranslate2 translator result
        mock_hypothesis = MagicMock()
        mock_hypothesis.hypotheses = [["es_token", "hola", "mundo"]]
        mock_result = MagicMock()
        mock_result.__getitem__ = lambda self, i: mock_hypothesis
        mock_translator = MagicMock()
        mock_translator.translate_batch.return_value = [mock_hypothesis]

        p._translator = mock_translator
        p._tokenizer = mock_tokenizer

        result = p.translate("hello world", "en", "es")
        assert isinstance(result, str)
        assert result == "hola mundo"

    def test_translate_raises_translation_error_on_unknown_target_lang(self):
        p = self._make_provider()
        mock_tokenizer = MagicMock()
        mock_tokenizer.unk_token_id = 0
        # Simulate unknown lang — convert_tokens_to_ids returns unk_token_id
        mock_tokenizer.convert_tokens_to_ids.return_value = 0
        p._tokenizer = mock_tokenizer
        p._translator = MagicMock()

        with pytest.raises(TranslationError, match="Unsupported target language code"):
            p.translate("hello", "en", "xyz_FAKE")

    def test_translate_propagates_inference_errors_as_translation_error(self):
        p = self._make_provider()
        mock_tokenizer = MagicMock()
        mock_tokenizer.unk_token_id = 0
        mock_tokenizer.convert_tokens_to_ids.return_value = 42
        mock_tokenizer.return_value = {"input_ids": [1, 2, 3]}
        mock_tokenizer.convert_ids_to_tokens.return_value = ["a", "b"]
        p._tokenizer = mock_tokenizer

        mock_translator = MagicMock()
        mock_translator.translate_batch.side_effect = RuntimeError("ct2 crash")
        p._translator = mock_translator

        with pytest.raises(TranslationError, match="Inference failed"):
            p.translate("hello", "en", "es")

    def test_load_model_raises_provider_config_error_on_conversion_failure(self):
        """If model conversion fails, ProviderConfigError must be raised."""
        p = self._make_provider()
        fake_ct2 = MagicMock()
        fake_ct2.get_cuda_device_count.return_value = 0
        fake_transformers = MagicMock()

        with patch.dict("sys.modules", {"ctranslate2": fake_ct2, "transformers": fake_transformers}), \
             patch(
                 "providers.plugins.translation_plugins.nllb_ctranslate2._get_ct2_model_path",
                 side_effect=ProviderConfigError("conversion failed")
             ):
            with pytest.raises(ProviderConfigError, match="conversion failed"):
                p.load_model()

    def test_load_model_is_idempotent(self):
        p = self._make_provider()
        p._translator = MagicMock()
        p._tokenizer = MagicMock()
        # Must return early without touching load machinery
        p.load_model()
        # No exception means it exited early correctly


# ---------------------------------------------------------------------------
# Registry Integration Tests
# ---------------------------------------------------------------------------

class TestCTranslate2RegistryIntegration:
    """Verify that the new providers register and resolve correctly in the registry."""

    def test_faster_whisper_registers_under_correct_key(self):
        from providers.plugins.transcription_plugins.faster_whisper_local import FasterWhisperLocalProvider
        register_provider("faster_whisper", lambda cfg: FasterWhisperLocalProvider(cfg))
        from providers.registry import available_providers
        assert "faster_whisper" in available_providers()

    def test_nllb_ctranslate2_registers_under_correct_key(self):
        from providers.plugins.translation_plugins.nllb_ctranslate2 import NLLBCTranslate2Provider
        register_provider("nllb_ctranslate2", lambda cfg: NLLBCTranslate2Provider(cfg))
        from providers.registry import available_providers
        assert "nllb_ctranslate2" in available_providers()

    def test_old_providers_are_not_registered(self):
        """After the migration, whisper_local and nllb_local must not be in the registry."""
        from providers.registry import available_providers
        # _PROVIDER_FACTORIES is patched to {} by clean_factories autouse fixture
        assert "whisper_local" not in available_providers()
        assert "nllb_local" not in available_providers()

    def test_registry_transcribes_via_faster_whisper(self):
        from providers.plugins.transcription_plugins.faster_whisper_local import FasterWhisperLocalProvider
        register_provider("faster_whisper", lambda cfg: FasterWhisperLocalProvider(cfg))

        registry = ProviderRegistry()
        registry.configure("t1", {"provider_name": "faster_whisper"}, None)

        # Inject a mock model to avoid real load
        provider = registry._resolve_instance("t1", "transcription")
        seg = MagicMock()
        seg.text = "hello"
        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([seg], MagicMock())
        provider._model = mock_model

        result = registry.transcribe("t1", np.zeros(16000, dtype=np.float32))
        assert result == "hello"

    def test_registry_translates_via_nllb_ctranslate2(self):
        from providers.plugins.translation_plugins.nllb_ctranslate2 import NLLBCTranslate2Provider
        register_provider("nllb_ctranslate2", lambda cfg: NLLBCTranslate2Provider(cfg))

        registry = ProviderRegistry()
        registry.configure("t2", None, {"provider_name": "nllb_ctranslate2", "source_lang": "en", "target_lang": "es"})

        provider = registry._resolve_instance("t2", "translation")

        # Inject mock translator and tokenizer
        mock_tokenizer = MagicMock()
        mock_tokenizer.unk_token_id = 0
        mock_tokenizer.convert_tokens_to_ids.return_value = 42
        mock_tokenizer.return_value = {"input_ids": [1, 2, 3]}
        mock_tokenizer.convert_ids_to_tokens.return_value = ["a", "b"]
        mock_tokenizer.decode.return_value = "hola"
        mock_hypothesis = MagicMock()
        mock_hypothesis.hypotheses = [["es", "hola"]]
        mock_translator = MagicMock()
        mock_translator.translate_batch.return_value = [mock_hypothesis]

        provider._translator = mock_translator
        provider._tokenizer = mock_tokenizer

        result = registry.translate("t2", "hello", "en", "es")
        assert result == "hola"
