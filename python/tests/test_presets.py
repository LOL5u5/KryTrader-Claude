from __future__ import annotations

from config import CRYPTO15M_PRESETS, crypto15m_preset_config


def test_crypto15m_presets_exist():
    ids = {p["id"] for p in CRYPTO15M_PRESETS}
    assert {"c15-favorite", "c15-contrarian"} <= ids


def test_contrarian_preset_sets_contrarian_mode():
    cfg = crypto15m_preset_config("c15-contrarian")
    assert cfg is not None
    assert cfg["crypto15m_direction_mode"] == "contrarian"
    assert cfg["crypto15m_exit_threshold"] == 0.0


def test_deep_favorite_preset_uses_95c_band():
    cfg = crypto15m_preset_config("c15-favorite")
    assert cfg["crypto15m_entry_threshold"] == 0.95
    assert cfg["crypto15m_entry_max"] == 0.98


def test_unknown_preset_is_none():
    assert crypto15m_preset_config("nope") is None


def test_data_tuned_preset_is_model_confirmed_and_survives_validation():
    from config import DEFAULT_CONFIG, _validate_config

    cfg = crypto15m_preset_config("c15-data-tuned")
    assert cfg is not None
    assert cfg["crypto15m_direction_mode"] == "model"
    assert cfg["crypto15m_model_midwindow"] is True
    assert cfg["crypto15m_model_final_minute"] is False
    assert cfg["crypto15m_entry_max"] == 0.97
    assert "crypto15m_enabled" not in cfg and "crypto15m_live" not in cfg
    assert set(cfg) <= set(DEFAULT_CONFIG)
    validated = _validate_config({**DEFAULT_CONFIG, **cfg})
    for k, v in cfg.items():
        assert validated[k] == v, k
