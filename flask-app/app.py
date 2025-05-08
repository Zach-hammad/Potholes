# app.py

from flask import Flask, render_template, request, jsonify, send_file, abort
import boto3
import os
import io
import csv
import json
import random
import datetime
from werkzeug.utils import secure_filename
import glob
import mimetypes
import kaggle_to_tigris

app = Flask(__name__)

# --- Tigris S3 Configuration (S3-compatible) ---
S3_URL = "https://fly.storage.tigris.dev/"
TIGRIS_BUCKET_NAME = 'pothole-images'
svc = boto3.client(
    's3',
    endpoint_url=S3_URL,
    aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY')
)

def delete_s3_directory(bucket: str, prefix: str):
    paginator = svc.get_paginator('list_objects_v2')
    to_delete = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix + '/'):
        for obj in page.get('Contents', []):
            to_delete.append({'Key': obj['Key']})

    if not to_delete:
        return []

    deleted = []
    for i in range(0, len(to_delete), 1000):
        batch = to_delete[i:i+1000]
        resp = svc.delete_objects(Bucket=bucket, Delete={'Objects': batch})
        deleted.extend(resp.get('Deleted', []))

    return deleted

# --- Helper: fetch real data from Tigris via boto3 S3 API ---
# --- Helper: fetch real data from S3, capturing the folder & base name ---
def fetch_pothole_data_from_s3(bucket_name: str):
    paginator = svc.get_paginator('list_objects_v2')
    page_iterator = paginator.paginate(Bucket=bucket_name)

    data = []
    for page in page_iterator:
        for obj in page.get('Contents', []):
            key = obj['Key']
            if not key.lower().endswith('.json'):
                continue

            try:
                resp    = svc.get_object(Bucket=bucket_name, Key=key)
                sidecar = json.loads(resp['Body'].read())
            except Exception as e:
                app.logger.warning(f"Skipping {key}: {e}")
                continue

            ts  = sidecar.get("timestamp")
            gps = sidecar.get("gps", {})
            lat = gps.get("lat")
            lon = gps.get("lon")
            if ts is None or lat is None or lon is None:
                app.logger.warning(f"Skipping incomplete sidecar {key}")
                continue

            # split off the date-folder and base filename
            prefix, filename = key.rsplit('/', 1)            # e.g. "2025-5-01", "pothole_1746148157.json"
            base             = filename.rsplit('.', 1)[0]    # e.g. "pothole_1746148157"

            data.append({
                "id":          ts,                             # timestamp
                "lat":         lat,
                "lng":         lon,
                "severity" : random.randint(1, 5),
                "confidence" : round(random.uniform(0.5, 1.0), 2),
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
            "id": i,
            "lat": round(lat, 6),
            "lng": round(lng, 6),
            "severity": severity,
            "confidence": confidence,
            "date": date,
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
    sev_list = args.getlist('severity', type=int)
    start = args.get('start_date')
    end = args.get('end_date')
    conf_min = args.get('conf_min', type=float, default=0.0)

    results = []
    for p in POH_DATA:
        if sev_list and p['severity'] not in sev_list:
            continue
        if start and p['date'] < start:
            continue
        if end and p['date'] > end:
            continue
        if (p.get('confidence') or 0) < conf_min:
            continue
        results.append(p)
    return results

# --- Routes ---

@app.route('/', methods=['GET'])
def index():
    return render_template('index.html')

@app.route('/dashboard', methods=['GET'])
def dashboard():
    return render_template('dashboard.html')


@app.route('/api/potholes', methods=['GET'])
def get_potholes():
    results = filter_potholes(request.args)

    for p in results:
        # your bucket has: <date-folder>/<base>.json  &  <base>_best.<ext>
        prefix = f"{p['s3_prefix']}/{p['s3_base']}_best"
        try:
            # List objects in the bucket to find matching image files
            response = svc.list_objects_v2(
                Bucket=TIGRIS_BUCKET_NAME,
                Prefix=prefix
            )
            # Find the first matching image file
            image_key = None
            for obj in response.get('Contents', []):
                if obj['Key'].startswith(prefix) and obj['Key'].lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
                    image_key = obj['Key']
                    break

            if image_key:
                url = svc.generate_presigned_url(
                    ClientMethod='get_object',
                    Params={'Bucket': TIGRIS_BUCKET_NAME, 'Key': image_key},
                    ExpiresIn=3600
                )
            else:
                url = None
        except Exception as e:
            app.logger.warning(f"Couldn’t find or presign image for {prefix}: {e}")
            url = None

        p['image_url'] = url

    return jsonify(results)

# ...existing code...

@app.route('/export', methods=['GET'])
def export_data():
    fmt = request.args.get('format', 'csv')
    data = filter_potholes(request.args)

    if fmt == 'geojson':
        gj = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [p['lng'], p['lat']]
                    },
                    "properties": {
                        k: v for k, v in p.items() if k not in ('lat', 'lng')
                    }
                } for p in data
            ]
        }
        return jsonify(gj)

    si = io.StringIO()
    writer = csv.DictWriter(si, fieldnames=data[0].keys() if data else [])
    writer.writeheader()
    writer.writerows(data)

    return send_file(
        io.BytesIO(si.getvalue().encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name='potholes.csv'
    )

@app.route('/generate_presigned_url', methods=['POST'])
def generate_presigned_url():
    payload = request.get_json(force=True)

    # Single-file upload
    if not payload.get('dataset_url'):
        file_name = payload.get('file_name')
        file_type = payload.get('file_type')
        try:
            presigned_post = svc.generate_presigned_post(
                Bucket=TIGRIS_BUCKET_NAME,
                Key=file_name,
                Fields={"Content-Type": file_type},
                Conditions=[{"Content-Type": file_type}],
            )
            return jsonify({'data': presigned_post})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    # Kaggle dataset bulk upload
    dataset_url = payload['dataset_url']
    kaggle_api = kaggle_to_tigris.kaggle_auth()
    dataset = kaggle_to_tigris.pull_images_from_dataset(kaggle_api, dataset_url)
    files = glob.glob(f"{dataset}/**/*.*", recursive=True)

    presigned_urls = []
    for file_path in files:
        file_name = secure_filename(os.path.basename(file_path))
        content_type = mimetypes.guess_type(file_name)[0] or 'application/octet-stream'
        presigned_post = svc.generate_presigned_post(
            Bucket=TIGRIS_BUCKET_NAME,
            Key=f"{dataset}/{file_name}",
            Fields={"Content-Type": content_type},
            Conditions=[{"Content-Type": content_type}],
        )
        presigned_urls.append({
            "file_name": file_name,
            "file_path": file_path,
            "url": presigned_post['url'],
            "fields": presigned_post['fields']
        })

    return jsonify({'results': presigned_urls})

@app.route('/list_buckets', methods=['GET'])
def list_buckets():
    try:
        buckets = svc.list_buckets().get('Buckets', [])
        result = {}
        for b in buckets:
            name = b['Name']
            objs = svc.list_objects_v2(Bucket=name).get('Contents', [])
            result[name] = [o['Key'] for o in objs]
        return jsonify({'buckets': result})
    except Exception as e:
        app.logger.error(f"Error listing buckets: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/local-files/<path:file_path>', methods=['GET', 'DELETE'])
def serve_local_file(file_path):
    try:
        if os.path.isfile(file_path):
            if request.method == 'DELETE':
                os.remove(file_path)
                return jsonify({})
            return send_file(file_path)
        else:
            abort(404, description="File not found.")
    except Exception as e:
        app.logger.error(f"Error serving file {file_path}: {e}")
        abort(500, description="Internal server error.")

@app.route('/api/delete_today_directory', methods=['DELETE'])
def delete_today_directory():
    today_prefix = datetime.date.today().isoformat()
    deleted = delete_s3_directory(TIGRIS_BUCKET_NAME, today_prefix)
    if not deleted:
        return jsonify({'message': f'No objects found under "{today_prefix}/"'}), 404
    return jsonify({'deleted': deleted}), 200

# --- Run the app ---
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8501, debug=True)
