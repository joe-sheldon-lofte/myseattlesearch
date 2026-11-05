# File: scripts/utilities/purge_r2_history.py

import os
import sys
import boto3
from botocore.config import Config

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
DEV_VARS_PATH = os.path.join(PROJECT_ROOT, ".dev.vars")

def load_dev_vars(filepath):
    env_vars = {}
    if not os.path.exists(filepath):
        print(f"[!] Secrets file not found at {filepath}")
        return env_vars
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                env_vars[k.strip()] = v.strip().strip("'").strip('"')
    return env_vars

config = load_dev_vars(DEV_VARS_PATH)

CF_ACCOUNT_ID = config.get("CF_ACCOUNT_ID")
R2_ACCESS_KEY_ID = config.get("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = config.get("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME = config.get("R2_BUCKET_NAME", "myseattlesearch-assets")

if not all([CF_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY]):
    print("[!] Missing R2 credentials in .dev.vars")
    sys.exit(1)

s3_client = boto3.client(
    "s3",
    endpoint_url=f"https://{CF_ACCOUNT_ID}.r2.cloudflarestorage.com",
    aws_access_key_id=R2_ACCESS_KEY_ID,
    aws_secret_access_key=R2_SECRET_ACCESS_KEY,
    config=Config(signature_version="s3v4")
)

def purge_history_folder():
    print(f"[*] Connecting to R2 bucket '{R2_BUCKET_NAME}'...")
    print("[*] Listing objects under prefix 'history/'...")
    
    deleted_count = 0
    continuation_token = None
    
    while True:
        list_kwargs = {
            "Bucket": R2_BUCKET_NAME,
            "Prefix": "history/",
            "MaxKeys": 1000
        }
        if continuation_token:
            list_kwargs["ContinuationToken"] = continuation_token
            
        resp = s3_client.list_objects_v2(**list_kwargs)
        contents = resp.get("Contents", [])
        
        if not contents:
            break
            
        delete_batch = [{"Key": obj["Key"]} for obj in contents]
        s3_client.delete_objects(
            Bucket=R2_BUCKET_NAME,
            Delete={"Objects": delete_batch, "Quiet": True}
        )
        
        deleted_count += len(delete_batch)
        print(f"    Purged {deleted_count} objects...")
        
        if resp.get("IsTruncated"):
            continuation_token = resp.get("NextContinuationToken")
        else:
            break

    print(f"[+] Clean Slate Complete: {deleted_count} historical assets removed from R2.")

if __name__ == "__main__":
    purge_history_folder()