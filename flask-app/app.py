# app.py

from flask import Flask
import os
from config import BUCKET_NAME, S3_URL, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY
from services.s3_service import S3Service
from services.data_loader import load_pothole_data
from routes import api, dashboard, export

def create_app():
    app = Flask(__name__)

    app.s3 = S3Service(
        bucket_name=BUCKET_NAME,
        endpoint_url=S3_URL,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY
    )

    app.pothole_data = load_pothole_data(app)

    app.register_blueprint(dashboard.bp)
    app.register_blueprint(api.bp)
    app.register_blueprint(export.bp)

    return app

app = create_app()
# --- Run the app ---
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8501, debug=True)
