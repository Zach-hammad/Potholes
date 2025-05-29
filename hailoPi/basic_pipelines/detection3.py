import gi
import os
import cv2
import hailo
import time
import json
import threading
import serial
import numpy as np
import datetime
from collections import deque
from gi.repository import Gst, GLib
import boto3

from hailo_apps_infra.hailo_rpi_common import (
    get_caps_from_pad,
    get_numpy_from_buffer,
    app_callback_class,
)
from hailo_apps_infra.detection_pipeline import GStreamerDetectionApp

# --------------------------------------------
# Configuration
# --------------------------------------------
gi.require_version('Gst', '1.0')
Gst.init(None)

# Tigris (S3-compatible) bucket config
S3_URL = os.getenv("S3_URL", "https://fly.storage.tigris.dev/")
TIGRIS_BUCKET_NAME = os.getenv("TIGRIS_BUCKET_NAME", "pothole-images")

# Initialize S3 client
s3_client = boto3.client(
    's3',
    endpoint_url=S3_URL,
    aws_access_key_id=os.getenv('S3_ACCESS_KEY'),
    aws_secret_access_key=os.getenv('S3_SECRET_KEY'),
)

# --------------------------------------------
# Global Serial Reader for GPS metadata
# --------------------------------------------
latest_serial_data = {"raw": "", "lat": None, "lon": None}

# --------------------------------------------
# Frame Buffer and Detection Tracker
# --------------------------------------------
FRAME_BUFFER = deque(maxlen=300)
FRAME_LOCK = threading.Lock()
RECORDING = False
LAST_DETECTION_TIME = 0
DETECTION_TIMEOUT = 3

# Base output directory
OUTPUT_BASE_DIR = "cached_clips"
os.makedirs(OUTPUT_BASE_DIR, exist_ok=True)

# --------------------------------------------
def read_serial():
    global latest_serial_data
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
                print(f"[DEBUG] Serial parsed: raw={latest_serial_data['raw']}, lat={latest_serial_data['lat']}, lon={latest_serial_data['lon']}")
    except Exception as e:
        print(f"[Serial Thread] Error: {e}")

# --------------------------------------------
def save_clip_and_metadata(frames_data):
    print("[DEBUG] save_clip_and_metadata() triggered")
    if not frames_data:
        print("[WARN] No frames to save, aborting")
        return

    date_str = datetime.date.today().isoformat()
    output_dir = os.path.join(OUTPUT_BASE_DIR, date_str)
    os.makedirs(output_dir, exist_ok=True)

    timestamp = int(time.time())
    video_name = f"pothole_{timestamp}.avi"
    json_name = f"pothole_{timestamp}.json"
    bestframe_name = f"pothole_{timestamp}_best.jpg"
    video_path = os.path.join(output_dir, video_name)
    metadata_path = os.path.join(output_dir, json_name)
    bestframe_path = os.path.join(output_dir, bestframe_name)

    h, w, _ = frames_data[0]['frame'].shape
    if not all(entry['frame'].shape == (h, w, 3) for entry in frames_data):
        print("[ERROR] Inconsistent frame sizes detected. Skipping video save.")
        return

    out = cv2.VideoWriter(video_path, cv2.VideoWriter_fourcc(*'XVID'), 30, (w, h))
    if not out.isOpened():
        print(f"[ERROR] VideoWriter failed to open for {video_path}")
        return
    for entry in frames_data:
        out.write(entry['frame'])
    out.release()
    print(f"[INFO] Saved video: {video_path}")

    best_idx, best_diff = None, float('inf')
    for i, entry in enumerate(frames_data):
        for yc in entry['y_centers']:
            diff = abs(yc - 0.5)
            if diff < best_diff:
                best_diff = diff
                best_idx = i
    if best_idx is not None:
        cv2.imwrite(bestframe_path, frames_data[best_idx]['frame'])
        print(f"[INFO] Saved best frame: {bestframe_path}")
    else:
        print("[WARN] No detections to select best frame")

    meta = {
        "timestamp": timestamp,
        "gps": {"lat": latest_serial_data['lat'], "lon": latest_serial_data['lon']},
    }
    with open(metadata_path, 'w') as fjson:
        json.dump(meta, fjson)
    print(f"[INFO] Saved metadata: {metadata_path}")

    for fname in [video_name, json_name, bestframe_name]:
        local = os.path.join(output_dir, fname)
        s3_key = f"{date_str}/{fname}"
        try:
            s3_client.upload_file(local, TIGRIS_BUCKET_NAME, s3_key)
            print(f"[INFO] Uploaded {fname} to S3://{TIGRIS_BUCKET_NAME}/{s3_key}")
        except Exception as e:
            print(f"[ERROR] Failed to upload {fname}: {e}")

# --------------------------------------------
class user_app_callback_class(app_callback_class):
    def __init__(self):
        super().__init__()
        self.use_frame = True

# --------------------------------------------
def app_callback(pad, info, user_data):
    global RECORDING, LAST_DETECTION_TIME
    buf = info.get_buffer()
    if buf is None:
        return Gst.PadProbeReturn.OK

    user_data.use_frame = True
    fmt, w, h = get_caps_from_pad(pad)
    frame = None
    if fmt and w and h:
        frame = get_numpy_from_buffer(buf, fmt, w, h)
        if frame is not None:
            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

    dets = hailo.get_roi_from_buffer(buf).get_objects_typed(hailo.HAILO_DETECTION)
    y_centers = []
    pothole = False
    if frame is not None:
        for det in dets:
            if det.get_class_id() == 1:
                pothole = True
            bbox = det.get_bbox()
            yc = (bbox.ymin() + bbox.ymax()) / 2.0
            y_centers.append(yc)
            x0, y0 = int(bbox.xmin() * w), int(bbox.ymin() * h)
            x1, y1 = int(bbox.xmax() * w), int(bbox.ymax() * h)
            cv2.rectangle(frame, (x0, y0), (x1, y1), (0, 255, 0), 2)
        lat, lon = latest_serial_data.get("lat"), latest_serial_data.get("lon")
        gps_text = f"Lat:{lat:.6f} Lon:{lon:.6f}" if lat and lon else "GPS unavailable"
        cv2.putText(frame, gps_text, (10, h - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1)

    safe_frame = np.copy(frame) if frame is not None else None

    with FRAME_LOCK:
        if pothole and safe_frame is not None:
            LAST_DETECTION_TIME = time.time()
            if not RECORDING:
                RECORDING = True
                print("[INFO] Recording started")
            FRAME_BUFFER.append({'frame': safe_frame, 'y_centers': y_centers})
        elif RECORDING:
            blank = np.zeros((h, w, 3), np.uint8)
            FRAME_BUFFER.append({'frame': safe_frame if safe_frame is not None else blank, 'y_centers': y_centers})

        if RECORDING and (time.time() - LAST_DETECTION_TIME > DETECTION_TIMEOUT):
            RECORDING = False
            clip = list(FRAME_BUFFER)
            FRAME_BUFFER.clear()
            threading.Thread(target=save_clip_and_metadata, args=(clip,), daemon=True).start()
            print("[INFO] Detection ended, saving clip")

    return Gst.PadProbeReturn.OK

# --------------------------------------------
if __name__ == "__main__":
    threading.Thread(target=read_serial, daemon=True).start()
    app = GStreamerDetectionApp(app_callback, user_app_callback_class())
    app.run()

