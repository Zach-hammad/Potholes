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
# Global State
# --------------------------------------------
latest_serial_data = {"raw": "", "lat": None, "lon": None}
latest_frame = None  # for calibration uploads

FRAME_BUFFER = deque(maxlen=300)
RECORDING = False
LAST_DETECTION_TIME = 0
DETECTION_TIMEOUT = 3

OUTPUT_BASE_DIR = "cached_clips"
os.makedirs(OUTPUT_BASE_DIR, exist_ok=True)

# --------------------------------------------
# Serial Reader Thread
# --------------------------------------------
def read_serial():
    global latest_serial_data
    print("[DEBUG] Serial reader thread starting")
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
        print(f"[ERROR] Serial thread error: {e}")

# --------------------------------------------
# Save Clip, Best Frames & Metadata
# --------------------------------------------
def save_clip_and_metadata(frames_data):
    print("[DEBUG] save_clip_and_metadata() triggered")
    if not frames_data:
        print("[WARN] No frames to save, aborting")
        return

    date_str = datetime.date.today().isoformat()
    out_dir = os.path.join(OUTPUT_BASE_DIR, date_str)
    os.makedirs(out_dir, exist_ok=True)
    ts = int(time.time())

    vid = f"pothole_{ts}.avi"
    meta_fn = f"pothole_{ts}.json"
    best_clean = f"pothole_{ts}_best_clean.png"
    best_ann = f"pothole_{ts}_best.png"

    # Write video (annotated)
    h, w, _ = frames_data[0]['annotated_frame'].shape
    print(f"[INFO] Writing video {vid}")
    writer = cv2.VideoWriter(
        os.path.join(out_dir, vid),
        cv2.VideoWriter_fourcc(*'XVID'),
        30,
        (w, h)
    )
    if not writer.isOpened():
        print(f"[ERROR] VideoWriter failed for {vid}")
        return
    for e in frames_data:
        writer.write(e['annotated_frame'])
    writer.release()
    print(f"[INFO] Saved video: {vid}")

    # Select best frame by center proximity
    bi, bd = None, float('inf')
    for i, e in enumerate(frames_data):
        for yc in e['y_centers']:
            d = abs(yc - 0.5)
            if d < bd:
                bd, bi = d, i

    if bi is not None:
        print(f"[DEBUG] Best frame index: {bi}")
        # Save un-annotated “clean” best frame
        clean_path = os.path.join(out_dir, best_clean)
        cv2.imwrite(clean_path, frames_data[bi]['clean_frame'])
        print(f"[INFO] Saved clean best frame: {best_clean}")

        # Save annotated best frame
        ann_path = os.path.join(out_dir, best_ann)
        cv2.imwrite(ann_path, frames_data[bi]['annotated_frame'])
        print(f"[INFO] Saved annotated best frame: {best_ann}")

    # Write metadata
    meta = {
        "timestamp": ts,
        "gps": {"lat": latest_serial_data['lat'], "lon": latest_serial_data['lon']},
        "frame_count": len(frames_data),
        "duration_s": round(len(frames_data) / 30, 2)
    }
    meta_path = os.path.join(out_dir, meta_fn)
    with open(meta_path, 'w') as f:
        json.dump(meta, f, indent=2)
    print(f"[INFO] Saved metadata: {meta_fn}")

    # Upload files to S3
    for fn in (vid, meta_fn, best_clean, best_ann):
        lp = os.path.join(out_dir, fn)
        key = f"{date_str}/{fn}"
        try:
            s3_client.upload_file(lp, TIGRIS_BUCKET_NAME, key)
            print(f"[INFO] Uploaded {fn} to S3://{TIGRIS_BUCKET_NAME}/{key}")
        except Exception as e:
            print(f"[ERROR] Failed upload {fn}: {e}")

# --------------------------------------------
# Periodic Calibration Upload
# --------------------------------------------
def upload_calibration_frame():
    global latest_frame
    # schedule next run
    threading.Timer(1.0, upload_calibration_frame).start()

    if latest_frame is None:
        return  # no prints if nothing to upload

    # save and upload calibration frame
    ds = datetime.date.today().isoformat()
    cd = os.path.join(OUTPUT_BASE_DIR, ds, 'calibration')
    os.makedirs(cd, exist_ok=True)
    fn = f"calib_{int(time.time())}.png"
    path = os.path.join(cd, fn)
    cv2.imwrite(path, latest_frame)

    key = f"{ds}/calibration/{fn}"
    try:
        s3_client.upload_file(path, TIGRIS_BUCKET_NAME, key)
        print(f"[CALIB] Uploaded calibration frame: {fn} to S3://{TIGRIS_BUCKET_NAME}/{key}")
    except Exception as e:
        print(f"[CALIB] Upload failed for {fn}: {e}")

# --------------------------------------------
# GStreamer Callback
# --------------------------------------------
def app_callback(pad, info, user_data):
    global latest_frame, FRAME_BUFFER, RECORDING, LAST_DETECTION_TIME
    buf = info.get_buffer()
    if buf is None:
        return Gst.PadProbeReturn.OK
    user_data.use_frame = True

    fmt, w, h = get_caps_from_pad(pad)
    if not (fmt and w and h):
        return Gst.PadProbeReturn.OK

    frame = get_numpy_from_buffer(buf, fmt, w, h)
    if frame is None:
        return Gst.PadProbeReturn.OK

    # keep raw and latest for calibration
    raw = frame.copy()
    latest_frame = raw.copy()

    # prepare annotated copy
    ann = frame.copy()

    dets = hailo.get_roi_from_buffer(buf).get_objects_typed(hailo.HAILO_DETECTION)
    centers, confs, boxes = [], [], []
    pothole_detected = False

    for det in dets:
        if det.get_class_id() == 1:
            pothole_detected = True
        b = det.get_bbox()
        boxes.append({
            'xmin': b.xmin(), 'ymin': b.ymin(),
            'xmax': b.xmax(), 'ymax': b.ymax()
        })
        centers.append((b.ymin() + b.ymax()) / 2.0)
        confs.append(det.get_confidence())

    # draw annotations
    for box in boxes:
        x0, y0 = int(box['xmin']*w), int(box['ymin']*h)
        x1, y1 = int(box['xmax']*w), int(box['ymax']*h)
        cv2.rectangle(ann, (x0,y0), (x1,y1), (0,255,0), 2)
    if confs:
        cv2.putText(ann, f"Conf: {max(confs):.2f}", (10,30),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0,0,255), 2)

    now = time.time()
    if pothole_detected:
        LAST_DETECTION_TIME = now
        if not RECORDING:
            RECORDING = True
            FRAME_BUFFER.clear()
            print("[INFO] Recording started")
        FRAME_BUFFER.append({
            'clean_frame': raw,
            'annotated_frame': ann,
            'y_centers': centers,
            'confidences': confs,
            'bboxes': boxes
        })
    elif RECORDING and (now - LAST_DETECTION_TIME > DETECTION_TIMEOUT):
        RECORDING = False
        print("[INFO] Detection ended, saving clip")
        threading.Thread(
            target=save_clip_and_metadata,
            args=(list(FRAME_BUFFER),),
            daemon=True
        ).start()

    return Gst.PadProbeReturn.OK

# --------------------------------------------
# Main Entry
# --------------------------------------------
if __name__ == "__main__":
    print("[DEBUG] Starting application")
    threading.Thread(target=read_serial, daemon=True).start()
    print("[DEBUG] Serial reader started")
    upload_calibration_frame()
    print("[DEBUG] Calibration uploader initialized")
    app = GStreamerDetectionApp(app_callback, app_callback_class())
#    flip = Gst.ElementFactory.make("videoflip", "flip")
#    app.add(flip)

#    app.pipeline_description = app.pipeline_description.replace(
#        'videoconvert',
 #       'videoflip method=clockwise ! videoconvert'
 #   )
 #   print("[DEBUG] Launching GStreamerDetectionApp")

    app.run()
