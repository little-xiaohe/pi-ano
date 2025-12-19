from __future__ import annotations

import signal
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


def main() -> None:
    """Main entry point for the Pi-ano application."""
    # ------------------------------------------------------------------
    # Hardware / engines
    # ------------------------------------------------------------------
    led = LedMatrix()
    audio = AudioEngine()

    # ------------------------------------------------------------------
    # Signal handling
    # ------------------------------------------------------------------
    # Treat SIGINT (Ctrl+C) / SIGTERM as KeyboardInterrupt so both paths
    # trigger the same cleanup logic.
    def handle_signal(signum, frame):
        print(f"\n[Main] Received signal {signum}, requesting shutdown...")
        raise KeyboardInterrupt()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    # ------------------------------------------------------------------
    # Pico serial display controller
    # ------------------------------------------------------------------
    pico_display = PicoModeDisplay(
        device="/dev/ttyACM0",  # Change to /dev/ttyACM1 if needed
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

    # Best-effort: tell Pico to show initial mode
    try:
        pico_display.show_mode("menu")
    except Exception as e:
        print("[Main] initial show_mode(menu) error:", e)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------
    try:
        while True:
            now = time.monotonic()
            current_mode = input_manager.current_mode_name

            # Collect input events for this frame
            events = poll_all_inputs(input_controller, current_mode)

            # Route events + update active mode
            input_manager.handle_events(events, now)
            input_manager.update(now)

            # Frame pacing
            if current_mode == "song":
                time.sleep(0.001)
            else:
                time.sleep(1.0 / 60.0)

    except KeyboardInterrupt:
        print("\n[Main] KeyboardInterrupt / termination signal: shutting down...")

    finally:
        # ------------------------------------------------------------------
        # Best-effort cleanup order:
        # 1) Ask Pico to clear its LEDs BEFORE closing serial.
        # 2) Clear local LEDs.
        # 3) Close audio.
        # 4) Close Pico serial.
        # ------------------------------------------------------------------

        # 1) Clear Pico-controlled LED panel (sends "LED:CLEAR")
        try:
            if hasattr(pico_display, "clear"):
                pico_display.clear()
                time.sleep(0.1)  # Give Pico time to consume the command
        except Exception:
            pass

        # 2) Clear local LED matrix (if any)
        try:
            led.clear_all()
            led.show()
        except Exception:
            pass

        # 3) Stop/close audio engine
        try:
            audio.close()
        except Exception:
            pass

        # 4) Close Pico serial connection
        try:
            if hasattr(pico_display, "close"):
                pico_display.close()
        except Exception:
            pass

        print("[Main] Cleanup done. Bye.")


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
    print("    - Used as hit buttons in rhythm mode")
    print("  Long press D14 (KEY_4)")
    print("    - Cycle through modes: menu → piano → rhythm → song")
    print("  Long press D25 (KEY_1)")
    print("    - Cycle through loaded SoundFonts (if multiple are loaded)")
    print()
    print("Press Ctrl+C in the terminal to quit.\n")


def poll_all_inputs(input_controller: InputController, current_mode: str):
    """
    Poll all input sources and return a flat list of InputEvent objects.

    Rules:
      - Keyboard is always active (mode switching, 'next', debug notes).
      - Buttons are always polled, but we may filter events depending on mode:
          * In piano mode, only keep control events (mode switching, next sf2),
            and ignore NOTE_ON / NOTE_OFF events.
          * In other modes (e.g., rhythm), button NOTE events are kept.
      - IR is only used in piano mode.
    """
    events = []

    # Keyboard: always active
    if input_controller.keyboard is not None:
        events.extend(input_controller.keyboard.poll())

    # Buttons: always polled, but filter depending on mode
    if input_controller.buttons is not None:
        btn_events = input_controller.buttons.poll()

        if current_mode == "piano":
            btn_events = [
                e
                for e in btn_events
                if e.type in (EventType.NEXT_MODE, EventType.MODE_SWITCH, EventType.NEXT_SF2)
            ]

        events.extend(btn_events)

    # IR: only used in piano mode
    if current_mode == "piano" and input_controller.ir is not None:
        events.extend(input_controller.ir.poll())

    return events


if __name__ == "__main__":
    main()
