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
import gps
import dataCapture
from loguru import logger

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
            logger.info("[INFO] Recording started")
        FRAME_BUFFER.append({
            'clean_frame': raw,
            'annotated_frame': ann,
            'y_centers': centers,
            'confidences': confs,
            'bboxes': boxes
        })
    elif RECORDING and (now - LAST_DETECTION_TIME > DETECTION_TIMEOUT):
        RECORDING = False
        logger.info("[INFO] Detection ended, saving clip")
        threading.Thread(
            target=dataCapture.save_clip_and_metadata,
            args=(list(FRAME_BUFFER),
                  s3_client,
                  OUTPUT_BASE_DIR,
                  TIGRIS_BUCKET_NAME,
                  latest_serial_data),
            daemon=True
        ).start()


    return Gst.PadProbeReturn.OK

# --------------------------------------------
# Main Entry
# --------------------------------------------
if __name__ == "__main__":
    logger.debug("[DEBUG] Starting application")
    threading.Thread(target=gps.read_serial,args=(latest_serial_data,), daemon=True).start()
    logger.debug("[DEBUG] Serial reader started")
    app = GStreamerDetectionApp(app_callback, app_callback_class())
    app.run()
