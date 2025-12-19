from src.hardware.config.keys import KeyId

# ------------------------------------------------------------------
# Long-press thresholds (seconds)
# ------------------------------------------------------------------

LONG_PRESS_SHUTDOWN_SEC  = 2.0   # KEY_0
LONG_PRESS_NEXT_SF2_SEC  = 1.0   # KEY_1
LONG_PRESS_NEXT_MODE_SEC = 1.0   # KEY_4

# Mapping: which keys support long-press + their thresholds
LONG_PRESS = {
    KeyId.KEY_0: LONG_PRESS_SHUTDOWN_SEC,
    KeyId.KEY_1: LONG_PRESS_NEXT_SF2_SEC,
    KeyId.KEY_4: LONG_PRESS_NEXT_MODE_SEC,
}
