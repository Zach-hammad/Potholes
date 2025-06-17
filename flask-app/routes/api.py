import os, glob, datetime, mimetypes
from werkzeug.utils import secure_filename
from flask import Blueprint, request, jsonify, current_app, abort, send_file
from services.s3_service import S3Service
from services.filter import filter_potholes
import kaggle_to_tigris



bp = Blueprint('api', __name__, url_prefix = '/api')
@bp.route('/potholes', methods=['GET'])
def get_potholes():
    s3: S3Service = current_app.s3
    data = current_app.pothole_data
    results = filter_potholes(request.args, data)

    for p in results:
        # your bucket has: <date-folder>/<base>.json  &  <base>_best.<ext>
        if p.get('s3_prefix') and p.get('s3_base'):
            prefix = f"{p['s3_prefix']}/{p['s3_base']}_best"
            try:
                # List objects in the bucket to find matching image files
                p['image_url'] = current_app.s3.presign_image_get(prefix)
            except Exception as e:
                current_app.logger.warning(f"Couldn't find or presign image for {prefix}: {e}")
                p['image_url'] = None
    return jsonify(results)

@bp.route('/delete_today_directory', methods=['DELETE'])
def delete_today_directory():
    """
    Delete all objects under today's date in S3, and return the list of deleted keys.
    """
    today_prefix = datetime.date.today().isoformat()
    deleted = current_app.s3.delete_s3_directory(today_prefix)
    if not deleted:
        return jsonify({'message': f'No objects found under "{today_prefix}/"'}), 404
    return jsonify({'deleted': deleted}), 200


@bp.route('/generate_presigned_url', methods=['POST'])
def generate_presigned_url():
    s3: S3Service = current_app.s3
    payload = request.get_json(force=True)
    

    # Single-file upload
    if not payload.get('dataset_url'):
        file_name = payload.get('file_name')
        file_type = payload.get('file_type')
        if not file_name or not file_type:
            abort(400, "file_name and file_type are required")
        try:
            presigned_post = s3.generate_presigned_post(
                Key=file_name,
                content_type = file_type
            )
            return jsonify({'data': presigned_post})
        except Exception as e:
            current_app.logger.error("Failed to presign single upload")
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
        try:

            presigned_post = s3.generate_presigned_post(
                Key=f"{dataset}/{file_name}",
                content_type = content_type
            )
            presigned_urls.append({
                "file_name": file_name,
                "file_path": file_path,
                "url": presigned_post['url'],
                "fields": presigned_post['fields']
            })
        except Exception:
            current_app.logger.warning(f"Skipping presign for {file_name}")
    return jsonify({'results': presigned_urls})

@bp.route('/list_buckets', methods=['GET'])
def list_buckets():
    s3: S3Service = current_app.s3
    try:
        buckets = s3.svc.list_buckets().get('Buckets', [])
        result = {}
        for b in buckets:
            name = b['Name']
            objs = s3.svc.list_objects_v2(Bucket=name).get('Contents', [])
            result[name] = [o['Key'] for o in objs]
        return jsonify({'buckets': result})
    except Exception as e:
        app.logger.error(f"Error listing buckets: {e}")
        return jsonify({'error': 'Internal server error'}), 500

"""
@bp.route('/local-files/<path:file_path>', methods=['GET', 'DELETE'])
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
"""


