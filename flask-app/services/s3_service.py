import os
import json
import datetime
import random
from typing import List, Dict, Optional

from config import BUCKET_NAME, S3_URL, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY

import boto3
from botocore.config import Config  as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError

import config
import logging

logger = logging.getLogger(__name__)


class S3Service:
    """
    All S3/Tigris Bucket Operations
    """
    def __init__(
        self,
        bucket_name: str,
        endpoint_url: str,
        aws_access_key_id: str,
        aws_secret_access_key: str,
        max_attempts: int =3,
    ):
        self.bucket = BUCKET_NAME
        self.svc = boto3.client(
        's3',
        endpoint_url=S3_URL,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY 
    )

    def list_json_sidecars(self, prefix: Optional[str]=None) -> List[str]:
        """
        Return all .json keys under prefix or entire bucket
        """
        paginator = self.svc.get_paginator('list_objects_v2')
        kwargs = {"Bucket": self.bucket}
        if prefix:
            kwargs["Prefix"] = prefix

        keys: List[str] = []
        for page in paginator.paginate(**kwargs):
            for obj in page.get('Contents', []):
                key = obj['Key']
                if key.lower().endswith('.json'):
                    keys.append(key)
        return keys

    def fetch_sidecar(self, key: str) -> Optional[dict]:
        """
        Fetch and parse a single JSON sidecar. Returns NONE on Failure
        """
        try:
            resp    = self.svc.get_object(Bucket=self.bucket, Key=key)
            return json.loads(resp['Body'].read())
        except (ClientError, BotoCoreError,  ValueError) as e:
            logger.warning(f"Skipping {key}: {e}")
            return None

    def fetch_pothole_data(self) -> List[Dict]:
        """
        Walk all json sidecars, extract geodata and metadata,
        return list of pothole dicts ready for filtering
        """
        data: List[Dict] = []
        for key in self.list_json_sidecars():
            sidecar = self.fetch_sidecar(key)
            if not sidecar:
                continue

            ts  = sidecar.get("timestamp")
            gps = sidecar.get("gps", {})
            lat = gps.get("lat")
            lon = gps.get("lon")
            if ts is None or lat is None or lon is None:
                logger.warning(f"Skipping incomplete sidecar {key}")
                continue

                # split off the date-folder and base filename
            prefix, filename = key.rsplit('/', 1)            # e.g. "2025-5-01", "pothole_1746148157.json"
            base = filename.rsplit('.', 1)[0]    # e.g. "pothole_1746148157"

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

    def generate_presigned_post(self, key:str, content_type:str, expires_in: int = 3600) -> Dict:
        """
        Single-file upload presigned POST.
        """
        return self.svc.generate_presigned_post(
            Bucket=self.bucket,
            Key=key,
            Fields={"Content-Type" : content_type},
            Conditions=[{"Content-Type":content_type}],
            ExpiresIn=expires_in,
        )

    def delete_s3_directory(self, prefix: str):
        """
        Delete all objects under a prefix. Returns list of deleted metadata.
        """
        paginator = self.svc.get_paginator('list_objects_v2')
        to_delete = []
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix + '/'):
            for obj in page.get('Contents', []):
                to_delete.append({'Key': obj['Key']})

        if not to_delete:
            return []

        deleted = []
        for i in range(0, len(to_delete), 1000):
            batch = to_delete[i:i+1000]
            resp = self.svc.delete_objects(Bucket=self.bucket, Delete={'Objects': batch})
            deleted.extend(resp.get('Deleted', []))

        return deleted

    def presign_image_get(self, prefix:str, expires_in: int =3600) -> Optional[str]:
        response = self.svc.list_objects_v2(Bucket=self.bucket, Prefix=prefix)
        # Find the first matching image file
        for obj in response.get('Contents', []):
            key = obj['Key']
            if key.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
                return self.svc.generate_presigned_url(
                    ClientMethod='get_object',
                    Params={'Bucket': self.bucket, 'Key': key},
                    ExpiresIn=expires_in
                )

        return None
