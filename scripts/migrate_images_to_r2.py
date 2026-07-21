import os
import io
import sys
import boto3
from botocore.config import Config
from PIL import Image

def main():
    # 1. Fetch Cloudflare R2 Environment Credentials
    account_id = os.environ.get("R2_ACCOUNT_ID")
    access_key = os.environ.get("R2_ACCESS_KEY_ID")
    secret_key = os.environ.get("R2_SECRET_ACCESS_KEY")
    bucket_name = os.environ.get("R2_BUCKET_NAME")

    if not all([account_id, access_key, secret_key, bucket_name]):
        print("❌ Error: Missing required Cloudflare R2 environment variables.")
        print("Please verify R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, and R2_BUCKET_NAME.")
        sys.exit(1)

    # 2. Initialize S3 / R2 Client
    r2_endpoint = f"https://{account_id}.r2.cloudflarestorage.com"
    s3_client = boto3.client(
        "s3",
        endpoint_url=r2_endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4"),
        region_name="auto"
    )

    # 3. Locate Target Assets Directory
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assets_dir = os.path.join(repo_root, "assets", "images")

    if not os.path.exists(assets_dir):
        print(f"❌ Assets directory not found at: {assets_dir}")
        sys.exit(1)

    supported_extensions = (".jpg", ".jpeg", ".png")
    mapping_results = []

    print(f"🚀 Scanning '{assets_dir}' for image assets...\n")

    # 4. Traverse & Convert Assets
    for filename in sorted(os.listdir(assets_dir)):
        ext = os.path.splitext(filename)[1].lower()
        if ext in supported_extensions:
            local_filepath = os.path.join(assets_dir, filename)
            stem = os.path.splitext(filename)[0]
            webp_filename = f"{stem}.webp"
            r2_key = f"repomove/{webp_filename}"

            try:
                # Open & Convert Image to WebP in memory
                with Image.open(local_filepath) as img:
                    if img.mode in ("RGBA", "P"):
                        img = img.convert("RGBA")
                    else:
                        img = img.convert("RGB")

                    output_buffer = io.BytesIO()
                    img.save(output_buffer, format="WEBP", quality=85, optimize=True)
                    webp_data = output_buffer.getvalue()

                # Upload to R2 with 1-Year Immutable Caching Headers
                s3_client.put_object(
                    Bucket=bucket_name,
                    Key=r2_key,
                    Body=webp_data,
                    ContentType="image/webp",
                    CacheControl="public, max-age=31536000, immutable"
                )

                old_rel_path = f"/assets/images/{filename}"
                new_r2_url = f"https://assets.myseattlesearch.com/{r2_key}"
                mapping_results.append((old_rel_path, new_r2_url))

                print(f"  ✓ Uploaded: {filename} ➔ {r2_key} ({len(webp_data) // 1024} KB)")

            except Exception as e:
                print(f"  ❌ Failed to process {filename}: {str(e)}")

    # 5. Output URL Search & Replace Cheat Sheet
    print("\n" + "="*80)
    print("📋 URL SEARCH & REPLACE CHEAT SHEET")
    print("="*80)
    print(f"{'LOCAL REPO PATH':<40} | {'NEW CLOUDFLARE R2 URL'}")
    print("-" * 80)
    for old_path, new_url in mapping_results:
        print(f"{old_path:<40} | {new_url}")
    print("="*80 + "\n")

if __name__ == "__main__":
    main()