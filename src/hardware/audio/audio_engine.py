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
        soundfont_path: str = "/home/pi/pi-ano/src/hardware/audio/assets/sf2/YDP-GrandPiano-20160804.sf2",
        sample_rate: int = 44100,
        default_velocity: int = 100,
    ) -> None:
        self.sample_rate = sample_rate
        self.default_velocity = default_velocity

        # ---- create synth & start audio driver ----
        # driver="alsa" 通常是 RPi 最穩的設定
        self.fs = fluidsynth.Synth()
        self.fs.start(driver="alsa")

        # ---- channels ----
        self.piano_channel: int = 0
        self.hit_channel: int = 1

        # ---- load SoundFont & select piano program on both channels ----
        sfid = self.fs.sfload(soundfont_path)
        # bank 0, preset 0 通常是 Grand Piano
        self.fs.program_select(self.piano_channel, sfid, 0, 0)
        self.fs.program_select(self.hit_channel, sfid, 0, 0)

        # ---- channel volume (7 = volume CC) ----
        # 0~127，這裡給一個中間偏大的音量
        channel_volume = 100
        self.fs.cc(self.piano_channel, 7, channel_volume)
        self.fs.cc(self.hit_channel, 7, channel_volume)

        # ---- KeyId → MIDI note mapping (for piano mode IR / keyboard) ----
        # 這裡假設 KEY_0 ~ KEY_4 對應 C4, D4, E4, F4, G4
        base_midi = 60  # C4 = 60
        self.key_to_midi: Dict[KeyId, int] = {
            KeyId.KEY_0: base_midi + 0,  # C4
            KeyId.KEY_1: base_midi + 2,  # D4
            KeyId.KEY_2: base_midi + 4,  # E4
            KeyId.KEY_3: base_midi + 5,  # F4
            KeyId.KEY_4: base_midi + 7,  # G4
            # 如果之後有 KEY_5~KEY_9 可以繼續往上 mapping
        }

        # hit SFX 用的 note（高一點的音，會比較突出）
        self.hit_note: int = 84  # 大約是 C6 附近

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _vel01_to_127(velocity01: float) -> int:
        """
        把 0.0~1.0 的 velocity 轉成 1~127 的 MIDI velocity。
        """
        v = max(0.0, min(1.0, velocity01))
        vel = int(v * 127)
        if vel <= 0:
            vel = 1
        return vel

    # ------------------------------------------------------------------
    # KeyId-based API（給 PianoMode 用）
    # ------------------------------------------------------------------
    def _key_to_midi_note(self, key: KeyId) -> Optional[int]:
        return self.key_to_midi.get(key)

    def note_on(self, key: KeyId, velocity: float = 1.0) -> None:
        """
        Trigger a piano note for given KeyId.

        velocity: 0.0 ~ 1.0 → mapped to MIDI 0~127
        """
        midi_note = self._key_to_midi_note(key)
        if midi_note is None:
            return

        vel = self._vel01_to_127(velocity)
        self.fs.noteon(self.piano_channel, midi_note, vel)

    def note_off(self, key: KeyId) -> None:
        midi_note = self._key_to_midi_note(key)
        if midi_note is None:
            return
        self.fs.noteoff(self.piano_channel, midi_note)

    # ------------------------------------------------------------------
    # MIDI note–based API（給 song mode / rhythm mode 用）
    # ------------------------------------------------------------------
    def note_on_midi(self, midi_note: int, velocity: int | float = 100) -> None:
        """
        播放「指定 MIDI note」。

        velocity:
          - 如果是 float 0.0~1.0 → 自動轉成 1~127
          - 如果是 int → 視為 0~127 直接使用
        """
        if isinstance(velocity, float):
            vel = self._vel01_to_127(velocity)
        else:
            vel = max(1, min(127, int(velocity)))

        self.fs.noteon(self.piano_channel, int(midi_note), vel)

    def note_off_midi(self, midi_note: int) -> None:
        self.fs.noteoff(self.piano_channel, int(midi_note))

    # ------------------------------------------------------------------
    # Hit SFX（給 RhythmMode 用）
    # ------------------------------------------------------------------
    def play_hit_sfx(self, velocity: float = 1.0) -> None:
        """
        播一個短促的「命中」音效。

        這裡簡單做法：
        - 同一個 SoundFont
        - 不同 channel（hit_channel）
        - 播高音 note（self.hit_note）
        - 不 blocking，Envelope 自己會收尾
        """
        vel = self._vel01_to_127(velocity)
        self.fs.noteon(self.hit_channel, self.hit_note, vel)
        # 不立刻 noteoff，讓音色自然 decay。
        # 如果你覺得 sustain 太長，可以在這裡再開一個
        # 簡單的 thread / timer 去 noteoff。

    # ------------------------------------------------------------------
    # 全域 STOP & 清理
    # ------------------------------------------------------------------
    def stop_all(self) -> None:
        """Panic: turn off all notes on both channels."""
        for midi_note in range(0, 128):
            self.fs.noteoff(self.piano_channel, midi_note)
            self.fs.noteoff(self.hit_channel, midi_note)

    def close(self) -> None:
        """Clean up synth on exit."""
        self.stop_all()
        self.fs.delete()
