import datetime, time
import os
import cv2
import json
import requests
from loguru import logger
# --------------------------------------------
# Save Clip, Best Frames & Metadata
# --------------------------------------------
def save_clip_and_metadata(frames_data, s3_client, OUTPUT_BASE_DIR, TIGRIS_BUCKET_NAME, latest_serial_data):
    logger.debug("[DEBUG] save_clip_and_metadata() triggered")
    if not frames_data:
        logger.warning("[WARN] No frames to save, aborting")
        return

    date_str = datetime.date.today().isoformat()
    out_dir = os.path.join(OUTPUT_BASE_DIR, date_str)
    os.makedirs(out_dir, exist_ok=True)
    ts = int(time.time())

    vid = f"pothole_{ts}.avi"
    meta_fn = f"pothole_{ts}.json"
    best_clean = f"pothole_{ts}_best_clean.jpg"
    best_ann = f"pothole_{ts}_best.jpg"

    # Write video (annotated)
    h, w, _ = frames_data[0]['annotated_frame'].shape
    logger.info(f"[INFO] Writing video {vid}")
    writer = cv2.VideoWriter(
        os.path.join(out_dir, vid),
        cv2.VideoWriter_fourcc(*'XVID'),
        30,
        (w, h)
    )
    if not writer.isOpened():
        logger.error(f"[ERROR] VideoWriter failed for {vid}")
        return
    for e in frames_data:
        writer.write(e['annotated_frame'])
    writer.release()
    logger.info(f"[INFO] Saved video: {vid}")

    # Select best frame by center proximity
    bi, bd = None, float('inf')
    for i, e in enumerate(frames_data):
        for yc in e['y_centers']:
            d = abs(yc - 0.5)
            if d < bd:
                bd, bi = d, i

    if bi is not None:
        logger.debug(f"[DEBUG] Best frame index: {bi}")
        # Save un-annotated “clean” best frame
        clean_path = os.path.join(out_dir, best_clean)
        cv2.imwrite(clean_path, frames_data[bi]['clean_frame'])
        logger.info(f"[INFO] Saved clean best frame: {best_clean}")

        # Save annotated best frame
        ann_path = os.path.join(out_dir, best_ann)
        cv2.imwrite(ann_path, frames_data[bi]['annotated_frame'])
        logger.info(f"[INFO] Saved annotated best frame: {best_ann}")

    # Write metadata
    meta = {
        "timestamp": ts,
        "captured_at": datetime.datetime.now().isoformat(),
        "gps": {"lat": latest_serial_data['lat'], "lon": latest_serial_data['lon']},
        "nmea_raw": latest_serial_data['raw'],
        "confidence": max(frames_data[0]['confidences']),
        "bboxes": frames_data[0]['bboxes'],
        "severity": None,
        "video_name": vid,
        "s3_key": f"{date_str}/{vid}",
        "frame_count": len(frames_data),
        "duration_s": round(len(frames_data) / 30, 2)
    }
    meta_path = os.path.join(out_dir, meta_fn)
    with open(meta_path, 'w') as f:
        json.dump(meta, f, indent=2)
    logger.info(f"[INFO] Saved metadata: {meta_fn}")

    # Upload files to S3
    for fn in (vid, meta_fn, best_clean, best_ann):
        lp = os.path.join(out_dir, fn)
        key = f"{date_str}/{fn}"
        upload(lp, s3_client, TIGRIS_BUCKET_NAME, key)



def ping_google():
    url = "https://www.google.com"
    response = requests.get(url)
    return response.status_code

def upload(lp, fn, s3_client, TIGRIS_BUCKET_NAME, key):
    if ping_google() == 200:
        s3_client.upload_file(lp, TIGRIS_BUCKET_NAME, key)
        os.remove(lp)
        logger.info(f"[INFO] Uploaded {fn} to S3://{TIGRIS_BUCKET_NAME}/{key}")
    else:
        time.sleep(120)
        upload(lp, fn, s3_client, TIGRIS_BUCKET_NAME, key)


