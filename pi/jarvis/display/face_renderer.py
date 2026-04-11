"""
Animated Robot Face — expressive eyes with emotions and state indicators.

Renders vectorized eyes on a pygame surface. Eyes blink, look around,
and change shape based on emotion state.

Emotions: neutral, happy, sad, angry, surprised, thinking, listening, speaking, sleeping
"""

import math
import random
import time
from enum import Enum, auto

import pygame

# ── Colors ────────────────────────────────────────────────────────────
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
CYAN = (0, 220, 255)
DARK_CYAN = (0, 140, 180)
BLUE = (30, 120, 255)
GREEN = (0, 255, 120)
RED = (255, 60, 60)
ORANGE = (255, 165, 0)
YELLOW = (255, 220, 0)
DIM_WHITE = (80, 80, 80)
BG_COLOR = (10, 10, 20)


class Emotion(Enum):
    NEUTRAL = auto()
    HAPPY = auto()
    SAD = auto()
    ANGRY = auto()
    SURPRISED = auto()
    THINKING = auto()
    LISTENING = auto()
    SPEAKING = auto()
    SLEEPING = auto()


class FaceRenderer:
    """Renders an animated robot face with expressive eyes."""

    def __init__(self, width: int, height: int) -> None:
        self._w = width
        self._h = height
        self._emotion = Emotion.NEUTRAL
        self._target_emotion = Emotion.NEUTRAL

        # Eye parameters
        self._eye_w = width // 5          # Eye width
        self._eye_h = height // 3         # Eye height
        self._eye_spacing = width // 6    # Gap between eyes
        self._eye_y = height // 2 - 20    # Vertical center

        # Animation state
        self._blink_timer = time.time() + random.uniform(2, 6)
        self._blink_progress = 0.0       # 0 = open, 1 = closed
        self._is_blinking = False

        self._look_x = 0.0              # -1 to 1 (left to right)
        self._look_y = 0.0              # -1 to 1 (up to down)
        self._target_look_x = 0.0
        self._target_look_y = 0.0
        self._look_timer = time.time() + random.uniform(1, 4)

        self._speak_phase = 0.0         # For speaking animation
        self._think_dots = 0            # For thinking animation
        self._think_timer = time.time()

        self._pulse_phase = 0.0         # Ambient pulse

        # Status bar text
        self._status_text = ""
        self._status_color = CYAN

    @property
    def emotion(self) -> Emotion:
        return self._emotion

    def set_emotion(self, emotion: Emotion) -> None:
        self._target_emotion = emotion

    def set_status(self, text: str, color: tuple = CYAN) -> None:
        self._status_text = text
        self._status_color = color

    def update(self, dt: float) -> None:
        """Update animation state. Call every frame."""
        now = time.time()
        self._pulse_phase += dt * 2

        # Transition emotion
        self._emotion = self._target_emotion

        # Blink logic
        if not self._is_blinking and now > self._blink_timer:
            self._is_blinking = True
            self._blink_progress = 0.0

        if self._is_blinking:
            self._blink_progress += dt * 8  # Fast blink
            if self._blink_progress >= 2.0:  # Full close + open cycle
                self._is_blinking = False
                self._blink_progress = 0.0
                self._blink_timer = now + random.uniform(2, 6)
                if self._emotion == Emotion.SLEEPING:
                    self._blink_timer = now + random.uniform(4, 8)

        # Look-around logic
        if now > self._look_timer and self._emotion not in (Emotion.SLEEPING,):
            self._target_look_x = random.uniform(-0.5, 0.5)
            self._target_look_y = random.uniform(-0.3, 0.3)
            self._look_timer = now + random.uniform(1.5, 4)

        # Smooth interpolation
        self._look_x += (self._target_look_x - self._look_x) * min(dt * 4, 1)
        self._look_y += (self._target_look_y - self._look_y) * min(dt * 4, 1)

        # Speaking animation
        if self._emotion == Emotion.SPEAKING:
            self._speak_phase += dt * 12

        # Thinking animation
        if self._emotion == Emotion.THINKING and now > self._think_timer:
            self._think_dots = (self._think_dots + 1) % 4
            self._think_timer = now + 0.5

    def render(self, surface: pygame.Surface) -> None:
        """Render the face onto the given surface."""
        surface.fill(BG_COLOR)

        cx = self._w // 2
        cy = self._eye_y

        # Left eye center, right eye center
        lx = cx - self._eye_spacing
        rx = cx + self._eye_spacing

        # Blink squeeze factor (0=open, 1=closed)
        if self._is_blinking:
            squeeze = 1.0 - abs(self._blink_progress - 1.0)
        elif self._emotion == Emotion.SLEEPING:
            squeeze = 0.85  # Mostly closed
        else:
            squeeze = 0.0

        # Draw both eyes
        self._draw_eye(surface, lx, cy, squeeze, is_left=True)
        self._draw_eye(surface, rx, cy, squeeze, is_left=False)

        # Draw mouth / expression indicator below eyes
        self._draw_mouth(surface, cx, cy + self._eye_h // 2 + 40)

        # Status bar at bottom
        if self._status_text:
            self._draw_status_bar(surface)

        # Ambient glow pulse around eyes
        self._draw_ambient(surface, lx, rx, cy)

    def _draw_eye(
        self, surface: pygame.Surface, cx: int, cy: int, squeeze: float, is_left: bool
    ) -> None:
        """Draw a single eye with emotion-specific shape."""
        ew = self._eye_w
        eh = int(self._eye_h * (1.0 - squeeze * 0.9))

        # Pupil offset from look direction
        pupil_dx = int(self._look_x * ew * 0.2)
        pupil_dy = int(self._look_y * eh * 0.15)

        # Emotion-specific eye shape
        emotion = self._emotion
        eye_color = CYAN
        pupil_color = WHITE

        if emotion == Emotion.HAPPY:
            # Squinted happy — bottom curve up (arc eyes)
            eh = int(eh * 0.7)
            eye_color = GREEN
        elif emotion == Emotion.SAD:
            # Droopy — top angled down on outer side
            eh = int(eh * 0.8)
            eye_color = BLUE
        elif emotion == Emotion.ANGRY:
            # Narrowed, angled inward at top
            eh = int(eh * 0.6)
            eye_color = RED
        elif emotion == Emotion.SURPRISED:
            # Wide open circles
            eh = int(eh * 1.3)
            ew = int(ew * 1.1)
            eye_color = YELLOW
        elif emotion == Emotion.LISTENING:
            eye_color = CYAN
            # Slightly wider
            eh = int(eh * 1.1)
        elif emotion == Emotion.SPEAKING:
            # Pulse size with speech
            scale = 1.0 + math.sin(self._speak_phase) * 0.05
            ew = int(ew * scale)
            eh = int(eh * scale)
            eye_color = GREEN
        elif emotion == Emotion.SLEEPING:
            eye_color = DIM_WHITE
            pupil_color = DIM_WHITE

        # Eye outline (rounded rect)
        eye_rect = pygame.Rect(cx - ew // 2, cy - eh // 2, ew, eh)
        border_radius = min(ew, eh) // 3

        # Glow effect (larger, dimmer)
        glow_color = tuple(max(0, c - 180) for c in eye_color)
        glow_rect = eye_rect.inflate(12, 12)
        pygame.draw.rect(surface, glow_color, glow_rect, border_radius=border_radius + 4)

        # Eye background
        pygame.draw.rect(surface, (15, 15, 30), eye_rect, border_radius=border_radius)

        # Eye border
        pygame.draw.rect(surface, eye_color, eye_rect, width=3, border_radius=border_radius)

        if squeeze < 0.85:
            # Pupil (inner filled shape)
            pupil_w = ew // 3
            pupil_h = int(eh * 0.5 * (1 - squeeze))
            pupil_rect = pygame.Rect(
                cx + pupil_dx - pupil_w // 2,
                cy + pupil_dy - pupil_h // 2,
                pupil_w,
                pupil_h,
            )
            pygame.draw.ellipse(surface, pupil_color, pupil_rect)

            # Highlight dot
            highlight_r = max(3, pupil_w // 5)
            pygame.draw.circle(
                surface, eye_color,
                (cx + pupil_dx - pupil_w // 4, cy + pupil_dy - pupil_h // 4),
                highlight_r,
            )

        # Angry brow (diagonal line above eye)
        if emotion == Emotion.ANGRY:
            brow_y = cy - eh // 2 - 15
            if is_left:
                pygame.draw.line(surface, RED, (cx - ew // 2 - 5, brow_y - 10), (cx + ew // 2 + 5, brow_y + 5), 4)
            else:
                pygame.draw.line(surface, RED, (cx - ew // 2 - 5, brow_y + 5), (cx + ew // 2 + 5, brow_y - 10), 4)

        # Sad brow (angled down on outer edges)
        if emotion == Emotion.SAD:
            brow_y = cy - eh // 2 - 12
            if is_left:
                pygame.draw.line(surface, BLUE, (cx - ew // 2, brow_y + 5), (cx + ew // 2, brow_y - 5), 3)
            else:
                pygame.draw.line(surface, BLUE, (cx - ew // 2, brow_y - 5), (cx + ew // 2, brow_y + 5), 3)

    def _draw_mouth(self, surface: pygame.Surface, cx: int, cy: int) -> None:
        """Draw mouth/expression indicator."""
        emotion = self._emotion
        mouth_w = self._eye_spacing

        if emotion == Emotion.HAPPY:
            # Smile arc
            rect = pygame.Rect(cx - mouth_w // 2, cy - 15, mouth_w, 30)
            pygame.draw.arc(surface, GREEN, rect, math.pi + 0.3, 2 * math.pi - 0.3, 3)

        elif emotion == Emotion.SAD:
            # Frown arc
            rect = pygame.Rect(cx - mouth_w // 2, cy, mouth_w, 30)
            pygame.draw.arc(surface, BLUE, rect, 0.3, math.pi - 0.3, 3)

        elif emotion == Emotion.SURPRISED:
            # O-shape
            pygame.draw.ellipse(surface, YELLOW, (cx - 15, cy - 10, 30, 25), 3)

        elif emotion == Emotion.SPEAKING:
            # Animated open/close
            mouth_h = int(8 + abs(math.sin(self._speak_phase)) * 15)
            pygame.draw.ellipse(surface, GREEN, (cx - 20, cy - mouth_h // 2, 40, mouth_h), 2)

        elif emotion == Emotion.THINKING:
            # Dots animation
            dot_text = "." * self._think_dots
            font = pygame.font.SysFont("monospace", 28, bold=True)
            txt = font.render(dot_text, True, CYAN)
            surface.blit(txt, (cx - txt.get_width() // 2, cy - 5))

        elif emotion == Emotion.LISTENING:
            # Small horizontal line (attentive)
            pygame.draw.line(surface, CYAN, (cx - 20, cy), (cx + 20, cy), 2)
            # Sound wave arcs
            for i in range(3):
                offset = int(math.sin(self._pulse_phase + i * 0.8) * 5)
                alpha = max(50, 200 - i * 60)
                wave_color = (*CYAN[:3],)
                arc_rect = pygame.Rect(cx - 30 - i * 12, cy - 10 - i * 5 + offset, 60 + i * 24, 20 + i * 10)
                pygame.draw.arc(surface, wave_color, arc_rect, 0.5, 2.6, 2)

        elif emotion == Emotion.NEUTRAL:
            # Simple dash
            pygame.draw.line(surface, DARK_CYAN, (cx - 25, cy), (cx + 25, cy), 2)

    def _draw_ambient(
        self, surface: pygame.Surface, lx: int, rx: int, cy: int
    ) -> None:
        """Subtle ambient glow that pulses."""
        if self._emotion == Emotion.SLEEPING:
            return

        alpha = int(20 + math.sin(self._pulse_phase) * 10)
        glow_surf = pygame.Surface((self._w, self._h), pygame.SRCALPHA)

        for ex in (lx, rx):
            color = (*CYAN[:3], alpha)
            pygame.draw.circle(glow_surf, color, (ex, cy), self._eye_w // 2 + 30)

        surface.blit(glow_surf, (0, 0))

    def _draw_status_bar(self, surface: pygame.Surface) -> None:
        """Draw status text at bottom of face area."""
        font = pygame.font.SysFont("monospace", 18)
        txt = font.render(self._status_text, True, self._status_color)
        x = (self._w - txt.get_width()) // 2
        y = self._h - 50
        surface.blit(txt, (x, y))
