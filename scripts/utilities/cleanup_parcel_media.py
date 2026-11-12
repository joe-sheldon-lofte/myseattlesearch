import os
import boto3
import httpx


def load_dev_vars(root_dir):
    for env_name in [".dev.vars", ".env"]:
        dev_vars_path = os.path.join(root_dir, env_name)
        if os.path.exists(dev_vars_path):
            with open(dev_vars_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def purge_r2_parcels_prefix(s3_client, bucket_name, prefix="parcels/"):
    print(f"🧹 Scanning R2 bucket '{bucket_name}' under prefix '{prefix}' (leaving 'history/' untouched)...")
    paginator = s3_client.get_paginator("list_objects_v2")
    total_deleted = 0

    for page in paginator.paginate(Bucket=bucket_name, Prefix=prefix):
        contents = page.get("Contents", [])
        if not contents:
            continue

        batch = [{"Key": obj["Key"]} for obj in contents]
        for i in range(0, len(batch), 1000):
            chunk = batch[i:i + 1000]
            s3_client.delete_objects(
                Bucket=bucket_name,
                Delete={"Objects": chunk, "Quiet": True},
            )
            total_deleted += len(chunk)
            print(f"\r   Deleted R2 objects: {total_deleted:,}", end="", flush=True)

    print(f"\n✅ R2 cleanup complete. Total objects removed under '{prefix}': {total_deleted:,}")


def purge_d1_parcel_media(endpoint, headers):
    print("🧹 Clearing 'parcel_media' table in Cloudflare D1...")
    res = httpx.post(
        endpoint,
        headers=headers,
        json={"sql": "DELETE FROM parcel_media;"},
        timeout=60.0,
    )
    data = res.json()
    if not data.get("success"):
        raise RuntimeError(f"D1 cleanup failed: {data.get('errors', [])}")
    meta = data.get("result", [{}])[0].get("meta", {})
    changes = meta.get("changes", 0)
    print(f"✅ D1 'parcel_media' table cleared ({changes:,} rows deleted).")


def reset_local_checkpoints(staging_dir):
    for db_name in ["snoco_harvest.db", "kc_harvest.db"]:
        db_path = os.path.join(staging_dir, db_name)
        if os.path.exists(db_path):
            os.remove(db_path)
            print(f"🗑️ Removed local checkpoint file: {db_path}")


def main():
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    staging_dir = os.path.join(base_dir, "data", "staging")
    load_dev_vars(base_dir)

    cf_account_id = os.environ.get("CF_ACCOUNT_ID")
    cf_api_token = os.environ.get("CF_D1_API_TOKEN")
    cf_db_id = os.environ.get("CF_DATABASE_PARCELDATA_ID")
    r2_access_key = os.environ.get("R2_ACCESS_KEY_ID")
    r2_secret_key = os.environ.get("R2_SECRET_ACCESS_KEY")
    r2_bucket = os.environ.get("R2_BUCKET_NAME")

    if not all([cf_account_id, cf_api_token, cf_db_id, r2_access_key, r2_secret_key, r2_bucket]):
        raise ValueError("Missing Cloudflare D1 or R2 credentials in .dev.vars.")

    s3_client = boto3.client(
        "s3",
        endpoint_url=f"https://{cf_account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=r2_access_key,
        aws_secret_access_key=r2_secret_key,
        region_name="auto",
    )

    endpoint = f"https://api.cloudflare.com/client/v4/accounts/{cf_account_id}/d1/database/{cf_db_id}/query"
    headers = {
        "Authorization": f"Bearer {cf_api_token}",
        "Content-Type": "application/json",
    }

    purge_r2_parcels_prefix(s3_client, r2_bucket, prefix="parcels/")
    purge_d1_parcel_media(endpoint, headers)
    reset_local_checkpoints(staging_dir)
    print("✨ Cleanup finished. 'base' parcel attributes and R2 'history/' assets remain intact.")


if __name__ == "__main__":
    main()