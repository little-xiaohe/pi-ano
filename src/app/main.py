# src/app/main.py

import time

from src.hardware.led.led_matrix import LedMatrix
from src.hardware.audio.audio_engine import AudioEngine
from src.hardware.pico.pico_mode_display import PicoModeDisplay

from src.logic.input_controller import InputController
from src.logic.input_manager import InputManager
from src.logic.input_event import EventType

from src.logic.modes.menu_mode import MenuMode
from src.logic.modes.piano_mode import PianoMode
from src.logic.modes.rhythm_mode import RhythmMode
from src.logic.modes.midi_song_mode import MidiSongMode


def print_startup_help() -> None:
    """Print a quick reference for keyboard and button controls."""
    print("=== Pi-ano Started (default mode: menu) ===\n")

    print("Keyboard commands:")
    print("  mode menu")
    print("  mode piano")
    print("  mode rhythm")
    print("  mode song")
    print("  next            (in song mode: skip to next track)")
    print("  on <key> [vel]  (debug note-on)")
    print("  off <key>       (debug note-off)")
    print()

    print("Buttons:")
    print("  KEY_0 ~ KEY_4 (D25, D24, D18, D15, D14)")
    print("    → used as hit buttons in rhythm mode")
    print("  Long press D14 (KEY_4)")
    print("    → cycle through modes: menu → piano → rhythm → song")
    print()
    print("Press Ctrl+C in the terminal to quit.\n")


def poll_all_inputs(input_controller: InputController, current_mode: str):
    """
    Poll all input sources and return a flat list of InputEvent objects.

    Rules:
      - Keyboard is always active (mode switching, 'next', debug notes).
      - Buttons are always active, BUT:
          * In piano mode, buttons are used *only* for mode switching
            (e.g., NEXT_MODE), and their NOTE_ON / NOTE_OFF events are ignored.
          * In other modes (e.g., rhythm), button NOTE events are kept.
      - IR is only used in piano mode.
    """
    events = []

    # Keyboard: always active
    if input_controller.keyboard is not None:
        events.extend(input_controller.keyboard.poll())

    # Buttons: always polled, but we may filter events depending on mode
    if input_controller.buttons is not None:
        btn_events = input_controller.buttons.poll()

        if current_mode == "piano":
            # In piano mode we only keep "mode control" style events,
            # and drop NOTE_ON / NOTE_OFF from buttons so they do not
            # trigger PianoMode or AudioEngine.
            btn_events = [
                e
                for e in btn_events
                if e.type in (EventType.NEXT_MODE, EventType.MODE_SWITCH)
            ]

        events.extend(btn_events)

    # IR: only used in piano mode
    if current_mode == "piano" and input_controller.ir is not None:
        events.extend(input_controller.ir.poll())

    return events


def main() -> None:
    # ------------------------------------------------------------------
    # Hardware / engines
    # ------------------------------------------------------------------
    led = LedMatrix()
    audio = AudioEngine()

    # Pico2 HUB75 顯示器（menu / piano / rhythm / song + rhythm 專用指令）
    pico_display = PicoModeDisplay(
        device="/dev/ttyACM0",   # 如果實際是 /dev/ttyACM1 自己改
        baudrate=115200,
        enabled=True,
    )

    # ------------------------------------------------------------------
    # Mode objects
    # ------------------------------------------------------------------
    menu = MenuMode(led)
    piano = PianoMode(led, audio=audio)
    rhythm = RhythmMode(led, audio=audio, debug=False)
    song = MidiSongMode(led, audio=audio, loop_playlist=True, debug=False)

    # ------------------------------------------------------------------
    # Input sources + central manager
    # ------------------------------------------------------------------
    input_controller = InputController(
        use_keyboard=True,
        use_buttons=True,
        use_ir=True,
    )

    input_manager = InputManager(
        menu=menu,
        piano=piano,
        rhythm=rhythm,
        song=song,
        pico_display=pico_display,
    )

    print_startup_help()

    try:
        pico_display.show_mode("menu")
    except Exception as e:
        print("[Main] initial show_mode(menu) error:", e)

    try:
        while True:
            now = time.monotonic()
            # 用 InputManager 封裝好的 property，比直接碰 attribute 安全
            current_mode = input_manager.current_mode_name

            # 1) Collect all input events for this frame
            events = poll_all_inputs(input_controller, current_mode)

            # 2) Let InputManager route events and update the active mode
            input_manager.handle_events(events, now)
            input_manager.update(now)

            # 3) Frame pacing
            #
            # Song mode runs slightly tighter to keep MIDI scheduling smooth.
            if current_mode == "song":
                time.sleep(0.001)
            else:
                # ~60 FPS for other modes
                time.sleep(1.0 / 60.0)

    except KeyboardInterrupt:
        print("\n[Main] KeyboardInterrupt: shutting down...")
    finally:
        # Best-effort cleanup: stop audio, clear LEDs, close Pico serial.
        try:
            led.clear_all()
            led.show()
        except Exception:
            pass

        try:
            audio.close()
        except Exception:
            pass

        # 有些版本的 PicoModeDisplay 可能沒有 close()，加個防呆
        try:
            if hasattr(pico_display, "close"):
                pico_display.close()
        except Exception:
            pass

        print("[Main] Cleanup done. Bye.")


if __name__ == "__main__":
    main()

