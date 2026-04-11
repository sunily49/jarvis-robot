"""Shared pytest configuration and fixtures."""

import sys
from pathlib import Path

# Add pi/jarvis to path so imports work
sys.path.insert(0, str(Path(__file__).parent.parent / "pi"))

import pytest
