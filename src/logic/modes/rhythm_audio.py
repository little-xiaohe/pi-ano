# src/logic/modes/rhythm_audio.py
"""
Background audio scheduler for RhythmMode.

AudioScheduler runs in a separate thread and plays ChartNote.midi_note
at the correct time, independent from LED frame rate.
"""

from __future__ import annotations

import threading
import time
from typing import List, Optional

from src.hardware.audio.audio_engine import AudioEngine
from src.logic.modes.rhythm_chart import ChartNote


class AudioScheduler(threading.Thread):
    """
    Simple time-based scheduler in a background thread.

    It plays ChartNote.midi_note on the main AudioEngine channel, aligned
    to ChartNote.time.

    Usage:
        scheduler = AudioScheduler(audio, chart_notes, time_fn=time.monotonic)
        scheduler.set_start_time(play_start_time)
        scheduler.start()
        ...
        scheduler.stop()  # when leaving mode or restarting
    """

    def __init__(
        self,
        audio: Optional[AudioEngine],
        notes: List[ChartNote],
        time_fn=time.monotonic,
    ) -> None:
        super().__init__(daemon=True)
        self.audio = audio
        self.notes = notes
        self.time_fn = time_fn

        self.start_time: float | None = None
        self.idx: int = 0
        self._stop_flag = threading.Event()

    # ------------------------------------------------------------------
    # Lifecycle control
    # ------------------------------------------------------------------

    def set_start_time(self, start_time: float) -> None:
        """
        Define the "song time 0" reference point.

        RhythmMode calls this when PLAY phase starts so that:
            song_time = time_fn() - start_time
        matches the same reference used for LED animation.
        """
        self.start_time = start_time

    def stop(self) -> None:
        """
        Request the scheduler to stop as soon as possible.

        After calling stop(), you may optionally join() the thread.
        """
        self._stop_flag.set()

    # ------------------------------------------------------------------
    # Thread main loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        if self.audio is None:
            return

        # Wait until start_time is set or stop is requested
        while not self._stop_flag.is_set() and self.start_time is None:
            time.sleep(0.001)

        # Main scheduling loop
        while (
            not self._stop_flag.is_set()
            and self.start_time is not None
            and self.idx < len(self.notes)
        ):
            now = self.time_fn()
            song_time = now - self.start_time
            note = self.notes[self.idx]

            wait = note.time - song_time
            if wait > 0:
                # Sleep a bit to avoid busy looping
                time.sleep(min(wait, 0.01))
                continue

            # Time reached → play the melody note
            vel = int(max(0.1, min(1.0, note.velocity)) * 127)
            self.audio.note_on_midi(note.midi_note, vel)
            self.idx += 1

        # ⚠️ 重要改動：
        # - 如果是「自然播完全部 notes」（_stop_flag 沒被設），就不要 stop_all()，
        #   讓鋼琴音自然 decay，有「餘音」的感覺。
        # - 如果是外部呼叫 stop() 要中途停止（切 mode / reset），這時候才清音。
        if self.audio is not None and self._stop_flag.is_set():
            try:
                self.audio.stop_all()
            except Exception:
                # Best-effort cleanup; ignore errors on shutdown.
                pass
