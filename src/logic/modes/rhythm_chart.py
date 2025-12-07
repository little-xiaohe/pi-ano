# src/logic/modes/rhythm_chart.py
"""
Data types for rhythm game charts.

Currently contains:
    - ChartNote: one compressed melody note used in RhythmMode
"""

from __future__ import annotations

from dataclasses import dataclass

from src.hardware.config.keys import KeyId


@dataclass
class ChartNote:
    """
    One compressed melody note in the rhythm chart.

    Attributes:
        time:       Seconds from song start (float).
        midi_note:  MIDI note number (0–127).
        key:        Logical lane (KeyId 0..4).
        velocity:   Original note velocity, mapped to 0.0–1.0.
        hit:        True if successfully hit by the player.
        judged:     True if already judged as hit or miss.
        score:      0, 1, or 2 points from this note.
    """
    time: float
    midi_note: int
    key: KeyId
    velocity: float
    hit: bool = False
    judged: bool = False
    score: int = 0
