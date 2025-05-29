#!/usr/bin/env python3
import gi
gi.require_version("Gst", "1.22")
from gi.repository import Gst

# --------------------------------------------
# Monkey-patch GStreamer: replace any video sink with fakesink
# --------------------------------------------
_orig_make = Gst.ElementFactory.make
def _fake_make(factory_name, name):
    # intercept all attempts to create a display sink
    if factory_name in ("autovideosink", "kmssink", "ximagesink"):
        return _orig_make("fakesink", name + "_headless")
    return _orig_make(factory_name, name)
Gst.ElementFactory.make = _fake_make

# --------------------------------------------
# Now import the rest of your stack
# --------------------------------------------
import os
import cv2
import hailo
import time
import json
import threading
import serial
import numpy as np
import datetime
import boto3

from collections import deque
from hailo_apps_infra.hailo_rpi_common import (
    get_caps_from_pad,
    get_numpy_from_buffer,
    app_callback_class,
)
from hailo_apps_infra.detection_pipeline import GStreamerDetectionApp

# --------------------------------------------
# Configuration & Initialization
# --------------------------------------------
Gst.init(None)

S3_URL            = os.getenv("S3_URL", "https://fly.storage.tigris.dev/")
TIGRIS_BUCKET     = os.getenv("TIGRIS_BUCKET_NAME", "pothole-images")
s3_client = boto3.client(
    's3',
    endpoint_url=S3_URL,
    aws_access_key_id=os.getenv('S3_ACCESS_KEY'),
    aws_secret_access_key=os.getenv('S3_SECRET_KEY'),
)

latest_serial_data = {"raw": "", "lat": None, "lon": None}
FRAME_BUFFER       = deque(maxlen=300)
RECORDING          = False
LAST_DETECTION_TIME= 0
DETECTION_TIMEOUT  = 3
OUTPUT_BASE_DIR    = "cached_clips"
os.makedirs(OUTPUT_BASE_DIR, exist_ok=True)

# --------------------------------------------
# GPS serial reader
# --------------------------------------------
def read_serial():
    global latest_serial_data
    try:
        ser = serial.Serial("/dev/serial0", 9600, timeout=1)
        while True:
            line = ser.readline().decode('ascii', errors='ignore').strip()
            if line.startswith("$GPGGA") or line.startswith("$GPRMC"):
                parts = line.split(',')
                latest_serial_data["raw"] = line
                # parse lat/lon
                if line.startswith("$GPRMC") and parts[2] == 'A':
                    lat = float(parts[3][:2]) + float(parts[3][2:]) / 60.0
                    if parts[4] == 'S': lat = -lat
                    lon = float(parts[5][:3]) + float(parts[5][3:]) / 60.0
                    if parts[6] == 'W': lon = -lon
                elif line.startswith("$GPGGA") and parts[6] != '0':
                    lat = float(parts[2][:2]) + float(parts[2][2:]) / 60.0
                    if parts[3] == 'S': lat = -lat
                    lon = float(parts[4][:3]) + float(parts[4][3:]) / 60.0
                    if parts[5] == 'W': lon = -lon
                else:
                    continue
                latest_serial_data.update({"lat": lat, "lon": lon})
                print(f"[DEBUG] GPS → lat={lat:.6f}, lon={lon:.6f}")
    except Exception as e:
        print(f"[Serial Thread] Error: {e}")

# --------------------------------------------
# Clip saving + S3 upload
# --------------------------------------------
def save_clip_and_metadata(frames_data):
    print("[DEBUG] save_clip_and_metadata()")
    if not frames_data:
        return

    date_str = datetime.date.today().isoformat()
    out_dir  = os.path.join(OUTPUT_BASE_DIR, date_str)
    os.makedirs(out_dir, exist_ok=True)

    ts = int(time.time())
    video_fp     = os.path.join(out_dir, f"pothole_{ts}.avi")
    bestframe_fp = os.path.join(out_dir, f"pothole_{ts}_best.jpg")
    meta_fp      = os.path.join(out_dir, f"pothole_{ts}.json")

    # write video
    h, w, _ = frames_data[0]['frame'].shape
    writer = cv2.VideoWriter(video_fp, cv2.VideoWriter_fourcc(*'XVID'), 30, (w, h))
    if writer.isOpened():
        for e in frames_data:
            writer.write(e['frame'])
        writer.release()
        print(f"[INFO] Video → {video_fp}")
    else:
        print(f"[ERROR] VideoWriter failed for {video_fp}")
        return

    # pick best frame (closest bbox-center to mid-height)
    best_idx, best_diff = None, float('inf')
    for i, e in enumerate(frames_data):
        for yc in e['y_centers']:
            d = abs(yc - 0.5)
            if d < best_diff:
                best_diff, best_idx = d, i
    if best_idx is not None:
        cv2.imwrite(bestframe_fp, frames_data[best_idx]['frame'])
        print(f"[INFO] Best frame → {bestframe_fp}")

    # write metadata
    meta = {
        "timestamp": ts,
        "gps": {"lat": latest_serial_data['lat'], "lon": latest_serial_data['lon']}
    }
    with open(meta_fp, 'w') as f:
        json.dump(meta, f)
    print(f"[INFO] Metadata → {meta_fp}")

    # upload
    for fp in (video_fp, bestframe_fp, meta_fp):
        key = f"{date_str}/{os.path.basename(fp)}"
        try:
            s3_client.upload_file(fp, TIGRIS_BUCKET, key)
            print(f"[INFO] Uploaded to {TIGRIS_BUCKET}/{key}")
        except Exception as e:
            print(f"[ERROR] Upload failed: {e}")

# --------------------------------------------
# GStreamer callback & helper class
# --------------------------------------------
class UserAppCallback(app_callback_class):
    def __init__(self):
        super().__init__()
        self.use_frame = True

def app_callback(pad, info, user_data):
    global RECORDING, LAST_DETECTION_TIME, FRAME_BUFFER
    buf = info.get_buffer()
    if not buf:
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
            x0, y0 = int(bbox.xmin()*w), int(bbox.ymin()*h)
            x1, y1 = int(bbox.xmax()*w), int(bbox.ymax()*h)
            cv2.rectangle(frame, (x0, y0), (x1, y1), (0,255,0), 2)
        lat, lon = latest_serial_data.get("lat"), latest_serial_data.get("lon")
        txt = f"Lat:{lat:.6f} Lon:{lon:.6f}" if lat and lon else "GPS unavailable"
        cv2.putText(frame, txt, (10, h-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,255,0), 1)

    # buffering logic
    if pothole and frame is not None:
        LAST_DETECTION_TIME = time.time()
        if not RECORDING:
            RECORDING = True
            print("[INFO] Recording started")
        FRAME_BUFFER.append({'frame': frame.copy(), 'y_centers': y_centers})
    elif RECORDING:
        blank = np.zeros((h, w, 3), np.uint8)
        FRAME_BUFFER.append({'frame': frame.copy() if frame is not None else blank, 'y_centers': y_centers})

    # end of detection?
    if RECORDING and (time.time() - LAST_DETECTION_TIME > DETECTION_TIMEOUT):
        RECORDING = False
        clip = list(FRAME_BUFFER)
        FRAME_BUFFER.clear()
        threading.Thread(target=save_clip_and_metadata, args=(clip,), daemon=True).start()
        print("[INFO] Detection ended, saving clip")

    return Gst.PadProbeReturn.OK

# --------------------------------------------
# Main (headless!)
# --------------------------------------------
if __name__ == "__main__":
    threading.Thread(target=read_serial, daemon=True).start()
    app = GStreamerDetectionApp(app_callback, UserAppCallback())
    app.run()

