# src/hardware/input/keyboard_input.py

import sys
import select
from typing import List

from src.hardware.config.keys import KeyId
from src.logic.input_event import InputEvent, EventType


class KeyboardInput:
    """
    Reads commands from stdin (non-blocking) and converts them into InputEvent objects.

    This is mainly a development / debugging input source so you can
    control modes and trigger keys from a terminal.

    Supported commands (case-insensitive):

        on <key> [velocity]
            - Emit NOTE_ON for the given key index.
            - <key>: integer index that maps to KeyId
            - [velocity]: optional float, default = 1.0

        off <key>
            - Emit NOTE_OFF for the given key index.

        mode menu
        mode piano
        mode rhythm
        mode song
            - Emit MODE_SWITCH to the given mode name.

        next
            - Emit NEXT_SONG (typically handled only in song mode).

    Notes:
        - poll() is non-blocking: if there is no line in stdin, it returns [].
        - All events produced from here have source="keyboard" (via InputEvent).
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def poll(self) -> List[InputEvent]:
        """
        Check stdin once (non-blocking) and return a list of InputEvent(s)
        based on a single line of input, if any.

        If there is no pending input, returns an empty list.
        """
        events: List[InputEvent] = []

        # Non-blocking check: is there anything ready to read on stdin?
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

            if mode_name in ("menu", "piano", "rhythm", "song"):
                events.append(
                    InputEvent(
                        type=EventType.MODE_SWITCH,
                        mode_name=mode_name,
                        source="keyboard",
                    )
                )
                print(f"[KB] MODE_SWITCH → {mode_name}")
            else:
                print(
                    "Unknown mode. Use: "
                    "mode menu | mode piano | mode rhythm | mode song"
                )
            return events

        # -------------------------
        # NEXT SONG (only meaningful in song mode)
        # -------------------------
        if cmd == "next":
            events.append(
                InputEvent(
                    type=EventType.NEXT_SONG,
                    source="keyboard",
                )
            )
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
                    source="keyboard",
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
                    source="keyboard",
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
        print("  mode menu | mode piano | mode rhythm | mode song")
        print("  next        (in song mode: skip to next song)")
        return events
