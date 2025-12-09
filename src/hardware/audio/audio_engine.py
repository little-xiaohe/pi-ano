from __future__ import annotations

from typing import Dict, Optional, List
import os

import fluidsynth

from src.hardware.config.keys import KeyId


class AudioEngine:
    """
    Audio engine using FluidSynth + SoundFont.

    - Channel 0: main piano (for piano mode, song mode, rhythm melody).
    - Channel 1: hit SFX (short accent note for rhythm hits).
    - 支援多個 SoundFont，長按 KEY_0 時在它們之間輪流切換。
    - 可以指定一個資料夾，會自動載入底下所有 .sf2 檔。
    """

    def __init__(
        self,
        soundfont_path: str = "/home/pi/pi-ano/src/hardware/audio/assets/sf2/piano.sf2",
        soundfont_dir: Optional[str] = "/home/pi/pi-ano/src/hardware/audio/assets/sf2/",
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

        # ---- soundfont management ----
        self._soundfont_ids: List[int] = []
        self._soundfont_paths: List[str] = []
        self._current_sf_index: int = 0

        # 1) 如果有指定資料夾，先嘗試從資料夾載入所有 .sf2
        if soundfont_dir is not None:
            self._load_soundfonts_from_dir(soundfont_dir)

        # 2) 如果資料夾裡沒載到任何 sf2，就退回用單一檔案 soundfont_path
        if not self._soundfont_ids:
            self.add_soundfont(soundfont_path)

        # 套用目前的 SoundFont（index = 0）
        self._apply_current_soundfont()

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
    # SoundFont management
    # ------------------------------------------------------------------

    def _load_soundfonts_from_dir(self, directory: str) -> None:
        """
        掃描指定資料夾，把所有 .sf2 檔按檔名字母順序載入。
        """
        if not os.path.isdir(directory):
            print(f"[AudioEngine] soundfont_dir not found: {directory}")
            return

        try:
            entries = sorted(os.listdir(directory))
        except Exception as e:
            print(f"[AudioEngine] listdir failed for {directory}: {e}")
            return

        count = 0
        for name in entries:
            if not name.lower().endswith(".sf2"):
                continue
            path = os.path.join(directory, name)
            if not os.path.isfile(path):
                continue
            self.add_soundfont(path)
            count += 1

        print(f"[AudioEngine] Loaded {count} SoundFont(s) from dir: {directory}")

    def add_soundfont(self, path: str) -> None:
        """
        Load an extra SoundFont and register it in the rotation list.

        不會自動切換到新的 SoundFont，只是加入清單；
        之後呼叫 cycle_soundfont() 時才會輪到它。
        """
        try:
            sfid = self.fs.sfload(path)
        except Exception as e:
            print(f"[AudioEngine] add_soundfont failed: {path} ({e})")
            return

        self._soundfont_ids.append(sfid)
        self._soundfont_paths.append(path)

        # 如果這是第一個 soundfont，就設定為 current
        if len(self._soundfont_ids) == 1:
            self._current_sf_index = 0

        print(f"[AudioEngine] SoundFont added: {path} (id={sfid})")

    def _apply_current_soundfont(self) -> None:
        """
        Apply the currently selected SoundFont to both channels.
        """
        if not self._soundfont_ids:
            return

        sfid = self._soundfont_ids[self._current_sf_index]
        self.fs.program_select(self.piano_channel, sfid, 0, 0)
        self.fs.program_select(self.hit_channel, sfid, 0, 0)

        path = self._soundfont_paths[self._current_sf_index]
        print(f"[AudioEngine] Using SoundFont[{self._current_sf_index}]: {path}")

    def cycle_soundfont(self) -> None:
        """
        Cycle to the next loaded SoundFont (if more than one).

        綁定在長按 KEY_0（NEXT_SF2）事件。
        """
        if not self._soundfont_ids:
            print("[AudioEngine] cycle_soundfont(): no SoundFont loaded")
            return

        if len(self._soundfont_ids) == 1:
            # 只有一個：重新套用一次，避免沒有反應的錯覺
            self._apply_current_soundfont()
            print("[AudioEngine] cycle_soundfont(): only one SoundFont, re-applied")
            return

        self._current_sf_index = (self._current_sf_index + 1) % len(self._soundfont_ids)
        self._apply_current_soundfont()

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
