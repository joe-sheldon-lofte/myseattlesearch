# File: scripts/helpers/pull_r2_data.py
import os
import hashlib
import boto3
from botocore.client import Config

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
DATA_DIR = os.path.join(REPO_ROOT, "data")

def load_local_env():
    for env_file in [".env", ".dev.vars"]:
        env_path = os.path.join(REPO_ROOT, env_file)
        if os.path.exists(env_path):
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        k, v = line.split("=", 1)
                        k = k.strip()
                        if k and k not in os.environ:
                            os.environ[k] = v.strip().strip("\"'")
            except Exception:
                pass

def get_r2_client():
    account_id = (os.environ.get("CF_MASTER_ACCOUNT_ID") or os.environ.get("CF_ACCOUNT_ID") or "").strip()
    access_key = (
        os.environ.get("CF_MASTER_ACCESS_KEY_ID")
        or os.environ.get("R2_ALL_ACCESS_KEY_ID")
        or os.environ.get("R2_ALL_ACCESS_TOKEN")
        or os.environ.get("R2_ACCESS_KEY_ID")
        or ""
    ).strip()
    secret_key = (
        os.environ.get("CF_MASTER_SECRET_ACCESS_KEY")
        or os.environ.get("R2_ALL_SECRET_ACCESS_KEY")
        or os.environ.get("R2_SECRET_ACCESS_KEY")
        or ""
    ).strip()
    endpoint_url = (
        os.environ.get("CF_MASTER_S3_API_ENDPOINT")
        or os.environ.get("R2_ENDPOINT_URL")
        or (f"https://{account_id}.r2.cloudflarestorage.com" if account_id else "")
    ).strip()

    if not all([endpoint_url, access_key, secret_key]):
        return None

    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",
        config=Config(signature_version="s3v4")
    )

def local_md5(filepath):
    if not os.path.exists(filepath):
        return ""
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def pull_all_r2_data():
    load_local_env()
    data_bucket = (os.environ.get("R2_DATA_BUCKET_NAME") or "myseattlesearch-data").strip()
    r2 = get_r2_client()
    if not r2:
        raise RuntimeError("Missing R2 credentials (CF_MASTER_ACCESS_KEY_ID / R2_ALL_ACCESS_TOKEN).")

    os.makedirs(DATA_DIR, exist_ok=True)
    paginator = r2.get_paginator("list_objects_v2")
    downloaded = 0
    skipped = 0

    for page in paginator.paginate(Bucket=data_bucket):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if not key.endswith(".json") or key.startswith("staging/"):
                continue

            dest_path = os.path.join(DATA_DIR, key)
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)

            remote_etag = obj.get("ETag", "").strip('"')
            if "-" not in remote_etag and local_md5(dest_path) == remote_etag:
                skipped += 1
                continue

            r2.download_file(data_bucket, key, dest_path)
            downloaded += 1

    print(f"⬇️ R2 Data Pull ({data_bucket}): {downloaded} downloaded, {skipped} already up-to-date.")

if __name__ == "__main__":
    pull_all_r2_data()
