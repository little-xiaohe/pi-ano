# src/app/main.py

import time

from src.hardware.led.led_matrix import LedMatrix
from src.hardware.audio.audio_engine import AudioEngine

from src.logic.input_controller import InputController
from src.logic.input_manager import InputManager

from src.logic.modes.chiikawa_mode import ChiikawaMode
from src.logic.modes.piano_mode import PianoMode
from src.logic.modes.rhythm_mode import RhythmMode
from src.logic.modes.midi_song_mode import MidiSongMode


def main() -> None:
    # --- hardware / engine ---
    led = LedMatrix()
    audio = AudioEngine()

    # --- modes ---
    chiikawa = ChiikawaMode(led)
    piano = PianoMode(led, audio=audio)
    rhythm = RhythmMode(led, audio=audio)
    song = MidiSongMode(led, audio=audio, loop_playlist=True)

    # --- input devices ---
    input_controller = InputController(
        use_keyboard=True,
        use_buttons=True,
        use_ir=False,
    )

    input_manager = InputManager(
        chiikawa=chiikawa,
        piano=piano,
        rhythm=rhythm,
        song=song,
    )

    print("=== Pi-Ano Started (Chiikawa menu default) ===")
    print("Keyboard commands:")
    print("  mode chiikawa")
    print("  mode piano")
    print("  mode rhythm")
    print("  mode song")
    print("  next            (song mode: 下一首)")
    print("  on <key> [vel]  (debug 用)")
    print("  off <key>")
    print()
    print("Buttons:")
    print("  KEY_0~KEY_4 (D25, D24, D18, D15, D14) → rhythm mode 的 hit")
    print("  長按 D14 (KEY_4) → 在任何 mode 切到下一個 mode")
    print("Ctrl+C to quit\n")

    try:
        while True:
            now = time.monotonic()
            mode = input_manager.current_mode

            events = []

            # keyboard：任何 mode 都有用（切 mode / next / debug）
            if input_controller.keyboard is not None:
                events.extend(input_controller.keyboard.poll())

            # buttons：任何 mode 都會 poll（rhythm 當 hit，用 D14 長按切 mode）
            if input_controller.buttons is not None:
                events.extend(input_controller.buttons.poll())

            # IR：只在 piano mode 使用
            if mode == "piano":
                if input_controller.ir is not None:
                    events.extend(input_controller.ir.poll())
            # rhythm / song / chiikawa 不用 IR

            # 處理事件 + 更新當前 mode
            input_manager.handle_events(events, now)
            input_manager.update(now)

            # song mode：loop 細一點讓 MIDI scheduler 比較穩
            if mode == "song":
                time.sleep(0.001)
            else:
                time.sleep(1.0 / 60.0)

    except KeyboardInterrupt:
        print("\nStopping, clearing LEDs...")
    finally:
        led.clear_all()
        led.show()
        audio.close()


if __name__ == "__main__":
    main()
