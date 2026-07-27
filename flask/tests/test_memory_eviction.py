import time
from unittest.mock import MagicMock, patch

import pytest
from providers.registry import (
    ProviderRegistry,
    _shared_models,
    _shared_models_lock,
    SharedModelRef,
)

@pytest.fixture(autouse=True)
def clear_shared_models():
    """Ensure a clean registry state for every test."""
    with _shared_models_lock:
        _shared_models.clear()
    yield
    with _shared_models_lock:
        _shared_models.clear()


def run_eviction_cycle(registry, mock_now):
    def fake_sleep(seconds):
        fake_sleep.calls += 1
        if fake_sleep.calls > 1:
            raise StopIteration("Stop loop")
    fake_sleep.calls = 0
    
    with patch('time.sleep', fake_sleep), patch('time.time', return_value=mock_now):
        try:
            registry._eviction_loop()
        except StopIteration:
            pass


def test_grace_period_boundary():
    registry = ProviderRegistry()
    mock_instance = MagicMock()
    
    now = time.time()
    with _shared_models_lock:
        ref = SharedModelRef(instance=mock_instance)
        ref.last_used = now - 30 # 30 seconds ago
        _shared_models[("dummy", ())] = ref
        
    run_eviction_cycle(registry, mock_now=now)
    
    # 30 seconds is under the 60 second grace period, so it should not be evicted
    assert ("dummy", ()) in _shared_models
    assert not mock_instance.unload_model.called


def test_ttl_eviction():
    registry = ProviderRegistry()
    mock_instance = MagicMock()
    
    now = time.time()
    with _shared_models_lock:
        ref = SharedModelRef(instance=mock_instance)
        ref.last_used = now - 3601 # over 1 hour ago
        _shared_models[("dummy", ())] = ref
        
    run_eviction_cycle(registry, mock_now=now)
    
    # Should be evicted due to TTL
    assert ("dummy", ()) not in _shared_models
    assert mock_instance.unload_model.called


@patch('providers.registry.MAX_IDLE_MEMORY_MB', 4000)
@patch('providers.registry._estimate_model_size', return_value=3000)
def test_budget_threshold_crossing_and_lru_ordering(mock_size):
    registry = ProviderRegistry()
    mock_old = MagicMock()
    mock_new = MagicMock()
    
    now = time.time()
    with _shared_models_lock:
        # Both are past grace period, but not past TTL
        ref_old = SharedModelRef(instance=mock_old)
        ref_old.last_used = now - 1000 
        _shared_models[("old_model", ())] = ref_old
        
        ref_new = SharedModelRef(instance=mock_new)
        ref_new.last_used = now - 100 
        _shared_models[("new_model", ())] = ref_new
        
    # Total idle memory = 3000 + 3000 = 6000 > 4000 budget
    # The oldest (old_model) should be evicted.
    run_eviction_cycle(registry, mock_now=now)
    
    assert ("old_model", ()) not in _shared_models
    assert mock_old.unload_model.called
    
    assert ("new_model", ()) in _shared_models
    assert not mock_new.unload_model.called


@patch('providers.registry.MAX_IDLE_MEMORY_MB', 4000)
@patch('providers.registry._estimate_model_size', return_value=3000)
def test_hot_tier_exemption_under_pressure(mock_size):
    registry = ProviderRegistry()
    mock_hot = MagicMock()
    mock_idle = MagicMock()
    
    now = time.time()
    with _shared_models_lock:
        ref_hot = SharedModelRef(instance=mock_hot)
        ref_hot.last_used = now - 2000 # very old
        ref_hot.is_hot_tier = True
        _shared_models[("hot_model", ())] = ref_hot
        
        ref_idle = SharedModelRef(instance=mock_idle)
        ref_idle.last_used = now - 100 # newer, but not hot tier
        _shared_models[("idle_model", ())] = ref_idle
        
    mock_idle2 = MagicMock()
    with _shared_models_lock:
        ref_idle2 = SharedModelRef(instance=mock_idle2)
        ref_idle2.last_used = now - 150 # older than idle 1
        _shared_models[("idle_model2", ())] = ref_idle2

    # Now we have hot (3000), idle1 (3000, 100s), idle2 (3000, 150s).
    # Budget is 4000. total_idle_mb = 6000.
    # Hot tier should NEVER be evicted even though it's the oldest (2000s).
    
    run_eviction_cycle(registry, mock_now=now)
    
    assert ("hot_model", ()) in _shared_models
    assert not mock_hot.unload_model.called
    
    assert ("idle_model", ()) in _shared_models
    assert not mock_idle.unload_model.called
    
    assert ("idle_model2", ()) not in _shared_models
    assert mock_idle2.unload_model.called
