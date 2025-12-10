from __future__ import annotations

from typing import Dict, Optional, List
import os

import fluidsynth

from src.hardware.config.keys import KeyId

# --------------------------------------------------------------------------------------
# Per-SoundFont Volume Table（不用 set_gain，因為舊版沒有）
# 依照檔名調整 MIDI Volume (0~127)
# gain 無法動態設，但 Volume 127 基本上就能補回差距。
# --------------------------------------------------------------------------------------

SOUNDFONT_VOLUME: Dict[str, int] = {
    "00_piano.sf2": 110,   # 偏大 → 壓低一點
    "01_guitar.sf2": 127,  # guitar 比較小聲 → 撐滿
}


class AudioEngine:
    """
    Audio engine using FluidSynth + SoundFont.

    - Channel 0: main piano
    - Channel 1: hit SFX
    - 支援多個 SoundFont，可動態切換（長按 KEY_0）
    """

    def __init__(
        self,
        soundfont_path: str = "/home/pi/pi-ano/src/hardware/audio/assets/sf2/00_piano.sf2",
        soundfont_dir: Optional[str] = "/home/pi/pi-ano/src/hardware/audio/assets/sf2/",
        sample_rate: int = 44100,
        default_velocity: int = 100,
        default_gain: float = 1.8,       # 初始 gain → 可調高補音量
    ) -> None:

        self.sample_rate = sample_rate
        self.default_velocity = default_velocity
        self.default_gain = default_gain

        # ---- create synth & start audio driver ----
        self.fs = fluidsynth.Synth(gain=self.default_gain, samplerate=sample_rate)
        self.fs.start(driver="alsa")

        # ---- channels ----
        self.piano_channel: int = 0
        self.hit_channel: int = 1

        # ---- soundfont management ----
        self._soundfont_ids: List[int] = []
        self._soundfont_paths: List[str] = []
        self._current_sf_index: int = 0

        # 嘗試從資料夾載入全部 sf2
        if soundfont_dir is not None:
            self._load_soundfonts_from_dir(soundfont_dir)

        # 如果沒載到 → fallback 使用單檔
        if not self._soundfont_ids:
            self.add_soundfont(soundfont_path)

        # 套用第一個 SoundFont
        self._apply_current_soundfont()

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

    # ------------------------------------------------------------------
    # SoundFont management
    # ------------------------------------------------------------------

    def _load_soundfonts_from_dir(self, directory: str) -> None:
        if not os.path.isdir(directory):
            print(f"[AudioEngine] soundfont_dir not found: {directory}")
            return

        try:
            entries = sorted(os.listdir(directory))
        except Exception as e:
            print(f"[AudioEngine] listdir failed: {directory} ({e})")
            return

        count = 0
        for name in entries:
            if name.lower().endswith(".sf2"):
                path = os.path.join(directory, name)
                if os.path.isfile(path):
                    self.add_soundfont(path)
                    count += 1

        print(f"[AudioEngine] Loaded {count} SoundFont(s) from {directory}")

    def add_soundfont(self, path: str) -> None:
        try:
            sfid = self.fs.sfload(path)
        except Exception as e:
            print(f"[AudioEngine] sfload failed: {path} ({e})")
            return

        self._soundfont_ids.append(sfid)
        self._soundfont_paths.append(path)

        if len(self._soundfont_ids) == 1:
            self._current_sf_index = 0

        print(f"[AudioEngine] SoundFont added: {path} (id={sfid})")

    def _apply_current_soundfont(self) -> None:
        """
        Apply SoundFont & adjust CC7 volume for both channels.
        """
        sfid = self._soundfont_ids[self._current_sf_index]
        path = self._soundfont_paths[self._current_sf_index]
        basename = os.path.basename(path)

        # SoundFont instrument
        self.fs.program_select(self.piano_channel, sfid, 0, 0)
        self.fs.program_select(self.hit_channel, sfid, 0, 0)

        # Volume tuning via CC7
        volume = SOUNDFONT_VOLUME.get(basename, 120)
        volume = max(0, min(127, int(volume)))

        self.fs.cc(self.piano_channel, 7, volume)
        self.fs.cc(self.hit_channel, 7, volume)

        print(f"[AudioEngine] Using SF[{self._current_sf_index}]: {basename} (vol={volume})")

    def cycle_soundfont(self) -> None:
        if not self._soundfont_ids:
            print("[AudioEngine] No SoundFont loaded.")
            return

        self._current_sf_index = (self._current_sf_index + 1) % len(self._soundfont_ids)
        self._apply_current_soundfont()

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _vel01_to_127(v: float) -> int:
        return max(1, min(127, int(max(0.0, min(1.0, v)) * 127)))

    # ------------------------------------------------------------------
    # KeyId API（給 PianoMode）
    # ------------------------------------------------------------------
    def _key_to_midi_note(self, key: KeyId) -> Optional[int]:
        return self.key_to_midi.get(key)

    def note_on(self, key: KeyId, velocity: float = 1.0) -> None:
        midi_note = self._key_to_midi_note(key)
        if midi_note is not None:
            self.fs.noteon(self.piano_channel, midi_note, self._vel01_to_127(velocity))

    def note_off(self, key: KeyId) -> None:
        midi_note = self._key_to_midi_note(key)
        if midi_note is not None:
            self.fs.noteoff(self.piano_channel, midi_note)

    # ------------------------------------------------------------------
    # MIDI API（給 SongMode / RhythmMode）
    # ------------------------------------------------------------------
    def note_on_midi(self, midi_note: int, velocity) -> None:
        self.fs.noteon(self.piano_channel, midi_note, self._vel01_to_127(velocity))

    def note_off_midi(self, midi_note: int) -> None:
        self.fs.noteoff(self.piano_channel, midi_note)

    # ------------------------------------------------------------------
    # Hit SFX
    # ------------------------------------------------------------------
    def play_hit_sfx(self, velocity: float = 1.0) -> None:
        self.fs.noteon(self.hit_channel, self.hit_note, self._vel01_to_127(velocity))

    # ------------------------------------------------------------------
    # STOP & cleanup
    # ------------------------------------------------------------------
    def stop_all(self) -> None:
        for n in range(128):
            self.fs.noteoff(self.piano_channel, n)
            self.fs.noteoff(self.hit_channel, n)

    def close(self) -> None:
        self.stop_all()
        self.fs.delete()
