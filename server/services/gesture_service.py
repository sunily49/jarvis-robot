"""
Gesture Detection Service — MediaPipe Hands.

Detects hand gestures: thumbs up, wave, stop, pointing, etc.
"""

import logging

import cv2
import mediapipe as mp
import numpy as np

logger = logging.getLogger(__name__)


class GestureService:
    def __init__(self) -> None:
        self._hands = mp.solutions.hands.Hands(
            static_image_mode=True,
            max_num_hands=2,
            min_detection_confidence=0.5,
        )
        logger.info("Gesture service initialized")

    def detect(self, jpeg_bytes: bytes) -> list[dict]:
        """Detect hand gestures in a JPEG image."""
        img_array = np.frombuffer(jpeg_bytes, dtype=np.uint8)
        frame = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        if frame is None:
            return []

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        result = self._hands.process(rgb)

        if not result.multi_hand_landmarks:
            return []

        gestures = []
        for hand_landmarks, handedness in zip(
            result.multi_hand_landmarks,
            result.multi_handedness,
        ):
            hand_label = handedness.classification[0].label
            gesture = self._classify_gesture(hand_landmarks)
            gestures.append({
                "hand": hand_label,
                "gesture": gesture,
                "confidence": round(handedness.classification[0].score, 3),
            })

        return gestures

    def _classify_gesture(self, landmarks) -> str:
        """Simple rule-based gesture classification from landmarks."""
        tips = [4, 8, 12, 16, 20]  # Thumb, index, middle, ring, pinky tips
        pips = [3, 6, 10, 14, 18]  # PIP joints

        fingers_up = []
        for tip, pip in zip(tips[1:], pips[1:]):  # Skip thumb
            fingers_up.append(landmarks.landmark[tip].y < landmarks.landmark[pip].y)

        # Thumb (special — uses x comparison)
        thumb_up = landmarks.landmark[4].x < landmarks.landmark[3].x

        all_up = all(fingers_up) and thumb_up
        all_down = not any(fingers_up) and not thumb_up
        index_only = fingers_up[0] and not any(fingers_up[1:])

        if all_up:
            return "open_hand"  # Stop / wave
        if all_down:
            return "fist"
        if index_only:
            return "pointing"
        if thumb_up and not any(fingers_up):
            return "thumbs_up"

        return "unknown"
