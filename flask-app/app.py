from flask import *
import boto3
import os
from werkzeug.utils import secure_filename
import kaggle_to_tigris


app = Flask(__name__)

S3_URL = "https://fly.storage.tigris.dev/"
TIGRIS_BUCKET_NAME = 'solitary-sun-9532'
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
            return jsonify({'data': presigned_post})
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    else:
        dataset_url = request.json.get('dataset_url')
        kaggle_api = kaggle_to_tigris.kaggle_auth()
        dataset = kaggle_to_tigris.pull_images_from_dataset(kaggle_api, dataset_url)
        dataset_images = [f for f in os.listdir(dataset) if f.endswith('.jpg')]
        
        try:
            presigned_post = svc.generate_presigned_post(
                Bucket=TIGRIS_BUCKET_NAME,
                Key=dataset_url,
                Fields={"Content-Type": file_type},
                Conditions=[
                    {"Content-Type": file_type}
                ],
            )
            return jsonify({'data': presigned_post})
        except Exception as e:
            return jsonify({'error': str(e)}), 500
        

@app.get("/list_buckets")
def list_buckets():
    try:
        buckets = svc.list_buckets()
        bucket_names = [bucket["Name"] for bucket in buckets.get("Buckets", [])]
        return jsonify({"buckets": bucket_names})
    except Exception as e:
        app.logger.error(f"Error listing buckets: {e}")
        return jsonify({"error": "Internal server error"}), 500
    
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8501)