import time
from dataclasses import dataclass
from typing import List

import board
import digitalio

from src.logic.input_event import InputEvent, EventType
from src.hardware.config.keys import KeyId
from src.logic.input_config import LONG_PRESS


@dataclass
class ButtonChannel:
    """
    Represents one physical button wired to a specific KeyId.

    Attributes:
        key: Logical key ID (KEY_0..KEY_4).
        pin: DigitalInOut object for the GPIO pin.
        last_value: Last sampled pin value (True = released, False = pressed).
        press_time: Timestamp (monotonic seconds) when the button was pressed, or None if released.
        long_sent: Whether a long-press event (NEXT_MODE / NEXT_SF2) has already been sent for this press.
    """
    key: KeyId
    pin: digitalio.DigitalInOut
    last_value: bool          # True = released (pull-up), False = pressed
    press_time: float | None  # time.monotonic() when press started
    long_sent: bool           # True if long-press event already sent


class ButtonInput:
    """
    Polls physical GPIO buttons and converts them into InputEvent objects.

    Wiring (using pull-up inputs, active LOW):
        KEY_0 → D25
        KEY_1 → D24 (long-press for "next soundfont")
        KEY_2 → D18
        KEY_3 → D15
        KEY_4 → D14  (long-press for "next mode")

    Behavior:
        - Short press:
            - On press edge (HIGH → LOW): emit NOTE_ON
            - On release edge (LOW → HIGH): emit NOTE_OFF
        - Long press on KEY_4 (D14):
            - If held for at least LONG_PRESS_NEXT_MODE_SEC: emit EventType.NEXT_MODE (once per press)
        - Long press on KEY_1 (D25):
            - If held for at least LONG_PRESS_NEXT_SF2_SEC: emit EventType.NEXT_SF2 (once per press)

    Note:
        The mapping from NOTE_ON / NOTE_OFF to actual behavior is handled at a higher level (InputManager + mode logic).
        For example, in piano mode you can filter out NOTE events from source="button" so that buttons only switch modes or trigger NEXT_SF2.
    """

    def __init__(self, debug: bool = True) -> None:
        self.debug = debug


        # Mapping from KeyId to physical GPIO pins
        key_pin_pairs = [
            (KeyId.KEY_0, board.D25),
            (KeyId.KEY_1, board.D24),
            (KeyId.KEY_2, board.D18),
            (KeyId.KEY_3, board.D15),
            (KeyId.KEY_4, board.D14),
        ]

        self.channels: List[ButtonChannel] = []

        for key, pin_obj in key_pin_pairs:
            dio = digitalio.DigitalInOut(pin_obj)
            dio.direction = digitalio.Direction.INPUT
            # Use internal pull-up; button press pulls the line LOW
            dio.pull = digitalio.Pull.UP

            channel = ButtonChannel(
                key=key,
                pin=dio,
                last_value=True,      # assume "released" (HIGH) at startup
                press_time=None,
                long_sent=False,
            )
            self.channels.append(channel)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def poll(self) -> List[InputEvent]:
        """
        Scan all buttons once and produce a list of InputEvent objects.

        For each button:
          - Edge: HIGH → LOW  (released → pressed): emit NOTE_ON
          - While pressed:
                If key == KEY_4 and held for ≥ LONG_PRESS_NEXT_MODE_SEC and NEXT_MODE not yet sent: emit NEXT_MODE once
                If key == KEY_1 and held for ≥ LONG_PRESS_NEXT_SF2_SEC and NEXT_SF2 not yet sent: emit NEXT_SF2 once
          - Edge: LOW → HIGH  (pressed → released): emit NOTE_OFF
        """
        events: List[InputEvent] = []
        now = time.monotonic()

        for ch in self.channels:
            current = ch.pin.value  # True = released, False = pressed

            # ----------------------------------------------------------
            # Edge: HIGH → LOW = button just pressed
            # ----------------------------------------------------------
            if ch.last_value and (not current):
                ch.press_time = now
                ch.long_sent = False

                # Immediately emit NOTE_ON (used as "hit" in rhythm mode)
                events.append(
                    InputEvent(
                        type=EventType.NOTE_ON,
                        key=ch.key,
                        velocity=1.0,
                        source="button",
                    )
                )
                if self.debug:
                    print(f"[BTN] NOTE_ON key={int(ch.key)}")

            # ----------------------------------------------------------
            # While pressed: check long press (data-driven)
            # ----------------------------------------------------------
            if (not current) and ch.press_time is not None and (not ch.long_sent):
                duration = now - ch.press_time

                # Is this key configured for long-press?
                threshold = LONG_PRESS.get(ch.key)
                if threshold is not None and duration >= threshold:

                    # Map key → action
                    if ch.key == KeyId.KEY_0:
                        ev_type = EventType.SHUTDOWN
                        debug_msg = "SHUTDOWN"
                    elif ch.key == KeyId.KEY_4:
                        ev_type = EventType.NEXT_MODE
                        debug_msg = "NEXT_MODE"
                    elif ch.key == KeyId.KEY_1:
                        ev_type = EventType.NEXT_SF2
                        debug_msg = "NEXT_SF2"
                    else:
                        ev_type = None

                    if ev_type is not None:
                        events.append(
                            InputEvent(
                                type=ev_type,
                                source="button",
                            )
                        )
                        ch.long_sent = True
                        if self.debug:
                            print(f"[BTN] LONG PRESS on {ch.key.name} → {debug_msg}")
            # ----------------------------------------------------------
            # Edge: LOW → HIGH = button just released
            # ----------------------------------------------------------
            if (not ch.last_value) and current:
                # Emit NOTE_OFF on release
                events.append(
                    InputEvent(
                        type=EventType.NOTE_OFF,
                        key=ch.key,
                        velocity=1.0,
                        source="button",
                    )
                )
                if self.debug:
                    print(f"[BTN] NOTE_OFF key={int(ch.key)}")

                # Reset press tracking state
                ch.press_time = None
                ch.long_sent = False

            # Update last_value for next poll
            ch.last_value = current

        return events
