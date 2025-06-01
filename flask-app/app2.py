from flask import *
import boto3
import os
from werkzeug.utils import secure_filename
import kaggle_to_tigris
import glob
import mimetypes
import tempfile
import zipfile
import shutil

app = Flask(__name__)

S3_URL = "https://fly.storage.tigris.dev/"
TIGRIS_BUCKET_NAME = 'pothole-images'
svc = boto3.client(
    's3',
    endpoint_url=S3_URL,
    aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY')
)

@app.route('/', methods=['GET'])
def index():
    return render_template('index.html')

@app.route('/generate_presigned_url', methods=['POST'])
def generate_presigned_url():
    if not request.json.get('dataset_url'):            
        file_name = request.json.get('file_name')
        file_type = request.json.get('file_type')

        try:
            presigned_post = svc.generate_presigned_post(
                Bucket=TIGRIS_BUCKET_NAME,
                Key=file_name,
                Fields={"Content-Type": file_type},
                Conditions=[
                    {"Content-Type": file_type}
                ],
            )
            print(presigned_post)

            return jsonify({'data': presigned_post})
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    else:
        dataset_url = request.json.get('dataset_url')
        kaggle_api = kaggle_to_tigris.kaggle_auth()
        dataset = kaggle_to_tigris.pull_images_from_dataset(kaggle_api, dataset_url)
        dataset_files = glob.glob(f"{dataset}/**/*.*", recursive=True)
        
        presigned_urls = []
        for file_path in dataset_files:
            file_name = os.path.basename(file_path) 
            content_type = file_type = mimetypes.guess_type(file_name)[0] 
            presigned_post = svc.generate_presigned_post(
                Bucket=TIGRIS_BUCKET_NAME,
                Key=f"{dataset}/{file_name}",
                Fields={"Content-Type": content_type},
                Conditions=[{"Content-Type": content_type}],
            )
            print(presigned_post)
            presigned_urls.append({
                "file_name": file_name,
                "file_path": file_path.replace("/", "\\"),
                "url": presigned_post["url"],
                "fields": presigned_post["fields"]
            })

        return jsonify({'results': presigned_urls})
        

@app.get("/list_buckets")
def list_buckets():
    try:
        # List all buckets
        buckets = svc.list_buckets()
        bucket_names = [bucket["Name"] for bucket in buckets.get("Buckets", [])]

        # Dictionary to hold objects in each bucket
        buckets_with_objects = {}

        # Iterate over each bucket and list objects
        for bucket_name in bucket_names:
            try:
                response = svc.list_objects_v2(Bucket=bucket_name)
                # Check if the bucket contains any objects
                if 'Contents' in response:
                    objects = [obj['Key'] for obj in response['Contents']]
                else:
                    objects = []
                buckets_with_objects[bucket_name] = objects
            except Exception as e:
                app.logger.error(f"Error listing objects in bucket {bucket_name}: {e}")
                buckets_with_objects[bucket_name] = f"Error: {str(e)}"

        return jsonify({"buckets": buckets_with_objects})
    except Exception as e:
        app.logger.error(f"Error listing buckets: {e}")
        return jsonify({"error": "Internal server error"}), 500


@app.route('/local-files/<path:file_path>', methods=['GET', 'DELETE'])
def serve_local_file(file_path):
    """
    Serve files from the local temporary directory, allowing nested paths.
    """
    # Construct the full path to the requested file
    try:
    # Check if the file exists and is within the TEMP_DIR
        if os.path.isfile(file_path):
            if request.method != 'GET':
                os.remove(file_path)
                print(f"REMOVE FILE {file_path} OK")
                return jsonify({})
            return send_file(file_path)
        else:
            abort(404, description="File not found or access is not allowed.")
    except Exception as e:
        app.logger.error(f"Error serving file {file_path}: {e}")
        abort(500, description="Internal server error.")
        
@app.route('/download_bucket_directory', methods=['GET'])
def download_bucket_directory():
    prefix = request.args.get('prefix', '').strip()
    if not prefix:
        return jsonify({'error': 'Missing prefix'}), 400

    try:
        # List all objects with the given prefix
        response = svc.list_objects_v2(
            Bucket=TIGRIS_BUCKET_NAME,
            Prefix=prefix
        )

        if 'Contents' not in response:
            return jsonify({'error': 'No files found in the specified prefix'}), 404

        # Create a temporary directory and zip file
        temp_dir = tempfile.mkdtemp()
        zip_path = os.path.join(temp_dir, 'archive.zip')

        with zipfile.ZipFile(zip_path, 'w') as zipf:
            for obj in response['Contents']:
                key = obj['Key']
                if key.endswith('/'):  # skip directories
                    continue

                # Download object to a temporary file
                temp_file_path = os.path.join(temp_dir, os.path.basename(key))
                svc.download_file(TIGRIS_BUCKET_NAME, key, temp_file_path)

                # Add to zip archive
                zipf.write(temp_file_path, arcname=os.path.relpath(key, prefix))

        return send_file(zip_path, as_attachment=True, download_name='pothole_files.zip')

    except Exception as e:
        app.logger.error(f"Error zipping files for prefix '{prefix}': {e}")
        return jsonify({'error': str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8501)
