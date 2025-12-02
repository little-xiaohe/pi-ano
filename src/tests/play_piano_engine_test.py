# play_piano_engine_test.py
# Quick test for AudioEngine with KeyId → C4~G4

import time

from src.hardware.audio.audio_engine import AudioEngine
from src.hardware.config.keys import KeyId


def main():
    engine = AudioEngine()

    try:
        scale = [
            KeyId.KEY_0,
            KeyId.KEY_1,
            KeyId.KEY_2,
            KeyId.KEY_3,
            KeyId.KEY_4,
        ]

        print("Playing C4 D4 E4 F4 G4 via AudioEngine ...")
        for key in scale:
            print(f"NOTE_ON key={key}")
            engine.note_on(key, velocity=0.9)
            time.sleep(0.4)
            engine.note_off(key)
            time.sleep(0.05)

        print("Done.")
    finally:
        print("Cleaning up AudioEngine ...")
        engine.close()


if __name__ == "__main__":
    main()
