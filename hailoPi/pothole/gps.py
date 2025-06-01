import serial
import pynmea2

# Replace with your actual serial port
serial_port = '/dev/ttyUSB0'
baud_rate = 9600

try:
    with serial.Serial(serial_port, baud_rate, timeout=1) as ser:
        while True:
            line = ser.readline().decode('ascii', errors='replace').strip()
            if line.startswith('$GPGGA'):
                try:
                    msg = pynmea2.parse(line)
                    print(f"Time: {msg.timestamp}, Latitude: {msg.latitude}, Longitude: {msg.longitude}, Altitude: {msg.altitude} {msg.altitude_units}, Satellites: {msg.num_sats}")
                except pynmea2.ParseError as e:
                    print(f"Parse error: {e}")
except serial.SerialException as e:
    print(f"Serial error: {e}")

