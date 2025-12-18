# src/logic/input_controller.py

from typing import List, Optional

from src.logic.input_event import InputEvent
from src.hardware.input.keyboard_input import KeyboardInput
from src.hardware.input.button_input import ButtonInput
from src.hardware.input.ir_input import IRInput



class InputController:
    """
    Aggregates input events from all input devices (keyboard, buttons, IR).
    Provides a unified poll() method to collect all input events.
    """

    def __init__(
        self,
        use_keyboard: bool = True,
        use_buttons: bool = False,
        use_ir: bool = False,
    ) -> None:
        """
        Initialize input devices based on flags.
        """
        self.keyboard: Optional[KeyboardInput] = KeyboardInput() if use_keyboard else None
        self.buttons: Optional[ButtonInput] = ButtonInput(debug=False) if use_buttons else None
        self.ir: Optional[IRInput] = IRInput(debug=False) if use_ir else None

    def poll(self) -> List[InputEvent]:
        """
        Poll all enabled input devices and aggregate their events into a single list.
        Returns:
            List[InputEvent]: All input events from enabled devices.
        """
        events: List[InputEvent] = []

        if self.keyboard is not None:
            events.extend(self.keyboard.poll())

        if self.buttons is not None:
            events.extend(self.buttons.poll())

        if self.ir is not None:
            events.extend(self.ir.poll())

        return events
