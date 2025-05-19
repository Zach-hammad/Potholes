from typing import List
from .s3_service import S3Service
from .dummy_gen import generate_dummy_potholes
from flask import Flask



def load_pothole_data(app: Flask, n_dummy: int =100)->List[dict]:
    """
    Attempt to load real pothole sidecar data from S3 via app.s3.
    If that fails—or returns an empty list—fall back to dummy data.
    """
    s3: S3Service = app.s3
    try:
        data =  s3.fetch_pothole_data()
        app.logger.info(f"Loaded {len(data)} records from S3 bucket")
        if not data:
            raise RuntimeError("No JSON sidecars found in the bucket")
    except Exception as e:
        app.logger.error(f"Error fetching from S3: {e}")
        data = generate_dummy_potholes(n_dummy)
        app.logger.info("Falling back to dummy data")

    return data