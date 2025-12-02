# src/hardware/audio/audio_engine.py

from __future__ import annotations

from typing import Dict

import fluidsynth

from src.hardware.config.keys import KeyId


class AudioEngine:
    """
    Audio engine using FluidSynth + SoundFont.

    - Uses one MIDI channel (0) with a piano preset.
    - Exposes simple note_on/note_off by KeyId.
    - Compatible with the pyFluidSynth version on Raspberry Pi
      (no Settings(), no set_gain()).
    """

    def __init__(
        self,
        soundfont_path: str = (
            "/home/pi/pi-ano/src/hardware/audio/assets/sf2/"
            "YDP-GrandPiano-20160804.sf2"
        ),
        sample_rate: int = 44100,      # 目前沒實際用到，但保留參數也無妨
        default_velocity: int = 120,   # 暫時沒用到，可以之後擴充
        channel_volume: int = 120,     # 0 ~ 127, 主音量用這個調
        enable_reverb: bool = True,
        enable_chorus: bool = True,
    ) -> None:
        self.sample_rate = sample_rate
        self.default_velocity = default_velocity

        # 1. Create synth
        self.fs = fluidsynth.Synth()
        self.fs.start(driver="alsa")

        self.channel = 0

        # 2. Load SoundFont
        sfid = self.fs.sfload(soundfont_path)
        # 一般鋼琴通常在 bank=0, preset=0
        self.fs.program_select(self.channel, sfid, 0, 0)

        # 3. Set channel volume (這是你主要的音量控制)
        # CC7 = channel volume
        self.fs.cc(self.channel, 7, channel_volume)

        # 4. Optional effects
        if enable_reverb:
            # roomsize, damping, width, level
            self.fs.set_reverb(0.2, 0.2, 0.9, 0.6)

        if enable_chorus:
            # n, level, speed, depth, type
            self.fs.set_chorus(3, 0.5, 0.3, 6.0, 0)

        # Map KeyId → MIDI note number
        # 這裡假設 KEY_0 ~ KEY_4 對應 C4, D4, E4, F4, G4
        base_midi = 60  # C4 = 60
        self.key_to_midi: Dict[KeyId, int] = {
            KeyId.KEY_0: base_midi + 0,  # C4
            KeyId.KEY_1: base_midi + 2,  # D4
            KeyId.KEY_2: base_midi + 4,  # E4
            KeyId.KEY_3: base_midi + 5,  # F4
            KeyId.KEY_4: base_midi + 7,  # G4
            # 之後如果有 KEY_5~KEY_9 可以繼續往上 mapping
        }

    # ---------------------------------------------------------
    # Low-level MIDI helpers
    # ---------------------------------------------------------
    def _key_to_midi_note(self, key: KeyId) -> int | None:
        return self.key_to_midi.get(key)

    def note_on(self, key: KeyId, velocity: float = 1.0) -> None:
        """
        Trigger a piano note for given KeyId.

        velocity: 0.0 ~ 1.0 → mapped to MIDI 1~127
        """
        midi_note = self._key_to_midi_note(key)
        if midi_note is None:
            return

        v = max(0.0, min(1.0, velocity))
        vel = int(v * 127)
        if vel <= 0:
            vel = 1  # 避免 0 被部分系統視為 note_off

        self.fs.noteon(self.channel, midi_note, vel)

    def note_off(self, key: KeyId) -> None:
        midi_note = self._key_to_midi_note(key)
        if midi_note is None:
            return
        self.fs.noteoff(self.channel, midi_note)

    def stop_all(self) -> None:
        """Panic: turn off all notes on this channel."""
        for midi_note in range(0, 128):
            self.fs.noteoff(self.channel, midi_note)

    def close(self) -> None:
        """Clean up synth on exit."""
        self.stop_all()
        self.fs.delete()
