"""
Person Registry — unified identity store linking face, voice, and preferences.

Stores a JSON file mapping person names to their profile:
- face: bool (has face encoding in faces.pkl)
- voice: bool (has voice embedding in voices.pkl)
- preferences: dict (free-form key-value, e.g. {"greeting": "Hey boss"})
- notes: str (free text from Gemini observations)
- first_seen: ISO timestamp
- last_seen: ISO timestamp
- encounter_count: int

This is the "brain" that ties all recognition modalities together.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

REGISTRY_PATH = Path(__file__).parent.parent / "data" / "persons.json"


class PersonRegistry:
    def __init__(self) -> None:
        self._persons: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if REGISTRY_PATH.exists():
            with open(REGISTRY_PATH) as f:
                self._persons = json.load(f)
            logger.info("Loaded %d persons from registry", len(self._persons))
        else:
            logger.info("No person registry found — starting fresh")

    def _save(self) -> None:
        REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(REGISTRY_PATH, "w") as f:
            json.dump(self._persons, f, indent=2)

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def register(self, name: str, modality: str = "face") -> dict:
        """Register or update a person. modality = 'face' | 'voice' | 'both'."""
        key = name.lower()
        if key not in self._persons:
            self._persons[key] = {
                "name": name,
                "face": False,
                "voice": False,
                "preferences": {},
                "notes": "",
                "first_seen": self._now_iso(),
                "last_seen": self._now_iso(),
                "encounter_count": 0,
            }

        if modality in ("face", "both"):
            self._persons[key]["face"] = True
        if modality in ("voice", "both"):
            self._persons[key]["voice"] = True

        self._persons[key]["last_seen"] = self._now_iso()
        self._save()
        return self._persons[key]

    def record_encounter(self, name: str) -> dict | None:
        """Bump encounter count and last_seen for a known person."""
        key = name.lower()
        if key not in self._persons:
            return None
        self._persons[key]["encounter_count"] += 1
        self._persons[key]["last_seen"] = self._now_iso()
        self._save()
        return self._persons[key]

    def set_preference(self, name: str, pref_key: str, pref_value: Any) -> bool:
        """Set a preference for a person (e.g., greeting style, language)."""
        key = name.lower()
        if key not in self._persons:
            return False
        self._persons[key]["preferences"][pref_key] = pref_value
        self._save()
        return True

    def set_notes(self, name: str, notes: str) -> bool:
        """Update notes about a person (from Gemini observations)."""
        key = name.lower()
        if key not in self._persons:
            return False
        self._persons[key]["notes"] = notes
        self._save()
        return True

    def get_person(self, name: str) -> dict | None:
        """Get full profile for a person."""
        return self._persons.get(name.lower())

    def list_persons(self) -> list[dict]:
        """List all registered persons."""
        return list(self._persons.values())

    def remove(self, name: str) -> bool:
        """Remove a person from the registry."""
        key = name.lower()
        if key in self._persons:
            del self._persons[key]
            self._save()
            return True
        return False

    def get_context_for_person(self, name: str) -> str:
        """Generate a context string for Gemini about this person."""
        person = self.get_person(name)
        if not person:
            return ""
        parts = [f"Known person: {person['name']}"]
        if person["preferences"]:
            prefs = ", ".join(f"{k}={v}" for k, v in person["preferences"].items())
            parts.append(f"Preferences: {prefs}")
        if person["notes"]:
            parts.append(f"Notes: {person['notes']}")
        parts.append(f"Encounters: {person['encounter_count']}")
        return ". ".join(parts)
