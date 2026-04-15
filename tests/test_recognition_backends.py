"""
Tests for modular recognition backends.

Covers:
- VAD: EnergyVAD speech/silence detection, factory auto-selection
- Face detector: HaarCascadeDetector creation, factory auto-selection, FaceDetection dataclass
"""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "pi"))


# ── VAD tests ─────────────────────────────────────────────────────────────────

class TestEnergyVAD:
    def setup_method(self):
        from jarvis.audio.vad import EnergyVAD
        self.vad = EnergyVAD(threshold=400)

    def test_silence_returns_false(self):
        """Zero signal should not be detected as speech."""
        silence = np.zeros(1024, dtype=np.int16)
        assert self.vad.is_speech(silence) is False

    def test_loud_signal_returns_true(self):
        """High-amplitude signal should be detected as speech."""
        loud = np.full(1024, 8000, dtype=np.int16)
        assert self.vad.is_speech(loud) is True

    def test_just_below_threshold(self):
        """Signal with RMS just below threshold should be False."""
        # RMS of constant value v is v itself
        # threshold=400, so use 399
        below = np.full(1024, 399, dtype=np.int16)
        assert self.vad.is_speech(below) is False

    def test_at_threshold(self):
        """Signal at exactly the threshold should be True (>=)."""
        at = np.full(1024, 400, dtype=np.int16)
        assert self.vad.is_speech(at) is True

    def test_reset_does_not_raise(self):
        """EnergyVAD.reset() is a no-op but must not raise."""
        self.vad.reset()  # stateless — just must not raise

    def test_repr(self):
        assert "EnergyVAD" in repr(self.vad)
        assert "400" in repr(self.vad)


class TestCreateVAD:
    def test_auto_returns_base_vad(self):
        """create_vad('auto') must always return a BaseVAD (EnergyVAD at minimum)."""
        from jarvis.audio.vad import BaseVAD, create_vad
        vad = create_vad("auto")
        assert isinstance(vad, BaseVAD)

    def test_explicit_energy_backend(self):
        from jarvis.audio.vad import EnergyVAD, create_vad
        vad = create_vad("energy")
        assert isinstance(vad, EnergyVAD)

    def test_unknown_backend_raises(self):
        from jarvis.audio.vad import create_vad
        with pytest.raises(ValueError, match="Unknown VAD backend"):
            create_vad("nonexistent_backend")

    def test_auto_result_is_functional(self):
        """VAD returned by auto-factory should process audio without error."""
        from jarvis.audio.vad import create_vad
        vad = create_vad("auto")
        vad.reset()
        silence = np.zeros(1024, dtype=np.int16)
        result = vad.is_speech(silence)
        assert isinstance(result, bool)


# ── Face detector tests ────────────────────────────────────────────────────────

class TestFaceDetection:
    def test_dataclass_fields(self):
        from jarvis.vision.face_detector import FaceDetection
        fd = FaceDetection(bbox=(10, 20, 50, 60), confidence=0.9)
        assert fd.bbox == (10, 20, 50, 60)
        assert fd.confidence == pytest.approx(0.9)

    def test_area_property(self):
        from jarvis.vision.face_detector import FaceDetection
        fd = FaceDetection(bbox=(0, 0, 100, 80), confidence=1.0)
        assert fd.area == 8000

    def test_center_property(self):
        from jarvis.vision.face_detector import FaceDetection
        fd = FaceDetection(bbox=(10, 20, 100, 80), confidence=1.0)
        assert fd.center == (60, 60)


class TestHaarCascadeDetector:
    def test_creates_successfully(self):
        from jarvis.vision.face_detector import HaarCascadeDetector
        det = HaarCascadeDetector()
        assert det is not None

    def test_blank_frame_returns_empty(self):
        """A blank black frame should contain no faces."""
        from jarvis.vision.face_detector import HaarCascadeDetector
        det = HaarCascadeDetector()
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        faces = det.detect(frame)
        assert faces == []

    def test_returns_list(self):
        """detect() always returns a list."""
        from jarvis.vision.face_detector import HaarCascadeDetector
        det = HaarCascadeDetector()
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        result = det.detect(frame)
        assert isinstance(result, list)

    def test_close_does_not_raise(self):
        from jarvis.vision.face_detector import HaarCascadeDetector
        det = HaarCascadeDetector()
        det.close()  # base class no-op


class TestCreateFaceDetector:
    def test_auto_returns_base_detector(self):
        """create_face_detector('auto') must always return a BaseFaceDetector."""
        from jarvis.vision.face_detector import BaseFaceDetector, create_face_detector
        det = create_face_detector("auto")
        assert isinstance(det, BaseFaceDetector)
        det.close()

    def test_explicit_haar_backend(self):
        from jarvis.vision.face_detector import HaarCascadeDetector, create_face_detector
        det = create_face_detector("haar")
        assert isinstance(det, HaarCascadeDetector)
        det.close()

    def test_unknown_backend_raises(self):
        from jarvis.vision.face_detector import create_face_detector
        with pytest.raises(ValueError, match="Unknown face detector backend"):
            create_face_detector("nonexistent_backend")

    def test_auto_result_is_functional(self):
        """Detector returned by auto-factory should process a frame without error."""
        from jarvis.vision.face_detector import create_face_detector
        det = create_face_detector("auto")
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        faces = det.detect(frame)
        assert isinstance(faces, list)
        det.close()
