# File: scripts/helpers/push_r2_data.py
import os
import sys
import hashlib
import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

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
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def push_all_r2_data():
    load_local_env()
    data_bucket = (os.environ.get("R2_DATA_BUCKET_NAME") or "myseattlesearch-data").strip()
    r2 = get_r2_client()
    if not r2:
        raise RuntimeError("Missing R2 credentials (CF_MASTER_ACCESS_KEY_ID / R2_ALL_ACCESS_TOKEN).")

    if not os.path.exists(DATA_DIR):
        print("⚠️ No data/ directory found. Nothing to push.")
        return 0

    uploaded = 0
    unchanged = 0

    for root, dirs, files in os.walk(DATA_DIR):
        dirs[:] = [d for d in dirs if d != "staging"]
        for fname in files:
            if not fname.endswith(".json"):
                continue

            full_path = os.path.join(root, fname)
            rel_key = os.path.relpath(full_path, DATA_DIR).replace("\\", "/")
            file_hash = local_md5(full_path)

            try:
                head = r2.head_object(Bucket=data_bucket, Key=rel_key)
                remote_etag = head.get("ETag", "").strip('"')
                if "-" not in remote_etag and remote_etag == file_hash:
                    unchanged += 1
                    continue
            except ClientError:
                pass

            r2.upload_file(
                full_path,
                data_bucket,
                rel_key,
                ExtraArgs={"ContentType": "application/json"}
            )
            uploaded += 1
            print(f"   ☁️ Pushed {rel_key} ➔ {data_bucket}")

    print(f"⬆️ R2 Data Push ({data_bucket}): {uploaded} uploaded, {unchanged} unchanged.")

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as gh_out:
            gh_out.write(f"r2_uploaded_count={uploaded}\n")

    return uploaded

if __name__ == "__main__":
    push_all_r2_data()
