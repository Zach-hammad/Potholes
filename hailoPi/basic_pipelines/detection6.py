#!/usr/bin/env python3
import os
import time
import json
import threading
import serial
import datetime
from collections import deque

import numpy as np
import cv2
from picamera2 import Picamera2, Preview
import hailo_platform  # pip install hailo_platform (or use your local HailoRT package)
from hailo_platform import HailoRTEngine, ConfigParams

# ----------------------------------------
# Configuration
# ----------------------------------------
HEF_PATH      = "pothole/pothole.hef"
LABELS_JSON   = "resources/pothole.json"
OUTPUT_BASE   = "cached_clips"
S3_BUCKET     = os.getenv("TIGRIS_BUCKET_NAME", "pothole-images")
S3_URL        = os.getenv("S3_URL", "https://fly.storage.tigris.dev/")
ACCESS_KEY    = os.getenv("S3_ACCESS_KEY")
SECRET_KEY    = os.getenv("S3_SECRET_KEY")

# Hailo model input size
MODEL_W, MODEL_H = 640, 640   # match your HEF

# VideoWriter params
FPS = 30
FRAME_BUFFER_LEN = 300
DETECTION_TIMEOUT = 3.0      # seconds after last detection to cut clip

# Serial (GPS) state
latest_serial = {"lat": None, "lon": None, "raw": ""}

# ----------------------------------------
# GPS reader thread
# ----------------------------------------
def read_serial():
    try:
        ser = serial.Serial("/dev/serial0", 9600, timeout=1)
        while True:
            line = ser.readline().decode("ascii", errors="ignore").strip()
            if line.startswith(("$GPRMC","$GPGGA")):
                parts = line.split(",")
                latest_serial["raw"] = line
                # parse same as before...
                if line.startswith("$GPRMC") and parts[2]=="A":
                    lat = float(parts[3][:2]) + float(parts[3][2:])/60.0
                    if parts[4]=="S": lat = -lat
                    lon = float(parts[5][:3]) + float(parts[5][3:])/60.0
                    if parts[6]=="W": lon = -lon
                elif line.startswith("$GPGGA") and parts[6]!="0":
                    lat = float(parts[2][:2]) + float(parts[2][2:])/60.0
                    if parts[3]=="S": lat = -lat
                    lon = float(parts[4][:3]) + float(parts[4][3:])/60.0
                    if parts[5]=="W": lon = -lon
                else:
                    continue
                latest_serial.update({"lat":lat, "lon":lon})
                #print(f"[GPS] {lat:.6f}, {lon:.6f}")
    except Exception as e:
        print("[GPS ERR]", e)

# ----------------------------------------
# Clip saver
# ----------------------------------------
def save_clip_and_metadata(frames_data):
    if not frames_data:
        return

    date_str = datetime.date.today().isoformat()
    out_dir  = os.path.join(OUTPUT_BASE, date_str)
    os.makedirs(out_dir, exist_ok=True)

    ts = int(time.time())
    vid_path  = os.path.join(out_dir, f"pothole_{ts}.avi")
    best_path = os.path.join(out_dir, f"pothole_{ts}_best.jpg")
    meta_path = os.path.join(out_dir, f"pothole_{ts}.json")

    h, w, _ = frames_data[0]["frame"].shape
    vw = cv2.VideoWriter(vid_path, cv2.VideoWriter_fourcc(*"XVID"), FPS, (w,h))
    if not vw.isOpened():
        print("[ERROR] Could not open video writer")
        return
    for e in frames_data:
        vw.write(e["frame"])
    vw.release()
    print(f"[INFO] Saved video {vid_path}")

    # pick best frame by center-height closeness
    best_idx, best_diff = None, float("inf")
    for i,e in enumerate(frames_data):
        for yc in e["y_centers"]:
            d = abs(yc - 0.5)
            if d < best_diff:
                best_diff, best_idx = d, i

    if best_idx is not None:
        cv2.imwrite(best_path, frames_data[best_idx]["frame"])
        print(f"[INFO] Saved best frame {best_path}")

    meta = {
        "timestamp": ts,
        "gps": {"lat": latest_serial["lat"], "lon": latest_serial["lon"]},
    }
    with open(meta_path, "w") as f:
        json.dump(meta, f)
    print(f"[INFO] Saved metadata {meta_path}")

    # TODO: upload to S3 if needed

# ----------------------------------------
# Hailo setup
# ----------------------------------------
def load_engine():
    cfg = ConfigParams()
    cfg.set("HEF_PATH", HEF_PATH)
    # any additional HailoRT params here...
    engine = HailoRTEngine(cfg)
    return engine

# ----------------------------------------
# Pre/Post processing
# ----------------------------------------
def preprocess(frame):
    """Letterbox‐resize to MODEL_W×MODEL_H, normalize, NCHW."""
    h, w = frame.shape[:2]
    scale = min(MODEL_W/w, MODEL_H/h)
    nw, nh = int(w*scale), int(h*scale)
    resized = cv2.resize(frame, (nw, nh))
    pad = np.full((MODEL_H, MODEL_W, 3), 114, dtype=np.uint8)
    pad[(MODEL_H-nh)//2:(MODEL_H-nh)//2+nh, (MODEL_W-nw)//2:(MODEL_W-nw)//2+nw] = resized
    img = pad.astype(np.float32) / 255.0
    # HWC->CHW, add batch dim
    return img.transpose(2,0,1)[None, ...]

def postprocess(raw_outputs):
    """
    Parse raw Hailo outputs into list of detections:
    each det = (class_id, conf, xmin, ymin, xmax, ymax)
    Assumes your HEF yields float32 boxes & scores.
    You’ll need to adapt this to your model’s output format.
    """
    # placeholder: depends on your model
    # e.g. raw_outputs["boxes"], raw_outputs["scores"], raw_outputs["classes"]
    bboxes = raw_outputs["boxes"]      # shape [N,4] normalized
    scores = raw_outputs["scores"]     # shape [N]
    classes= raw_outputs["classes"]    # shape [N]
    dets = []
    for i,(bb,sc,cl) in enumerate(zip(bboxes, scores, classes)):
        if sc < 0.3: continue
        xmin, ymin, xmax, ymax = bb
        dets.append((int(cl), float(sc), xmin, ymin, xmax, ymax))
    return dets

# ----------------------------------------
# Main loop
# ----------------------------------------
if __name__ == "__main__":
    # start GPS reader
    threading.Thread(target=read_serial, daemon=True).start()

    # init camera
    picam2 = Picamera2()
    config = picam2.create_preview_configuration({"format":"RGB888", "size":(1280,720)})
    picam2.configure(config)
    picam2.start()

    # load Hailo engine
    engine = load_engine()

    FRAME_BUFFER = deque(maxlen=FRAME_BUFFER_LEN)
    recording    = False
    last_det     = 0

    try:
        while True:
            # 1) grab frame
            frame = picam2.capture_array()
            src_h, src_w = frame.shape[:2]

            # 2) preprocess & run
            inp = preprocess(frame)
            raw_out = engine.run({"input": inp})
            dets = postprocess(raw_out)

            # 3) annotate & buffer if pothole
            y_centers = []
            pothole = False
            for cl, sc, x0,y0,x1,y1 in dets:
                if cl == 1:
                    pothole = True
                # draw on frame
                cv2.rectangle(frame,
                              (int(x0*src_w), int(y0*src_h)),
                              (int(x1*src_w), int(y1*src_h)),
                              (0,255,0), 2)
                yc = (y0+y1)/2
                y_centers.append(yc)

            # GPS text
            lat, lon = latest_serial["lat"], latest_serial["lon"]
            gps_txt = f"Lat:{lat:.6f} Lon:{lon:.6f}" if lat and lon else "GPS N/A"
            cv2.putText(frame, gps_txt, (10, src_h-10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,255,0),1)

            # buffering logic
            if pothole:
                last_det = time.time()
                if not recording:
                    recording = True
                    print("[INFO] Detected pothole: starting buffer")
                FRAME_BUFFER.append({"frame": frame.copy(), "y_centers": y_centers})
            elif recording:
                FRAME_BUFFER.append({"frame": frame.copy(), "y_centers": y_centers})

            # check for end of event
            if recording and (time.time() - last_det > DETECTION_TIMEOUT):
                recording = False
                clip = list(FRAME_BUFFER)
                FRAME_BUFFER.clear()
                threading.Thread(target=save_clip_and_metadata,
                                 args=(clip,), daemon=True).start()
                print("[INFO] Detection ended — saving clip")

            # throttle to approximate FPS
            time.sleep(1.0 / FPS)

    except KeyboardInterrupt:
        print("Exiting…")
    finally:
        picam2.stop()
        engine.close()

