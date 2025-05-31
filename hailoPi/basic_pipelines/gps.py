import serial
import time
from loguru import logger
# Open UART port
# --------------------------------------------
# Serial Reader Thread
# --------------------------------------------
def read_serial(latest_serial_data):
    logger.debug("[DEBUG] Serial reader thread starting")
    try:
        ser = serial.Serial("/dev/serial0", 9600, timeout=1)
        while True:
            line = ser.readline().decode('ascii', errors='ignore').strip()
            if line.startswith("$GPGGA") or line.startswith("$GPRMC"):
                latest_serial_data["raw"] = line
                parts = line.split(',')
                if line.startswith("$GPRMC") and parts[2] == 'A':
                    lat = float(parts[3][:2]) + float(parts[3][2:]) / 60.0
                    if parts[4] == 'S': lat = -lat
                    lon = float(parts[5][:3]) + float(parts[5][3:]) / 60.0
                    if parts[6] == 'W': lon = -lon
                    latest_serial_data.update({"lat": lat, "lon": lon})
                elif line.startswith("$GPGGA") and parts[6] != '0':
                    lat = float(parts[2][:2]) + float(parts[2][2:]) / 60.0
                    if parts[3] == 'S': lat = -lat
                    lon = float(parts[4][:3]) + float(parts[4][3:]) / 60.0
                    if parts[5] == 'W': lon = -lon
                    latest_serial_data.update({"lat": lat, "lon": lon})
    except Exception as e:
        logger.error(f"[ERROR] Serial thread error: {e}")
