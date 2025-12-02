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
    rhythm = RhythmMode(led)
    song = MidiSongMode(led, audio=audio, loop_playlist=True)

    # --- input devices ---
    # IR 在 song mode 會暫時停用（下面 main loop 會控制）
    input_controller = InputController(
        use_keyboard=True,
        use_buttons=True,
        use_ir=True,
    )

    input_manager = InputManager(
        chiikawa=chiikawa,
        piano=piano,
        rhythm=rhythm,
        song=song,
    )

    print("=== Pi-Ano Started (Chiikawa menu default) ===")
    print("Commands:")
    print("  mode chiikawa")
    print("  mode piano")
    print("  mode rhythm")
    print("  mode song")
    print("  on <key> [vel]   (piano / rhythm 測試用)")
    print("  off <key>")
    print("Ctrl+C to quit\n")

    try:
        while True:
            now = time.monotonic()

            # --- 根據目前 mode，決定要不要 poll IR ---
            if input_manager.current_mode == "song":
                # 播歌的時候：只讀 keyboard，避免 IR + I2C 拖慢節奏
                if input_controller.keyboard is not None:
                    events = input_controller.keyboard.poll()
                else:
                    events = []
            else:
                # 其他模式：照原本方式 poll 全部 input
                events = input_controller.poll()

            # 處理事件（mode switch + NOTE_ON/OFF）
            input_manager.handle_events(events, now)

            # 更新現在的 mode（chiikawa / piano / rhythm / song）
            input_manager.update(now)

            # --- sleep 時間也稍微區分一下 ---
            if input_manager.current_mode == "song":
                # 播歌時：loop 細一點，讓 note 觸發更準
                time.sleep(0.001)  # 大約 200 FPS
            else:
                # 一般狀況維持 60 FPS 左右
                time.sleep(1.0 / 60.0)

    except KeyboardInterrupt:
        print("\nStopping, clearing LEDs...")
    finally:
        led.clear_all()
        led.show()
        audio.close()


if __name__ == "__main__":
    main()
