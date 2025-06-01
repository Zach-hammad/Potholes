import os
import datetime
import threading
import cv2
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