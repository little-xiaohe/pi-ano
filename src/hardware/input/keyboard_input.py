# src/hardware/input/keyboard_input.py

import sys
import select
from typing import List

from src.hardware.config.keys import KeyId
from src.logic.input_event import InputEvent, EventType


class KeyboardInput:
    """
    Reads commands from stdin (non-blocking) and produces InputEvent objects.

    Supported commands:
      on <key> [velocity]     → NOTE_ON event
      off <key>               → NOTE_OFF event
      mode chiikawa           → MODE_SWITCH to chiikawa menu
      mode piano              → MODE_SWITCH to piano mode
      mode rhythm             → MODE_SWITCH to rhythm mode
      mode song               → MODE_SWITCH to MIDI song mode
      next                    → in song mode: skip to next song
    """

    def poll(self) -> List[InputEvent]:
        events: List[InputEvent] = []

        # non-blocking check: is there anything to read from stdin?
        ready, _, _ = select.select([sys.stdin], [], [], 0.0)
        if not ready:
            return events

        line = sys.stdin.readline()
        if not line:
            return events

        line = line.strip()
        if not line:
            return events

        parts = line.split()
        cmd = parts[0].lower()

        # -------------------------
        # MODE SWITCH
        # -------------------------
        if cmd == "mode" and len(parts) >= 2:
            mode_name = parts[1].lower()

            if mode_name in ("chiikawa", "piano", "rhythm", "song"):
                events.append(
                    InputEvent(
                        type=EventType.MODE_SWITCH,
                        mode_name=mode_name,
                    )
                )
                print(f"[KB] MODE_SWITCH -> {mode_name}")
            else:
                print("Unknown mode, use: mode chiikawa | mode piano | mode rhythm | mode song")

            return events

        # -------------------------
        # NEXT SONG (only meaningful in song mode)
        # -------------------------
        if cmd == "next":
            events.append(InputEvent(type=EventType.NEXT_SONG))
            print("[KB] NEXT_SONG requested")
            return events

        # -------------------------
        # NOTE ON
        # -------------------------
        if cmd == "on" and len(parts) >= 2:
            try:
                key_idx = int(parts[1])
                key = KeyId(key_idx)
            except Exception:
                print("Invalid key index for 'on'. Must match your KeyId range.")
                return events

            velocity = 1.0
            if len(parts) == 3:
                try:
                    velocity = float(parts[2])
                except ValueError:
                    print("Invalid velocity, using 1.0")

            events.append(
                InputEvent(
                    type=EventType.NOTE_ON,
                    key=key,
                    velocity=velocity,
                )
            )
            print(f"[KB] NOTE_ON key={key} vel={velocity}")
            return events

        # -------------------------
        # NOTE OFF
        # -------------------------
        if cmd == "off" and len(parts) >= 2:
            try:
                key_idx = int(parts[1])
                key = KeyId(key_idx)
            except Exception:
                print("Invalid key index for 'off'. Must match your KeyId range.")
                return events

            events.append(
                InputEvent(
                    type=EventType.NOTE_OFF,
                    key=key,
                )
            )
            print(f"[KB] NOTE_OFF key={key}")
            return events

        # -------------------------
        # Unknown command
        # -------------------------
        print("Unknown command. Use:")
        print("  on <key> [vel]")
        print("  off <key>")
        print("  mode chiikawa | mode piano | mode rhythm | mode song")
        print("  next   (in song mode: skip to next song)")
        return events
