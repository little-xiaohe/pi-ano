# play_scale.py
# Play notes C D E F G on Raspberry Pi speaker using simpleaudio

import time

import numpy as np
import simpleaudio as sa

SAMPLE_RATE = 44100  # Hz

# Middle C (C4) ~ G4
NOTE_FREQS = {
    "C4": 261.63,
    "D4": 293.66,
    "E4": 329.63,
    "F4": 349.23,
    "G4": 392.00,
}


def generate_tone(freq: float, duration: float, volume: float = 0.1) -> np.ndarray:
    """
    Generate a sine wave tone.

    freq: frequency in Hz
    duration: seconds
    volume: 0.0 ~ 1.0
    """
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), False)
    tone = np.sin(freq * t * 2 * np.pi)

    # scale to 16-bit PCM
    audio = tone * (2**15 - 1) * volume
    audio = audio.astype(np.int16)
    return audio


def play_tone(freq: float, duration: float = 0.4, volume: float = 0.3) -> None:
    audio = generate_tone(freq, duration, volume)
    play_obj = sa.play_buffer(audio, num_channels=1, bytes_per_sample=2, sample_rate=SAMPLE_RATE)
    play_obj.wait_done()  # block until sound finishes


def main():
    # C D E F G
    scale = ["C4", "D4", "E4", "F4", "G4"]

    print("Playing C D E F G ...")
    for note in scale:
        freq = NOTE_FREQS[note]
        print(f"Note {note} ({freq:.2f} Hz)")
        play_tone(freq, duration=0.4, volume=0.3)
        time.sleep(0.05)  # small gap between notes

    print("Done.")


if __name__ == "__main__":
    main()
