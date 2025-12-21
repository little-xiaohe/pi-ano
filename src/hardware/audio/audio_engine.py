from __future__ import annotations

from typing import Dict, Optional, List
import os
import fluidsynth

from src.hardware.config.keys import KeyId


# --------------------------------------------------------------------------------------
# Per-SoundFont Volume Table (do not use set_gain, as older versions do not support it)
# Adjust MIDI Volume (0~127) based on file name.
# Gain cannot be set dynamically, but Volume 127 can compensate for differences.
# --------------------------------------------------------------------------------------
SOUNDFONT_VOLUME: Dict[str, int] = {
    "00_piano.sf2": 110,   # Piano is louder, so lower the volume a bit
    # "01_guitar.sf2": 127,  # Guitar is quieter, so set to max
}



class AudioEngine:
    """
    Audio engine using FluidSynth and SoundFont.

    - Channel 0: main piano
    - Channel 1: hit SFX
    - Supports multiple SoundFonts, can switch dynamically (long press KEY_0)
    """

    def __init__(
        self,
        soundfont_path: str = "/home/pi/pi-ano/src/hardware/audio/assets/sf2/00_piano.sf2",
        soundfont_dir: Optional[str] = "/home/pi/pi-ano/src/hardware/audio/assets/sf2/",
        sample_rate: int = 44100,
        default_velocity: int = 100,
        default_gain: float = 1.8,
    ) -> None:

        self.sample_rate = sample_rate
        self.default_velocity = default_velocity
        self.default_gain = default_gain


        # Create synth and start audio driver
        self.fs = fluidsynth.Synth(gain=self.default_gain, samplerate=sample_rate)
        # self.fs.start(driver="alsa")
        self.fs.start(
            driver="alsa",
            device="plughw:CARD=Device,DEV=0"
        )

        # Channel assignments
        self.piano_channel: int = 0
        self.hit_channel: int = 1

        # SoundFont management
        self._soundfont_ids: List[int] = []
        self._soundfont_paths: List[str] = []
        self._current_sf_index: int = 0

        # Try to load all sf2 files from directory
        if soundfont_dir is not None:
            self._load_soundfonts_from_dir(soundfont_dir)

        # If none loaded, fallback to single file
        if not self._soundfont_ids:
            self.add_soundfont(soundfont_path)

        # Apply the first SoundFont
        self._apply_current_soundfont()

        # KeyId to MIDI note mapping (C4 = 60)
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
    # SoundFont Management
    # ------------------------------------------------------------------

    def _load_soundfonts_from_dir(self, directory: str) -> None:
        """
        Load all SoundFont (.sf2) files from the specified directory.
        """
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
        """
        Add a SoundFont file to the engine.
        """
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
        Apply the current SoundFont and adjust CC7 volume for both channels.
        """
        sfid = self._soundfont_ids[self._current_sf_index]
        path = self._soundfont_paths[self._current_sf_index]
        basename = os.path.basename(path)

        # Set SoundFont instrument for both channels
        self.fs.program_select(self.piano_channel, sfid, 0, 0)
        self.fs.program_select(self.hit_channel, sfid, 0, 0)

        # Volume tuning via CC7 (MIDI volume controller)
        volume = SOUNDFONT_VOLUME.get(basename, 120)
        volume = max(0, min(127, int(volume)))

        self.fs.cc(self.piano_channel, 7, volume)
        self.fs.cc(self.hit_channel, 7, volume)

        print(f"[AudioEngine] Using SF[{self._current_sf_index}]: {basename} (vol={volume})")

    def cycle_soundfont(self) -> None:
        """
        Switch to the next SoundFont in the list.
        """
        if not self._soundfont_ids:
            print("[AudioEngine] No SoundFont loaded.")
            return

        self._current_sf_index = (self._current_sf_index + 1) % len(self._soundfont_ids)
        self._apply_current_soundfont()


    # ------------------------------------------------------------------
    # Helper Methods
    # ------------------------------------------------------------------


    @staticmethod
    def _vel01_to_127(v: float) -> int:
        """
        Convert a velocity value in the range [0.0, 1.0] to MIDI velocity [1, 127].
        """
        return max(1, min(127, int(max(0.0, min(1.0, v)) * 127)))


    # ------------------------------------------------------------------
    # KeyId API (for PianoMode)
    # ------------------------------------------------------------------
    def _key_to_midi_note(self, key: KeyId) -> Optional[int]:
        """
        Map a KeyId to a MIDI note number.
        """
        return self.key_to_midi.get(key)

    def note_on(self, key: KeyId, velocity: float = 1.0) -> None:
        """
        Trigger note on for a given KeyId.
        """
        midi_note = self._key_to_midi_note(key)
        if midi_note is not None:
            self.fs.noteon(self.piano_channel, midi_note, self._vel01_to_127(velocity))

    def note_off(self, key: KeyId) -> None:
        """
        Trigger note off for a given KeyId.
        """
        midi_note = self._key_to_midi_note(key)
        if midi_note is not None:
            self.fs.noteoff(self.piano_channel, midi_note)


    # ------------------------------------------------------------------
    # MIDI API (for SongMode / RhythmMode)
    # ------------------------------------------------------------------
    def note_on_midi(self, midi_note: int, velocity) -> None:
        """
        Trigger note on for a given MIDI note number.
        """
        self.fs.noteon(self.piano_channel, midi_note, self._vel01_to_127(velocity))

    def note_off_midi(self, midi_note: int) -> None:
        """
        Trigger note off for a given MIDI note number.
        """
        self.fs.noteoff(self.piano_channel, midi_note)


    # ------------------------------------------------------------------
    # Hit SFX
    # ------------------------------------------------------------------
    def play_hit_sfx(self, velocity: float = 1.0) -> None:
        """
        Play the hit sound effect (SFX) on the hit channel.
        """
        self.fs.noteon(self.hit_channel, self.hit_note, self._vel01_to_127(velocity))


    # ------------------------------------------------------------------
    # Stop & Cleanup
    # ------------------------------------------------------------------
    def stop_all(self) -> None:
        """
        Stop all notes on both channels.
        """
        for n in range(128):
            self.fs.noteoff(self.piano_channel, n)
            self.fs.noteoff(self.hit_channel, n)

    def close(self) -> None:
        """
        Stop all notes and clean up the synthesizer.
        """
        self.stop_all()
        self.fs.delete()
