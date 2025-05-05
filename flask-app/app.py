# app.py

from flask import Flask, render_template, request, jsonify, send_file, abort
import boto3
import os
import io
import csv
import json
import datetime
from werkzeug.utils import secure_filename
import glob
import mimetypes
import kaggle_to_tigris
import random

import torch
import torchvision.transforms as T
from PIL import Image
import numpy as np

app = Flask(__name__)

# --- Tigris S3 Configuration (S3-compatible) ---
S3_URL = "https://fly.storage.tigris.dev/"
TIGRIS_BUCKET_NAME = "pothole-images"
svc = boto3.client(
    "s3",
    endpoint_url=S3_URL,
    aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
)

# ───────────────────────────────────────────────────────────────────────────────
# Severity model setup
# ───────────────────────────────────────────────────────────────────────────────
MODEL_PATH = os.path.join(os.path.dirname(__file__), "models", "severity.pt")
DEVICE     = torch.device("cpu")

# Load the PyTorch .pt model
severity_model = torch.load(MODEL_PATH, map_location=DEVICE)
severity_model.eval()

# Define the same transforms used during training
severity_transform = T.Compose([
    T.Resize((640, 640)),      # adjust to your model's expected input size
    T.ToTensor(),
])

def preprocess_for_severity(img: Image.Image):
    """
    Preprocess PIL image for severity model:
      - Resize
      - ToTensor
      - Normalize
      - Add batch dim
    """
    return severity_transform(img).unsqueeze(0).to(DEVICE)


# --- Helper: fetch real data from Tigris via boto3 S3 API ---
def fetch_pothole_data_from_s3(bucket_name: str):
    paginator = svc.get_paginator("list_objects_v2")
    page_iterator = paginator.paginate(Bucket=bucket_name)

    data = []
    for page in page_iterator:
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if not key.lower().endswith(".json"):
                continue

            # fetch the sidecar JSON
            try:
                resp      = svc.get_object(Bucket=bucket_name, Key=key)
                sidecar   = json.loads(resp["Body"].read())
            except Exception as e:
                app.logger.warning(f"Skipping sidecar {key}: {e}")
                continue

            ts  = sidecar.get("timestamp")
            gps = sidecar.get("gps", {})
            lat = gps.get("lat")
            lon = gps.get("lon")
            if ts is None or lat is None or lon is None:
                app.logger.warning(f"Incomplete data in sidecar {key}, skipping")
                continue

            # derive prefix (folder) and base filename (without extension)
            prefix, filename = key.rsplit("/", 1)          # e.g. "2025-05-02", "pothole_1716148205.json"
            base             = filename.rsplit(".", 1)[0] # e.g. "pothole_1716148205"

            # fetch the best-frame image and run severity inference
            best_key = f"{prefix}/{base}_best.jpg"
            sev = None
            try:
                resp_img   = svc.get_object(Bucket=bucket_name, Key=best_key)
                img_bytes  = resp_img["Body"].read()
                img        = Image.open(io.BytesIO(img_bytes)).convert("RGB")
                inp_tensor = preprocess_for_severity(img)
                with torch.no_grad():
                    logits = severity_model(inp_tensor)
                    cls    = int(logits.argmax(dim=1).item())
                    # map class 0→4 to severities 1→5:
                    sev = cls + 1
            except Exception as e:
                app.logger.warning(f"Severity inference failed for {best_key}: {e}")

            data.append({
                "id":          ts,
                "lat":         lat,
                "lng":         lon,
                "severity":    sev,
                "confidence":  round(random.uniform(0.5, 1.0), 2),
                "timestamp":   ts,
                "date":        datetime.date.fromtimestamp(ts).isoformat(),
                "description": sidecar.get("description", ""),
                "s3_prefix":   prefix,
                "s3_base":     base
            })

    return data


# --- Dummy Pothole Data Generation (fallback) ---
def generate_dummy_potholes(n=100):
    base_lat, base_lng = 39.9526, -75.1652
    descriptions = [
        "Crack along curb", "Large crater", "Hairline fracture",
        "Pothole near manhole", "Edge collapse", "Multiple small holes",
        "Sunken asphalt", "Long depression", "Water pooling", "Severe washout"
    ]
    today = datetime.date.today()
    data = []
    for i in range(1, n + 1):
        lat = base_lat + random.uniform(-0.03, 0.03)
        lng = base_lng + random.uniform(-0.03, 0.03)
        severity = random.randint(1, 5)
        confidence = round(random.uniform(0.5, 1.0), 2)
        date = (today - datetime.timedelta(days=random.randint(0, 30))).isoformat()
        desc = random.choice(descriptions)
        data.append({
            "id":          i,
            "lat":         round(lat, 6),
            "lng":         round(lng, 6),
            "severity":    severity,
            "confidence":  confidence,
            "date":        date,
            "description": desc
        })
    return data


# --- Load your pothole data at startup ---
try:
    POH_DATA = fetch_pothole_data_from_s3(TIGRIS_BUCKET_NAME)
    app.logger.info(f"Loaded {len(POH_DATA)} records from S3 bucket '{TIGRIS_BUCKET_NAME}'")
    if not POH_DATA:
        raise RuntimeError("No JSON sidecars found in the bucket")
except Exception as e:
    app.logger.error(f"Error fetching from S3: {e}")
    POH_DATA = generate_dummy_potholes(100)
    app.logger.info("Falling back to dummy data")


# --- Helper to filter potholes based on query args ---
def filter_potholes(args):
    sev_list = args.getlist("severity", type=int)
    start = args.get("start_date")
    end = args.get("end_date")
    conf_min = args.get("conf_min", type=float, default=0.0)

    results = []
    for p in POH_DATA:
        if sev_list and (p.get("severity") not in sev_list):
            continue
        if start and p["date"] < start:
            continue
        if end and p["date"] > end:
            continue
        if (p.get("confidence") or 0) < conf_min:
            continue
        results.append(p)
    return results


# --- Routes ---
@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@app.route("/dashboard", methods=["GET"])
def dashboard():
    return render_template("dashboard.html")


@app.route("/api/potholes", methods=["GET"])
def get_potholes():
    results = filter_potholes(request.args)

    for p in results:
        key = f"{p['s3_prefix']}/{p['s3_base']}_best.jpg"
        try:
            url = svc.generate_presigned_url(
                ClientMethod="get_object",
                Params={"Bucket": TIGRIS_BUCKET_NAME, "Key": key},
                ExpiresIn=3600
            )
        except Exception as e:
            app.logger.warning(f"Couldn't presign {key}: {e}")
            url = None

        p["image_url"] = url

    return jsonify(results)


@app.route("/export", methods=["GET"])
def export_data():
    fmt = request.args.get("format", "csv")
    data = filter_potholes(request.args)

    if fmt == "geojson":
        gj = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [p["lng"], p["lat"]],
                    },
                    "properties": {k: v for k, v in p.items() if k not in ("lat", "lng")},
                }
                for p in data
            ],
        }
        return jsonify(gj)

    si = io.StringIO()
    writer = csv.DictWriter(si, fieldnames=data[0].keys() if data else [])
    writer.writeheader()
    writer.writerows(data)

    return send_file(
        io.BytesIO(si.getvalue().encode()),
        mimetype="text/csv",
        as_attachment=True,
        download_name="potholes.csv",
    )


@app.route("/generate_presigned_url", methods=["POST"])
def generate_presigned_url():
    payload = request.get_json(force=True)

    if not payload.get("dataset_url"):
        file_name = payload.get("file_name")
        file_type = payload.get("file_type")
        try:
            presigned_post = svc.generate_presigned_post(
                Bucket=TIGRIS_BUCKET_NAME,
                Key=file_name,
                Fields={"Content-Type": file_type},
                Conditions=[{"Content-Type": file_type}],
            )
            return jsonify({"data": presigned_post})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # Kaggle dataset bulk upload
    dataset_url = payload["dataset_url"]
    kaggle_api = kaggle_to_tigris.kaggle_auth()
    dataset = kaggle_to_tigris.pull_images_from_dataset(kaggle_api, dataset_url)
    files = glob.glob(f"{dataset}/**/*.*", recursive=True)

    presigned_urls = []
    for file_path in files:
        file_name = secure_filename(os.path.basename(file_path))
        content_type = mimetypes.guess_type(file_name)[0] or "application/octet-stream"
        presigned_post = svc.generate_presigned_post(
            Bucket=TIGRIS_BUCKET_NAME,
            Key=f"{dataset}/{file_name}",
            Fields={"Content-Type": content_type},
            Conditions=[{"Content-Type": content_type}],
        )
        presigned_urls.append(
            {
                "file_name": file_name,
                "file_path": file_path,
                "url": presigned_post["url"],
                "fields": presigned_post["fields"],
            }
        )

    return jsonify({"results": presigned_urls})


@app.route("/list_buckets", methods=["GET"])
def list_buckets():
    try:
        buckets = svc.list_buckets().get("Buckets", [])
        result = {}
        for b in buckets:
            name = b["Name"]
            objs = svc.list_objects_v2(Bucket=name).get("Contents", [])
            result[name] = [o["Key"] for o in objs]
        return jsonify({"buckets": result})
    except Exception as e:
        app.logger.error(f"Error listing buckets: {e}")
        return jsonify({"error": "Internal server error"}), 500


@app.route("/local-files/<path:file_path>", methods=["GET", "DELETE"])
def serve_local_file(file_path):
    try:
        if os.path.isfile(file_path):
            if request.method == "DELETE":
                os.remove(file_path)
                return jsonify({})
            return send_file(file_path)
        else:
            abort(404, description="File not found.")
    except Exception as e:
        app.logger.error(f"Error serving file {file_path}: {e}")
        abort(500, description="Internal server error.")


# --- Run the app ---
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8501, debug=True)
