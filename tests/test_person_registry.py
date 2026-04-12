"""Tests for PersonRegistry — JSON-backed identity store."""

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "server"))


@pytest.fixture
def registry(tmp_path, monkeypatch):
    """Provide a PersonRegistry backed by a temp directory."""
    import services.person_registry as pr_module
    monkeypatch.setattr(pr_module, "REGISTRY_PATH", tmp_path / "persons.json")
    from services.person_registry import PersonRegistry
    return PersonRegistry()


def test_register_new_person(registry):
    person = registry.register("Alice", modality="face")
    assert person["name"] == "Alice"
    assert person["face"] is True
    assert person["voice"] is False
    assert person["encounter_count"] == 0


def test_register_voice(registry):
    person = registry.register("Bob", modality="voice")
    assert person["voice"] is True
    assert person["face"] is False


def test_register_both_modalities(registry):
    person = registry.register("Carol", modality="both")
    assert person["face"] is True
    assert person["voice"] is True


def test_register_updates_existing(registry):
    registry.register("Dave", modality="face")
    updated = registry.register("Dave", modality="voice")
    # Both should now be True
    assert updated["face"] is True
    assert updated["voice"] is True


def test_get_person(registry):
    registry.register("Eve", modality="face")
    person = registry.get_person("Eve")
    assert person is not None
    assert person["name"] == "Eve"


def test_get_person_case_insensitive(registry):
    registry.register("Frank", modality="face")
    assert registry.get_person("frank") is not None
    assert registry.get_person("FRANK") is not None


def test_get_nonexistent_person(registry):
    assert registry.get_person("Nobody") is None


def test_record_encounter(registry):
    registry.register("Grace", modality="face")
    result = registry.record_encounter("Grace")
    assert result["encounter_count"] == 1
    result2 = registry.record_encounter("Grace")
    assert result2["encounter_count"] == 2


def test_record_encounter_unknown(registry):
    assert registry.record_encounter("Unknown") is None


def test_set_preference(registry):
    registry.register("Henry", modality="face")
    ok = registry.set_preference("Henry", "greeting", "Hey boss!")
    assert ok is True
    person = registry.get_person("Henry")
    assert person["preferences"]["greeting"] == "Hey boss!"


def test_set_preference_unknown(registry):
    assert registry.set_preference("Nobody", "key", "val") is False


def test_set_notes(registry):
    registry.register("Iris", modality="face")
    ok = registry.set_notes("Iris", "Likes classical music")
    assert ok is True
    person = registry.get_person("Iris")
    assert person["notes"] == "Likes classical music"


def test_list_persons(registry):
    registry.register("Jack", modality="face")
    registry.register("Kate", modality="voice")
    persons = registry.list_persons()
    names = [p["name"] for p in persons]
    assert "Jack" in names
    assert "Kate" in names


def test_remove_person(registry):
    registry.register("Liam", modality="face")
    removed = registry.remove("Liam")
    assert removed is True
    assert registry.get_person("Liam") is None


def test_remove_nonexistent(registry):
    assert registry.remove("Nobody") is False


def test_get_context_for_person(registry):
    registry.register("Mia", modality="face")
    registry.set_preference("Mia", "language", "English")
    registry.set_notes("Mia", "Owner of the house")
    ctx = registry.get_context_for_person("Mia")
    assert "Mia" in ctx
    assert "language" in ctx
    assert "Owner" in ctx


def test_get_context_empty_for_unknown(registry):
    assert registry.get_context_for_person("Unknown") == ""


def test_persistence(tmp_path, monkeypatch):
    """Registry should persist to disk and reload."""
    import services.person_registry as pr_module
    registry_path = tmp_path / "persons.json"
    monkeypatch.setattr(pr_module, "REGISTRY_PATH", registry_path)

    from services.person_registry import PersonRegistry
    reg1 = PersonRegistry()
    reg1.register("Noah", modality="both")
    reg1.set_preference("Noah", "color", "blue")

    # Load fresh instance
    reg2 = PersonRegistry()
    person = reg2.get_person("Noah")
    assert person is not None
    assert person["preferences"]["color"] == "blue"


def test_timestamps_are_set(registry):
    person = registry.register("Olivia", modality="face")
    assert person["first_seen"] != ""
    assert person["last_seen"] != ""
