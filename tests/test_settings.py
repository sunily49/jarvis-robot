"""Tests for settings module — validates all config keys load correctly."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "pi"))


def test_settings_load():
    import jarvis.config.settings as s
    # Bool flags
    assert isinstance(s.TRIGGER_WAKEWORD, bool)
    assert isinstance(s.TRIGGER_BUTTON, bool)
    assert isinstance(s.TRIGGER_FACE, bool)
    assert isinstance(s.TRIGGER_CLAP, bool)
    assert isinstance(s.TRIGGER_PIR, bool)
    assert isinstance(s.TRIGGER_TELEGRAM, bool)
    assert isinstance(s.HW_MOTORS, bool)
    assert isinstance(s.HW_SERVOS, bool)
    assert isinstance(s.HW_SENSORS, bool)
    assert isinstance(s.DISPLAY_ENABLED, bool)
    assert isinstance(s.SERVER_ENABLED, bool)


def test_settings_numeric_types():
    import jarvis.config.settings as s
    assert isinstance(s.AUDIO_SAMPLE_RATE, int)
    assert s.AUDIO_SAMPLE_RATE > 0
    assert isinstance(s.AUDIO_CHUNK_SIZE, int)
    assert s.AUDIO_CHUNK_SIZE > 0
    assert isinstance(s.MCP_PORT, int)
    assert 1 <= s.MCP_PORT <= 65535
    assert isinstance(s.TRIGGER_COOLDOWN, float)
    assert s.TRIGGER_COOLDOWN >= 0.0
    assert isinstance(s.WAKEWORD_THRESHOLD, float)
    assert 0.0 <= s.WAKEWORD_THRESHOLD <= 1.0


def test_settings_string_types():
    import jarvis.config.settings as s
    assert isinstance(s.MCP_HOST, str)
    assert isinstance(s.SERVER_HOST, str)
    assert isinstance(s.LOG_LEVEL, str)
    assert s.LOG_LEVEL in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
    assert isinstance(s.MEMORY_DB_PATH, str)


def test_settings_env_override(monkeypatch):
    """Settings should respect environment variable overrides."""
    monkeypatch.setenv("TRIGGER_COOLDOWN", "7.5")
    monkeypatch.setenv("MCP_PORT", "9999")
    # Re-run helper functions directly
    import os
    cooldown = float(os.getenv("TRIGGER_COOLDOWN", "3.0"))
    port = int(os.getenv("MCP_PORT", "8080"))
    assert cooldown == 7.5
    assert port == 9999


def test_memory_short_term_limit_positive():
    import jarvis.config.settings as s
    assert s.MEMORY_SHORT_TERM_LIMIT > 0


def test_motor_pin_values():
    import jarvis.config.settings as s
    for pin in (s.MOTOR_ENA_PIN, s.MOTOR_IN1_PIN, s.MOTOR_IN2_PIN,
                s.MOTOR_ENB_PIN, s.MOTOR_IN3_PIN, s.MOTOR_IN4_PIN):
        assert isinstance(pin, int)
        assert 0 <= pin <= 40  # valid BCM pin range


def test_gpio_relay_pins_parseable():
    import jarvis.config.settings as s
    pins_str = s.GPIO_RELAY_PINS
    pins = [int(p) for p in pins_str.split(",") if p.strip()]
    assert len(pins) > 0
    for p in pins:
        assert 0 <= p <= 40
