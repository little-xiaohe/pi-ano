# src/hardware/audio/audio_engine.py

from __future__ import annotations

from typing import Dict, Optional

import fluidsynth

from src.hardware.config.keys import KeyId


class AudioEngine:
    """
    Audio engine using FluidSynth + SoundFont.

    - Channel 0: main piano (for piano mode, song mode, rhythm melody).
    - Channel 1: hit SFX (short accent note for rhythm hits).
    """

    def __init__(
        self,
        soundfont_path: str = "/home/pi/pi-ano/src/hardware/audio/assets/sf2/Nord-Black-Upright.sf2",
        sample_rate: int = 44100,
        default_velocity: int = 100,
    ) -> None:
        # print("[AudioEngine] INIT: starting FluidSynth")

        self.sample_rate = sample_rate
        self.default_velocity = default_velocity

        # ---- create synth & start audio driver ----
        self.fs = fluidsynth.Synth(gain=1.5, samplerate=sample_rate)
        self.fs.start(driver="alsa")

        # ---- channels ----
        self.piano_channel: int = 0
        self.hit_channel: int = 1

        # ---- load SoundFont ----
        # print(f"[AudioEngine] Loading SoundFont: {soundfont_path}")
        sfid = self.fs.sfload(soundfont_path)
        # print(f"[AudioEngine] SoundFont loaded, id = {sfid}")

        self.fs.program_select(self.piano_channel, sfid, 0, 0)
        self.fs.program_select(self.hit_channel, sfid, 0, 0)

        # ---- channel volume ----
        channel_volume = 127
        self.fs.cc(self.piano_channel, 7, channel_volume)
        self.fs.cc(self.hit_channel, 7, channel_volume)

        # ---- KeyId → MIDI note mapping ----
        base_midi = 60  # C4
        self.key_to_midi: Dict[KeyId, int] = {
            KeyId.KEY_0: base_midi + 0,
            KeyId.KEY_1: base_midi + 2,
            KeyId.KEY_2: base_midi + 4,
            KeyId.KEY_3: base_midi + 5,
            KeyId.KEY_4: base_midi + 7,
        }

        self.hit_note: int = 84  # C6

        # print("[AudioEngine] INIT complete.\n")

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _vel01_to_127(velocity01: float) -> int:
        v = max(0.0, min(1.0, velocity01))
        vel = int(v * 127)
        return max(1, vel)

    # ------------------------------------------------------------------
    # KeyId-based API（給 PianoMode）
    # ------------------------------------------------------------------
    def _key_to_midi_note(self, key: KeyId) -> Optional[int]:
        return self.key_to_midi.get(key)

    def note_on(self, key: KeyId, velocity: float = 1.0) -> None:
        midi_note = self._key_to_midi_note(key)
        if midi_note is None:
            return

        vel = self._vel01_to_127(velocity)
        # print(f"[AudioEngine] note_on(Key={key}, midi={midi_note}, vel={vel})")
        self.fs.noteon(self.piano_channel, midi_note, vel)

    def note_off(self, key: KeyId) -> None:
        midi_note = self._key_to_midi_note(key)
        if midi_note is None:
            return
        # print(f"[AudioEngine] note_off(Key={key}, midi={midi_note})")
        self.fs.noteoff(self.piano_channel, midi_note)

    # ------------------------------------------------------------------
    # MIDI API（給 SongMode / RhythmMode）
    # ------------------------------------------------------------------
    def note_on_midi(self, midi_note: int, velocity: int | float = 100) -> None:
        if isinstance(velocity, float):
            vel = self._vel01_to_127(velocity)
        else:
            vel = max(1, min(127, int(velocity)))

        # print(f"[AudioEngine] note_on_midi({midi_note}, vel={vel})")
        self.fs.noteon(self.piano_channel, int(midi_note), vel)

    def note_off_midi(self, midi_note: int) -> None:
        # print(f"[AudioEngine] note_off_midi({midi_note})  <<< CALLED")
        self.fs.noteoff(self.piano_channel, int(midi_note))

    # ------------------------------------------------------------------
    # Hit SFX（給 RhythmMode）
    # ------------------------------------------------------------------
    def play_hit_sfx(self, velocity: float = 1.0) -> None:
        vel = self._vel01_to_127(velocity)
        # print(f"[AudioEngine] play_hit_sfx(vel={vel})")
        self.fs.noteon(self.hit_channel, self.hit_note, vel)

    # ------------------------------------------------------------------
    # 全域 STOP & 清理
    # ------------------------------------------------------------------
    def stop_all(self) -> None:
        # print("[AudioEngine] stop_all() CALLED  <<< THIS CLEARS ALL SOUND")
        for midi_note in range(0, 128):
            self.fs.noteoff(self.piano_channel, midi_note)
            self.fs.noteoff(self.hit_channel, midi_note)

    def close(self) -> None:
        # print("[AudioEngine] close() CALLED  <<< DELETE SYNTH")
        self.stop_all()
        self.fs.delete()
