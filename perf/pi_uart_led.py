import serial
import time

uart = serial.Serial("/dev/ttyAMA3", 115200, timeout=1)

commands = ["RED\n", "GREEN\n", "BLUE\n", "OFF\n"]

for cmd in commands:
    print("Send:", cmd.strip())
    uart.write(cmd.encode())
    time.sleep(1)
