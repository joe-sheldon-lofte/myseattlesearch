import os
import json
import io
import requests
import boto3
from PIL import Image
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_PATH = os.path.join(DATA_DIR, "weekly_sports.json")

# Cloudflare R2 S3 Credentials from Environment
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY")
R2_ENDPOINT_URL = os.environ.get("R2_ENDPOINT_URL")
R2_BUCKET_NAME = os.environ.get("R2_BUCKET_NAME")

def get_r2_client():
    """Build boto3 S3 client for Cloudflare R2 if secrets are present."""
    if R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY and R2_ENDPOINT_URL:
        try:
            return boto3.client(
                "s3",
                endpoint_url=R2_ENDPOINT_URL,
                aws_access_key_id=R2_ACCESS_KEY_ID,
                aws_secret_access_key=R2_SECRET_ACCESS_KEY,
                region_name="auto"
            )
        except Exception as e:
            print(f"⚠️ Failed to initialize R2 client: {e}")
    return None

def process_and_upload_logo(s3_client, logo_url, team_slug):
    """Download logo, convert to WebP using Pillow, upload to R2, return new URL."""
    if not logo_url or not s3_client or not R2_BUCKET_NAME:
        return logo_url  # Fallback to source URL if R2 isn't configured

    r2_key = f"sports/logos/{team_slug}.webp"
    
    try:
        # 1. Download image
        res = requests.get(logo_url, timeout=10)
        if res.status_code != 200:
            return logo_url
            
        # 2. Convert to WebP using Pillow
        img = Image.open(io.BytesIO(res.content)).convert("RGBA")
        webp_buffer = io.BytesIO()
        img.save(webp_buffer, format="WEBP", quality=85)
        webp_buffer.seek(0)

        # 3. Upload to Cloudflare R2 (overwrites existing object in-place)
        s3_client.put_object(
            Bucket=R2_BUCKET_NAME,
            Key=r2_key,
            Body=webp_buffer,
            ContentType="image/webp",
            CacheControl="public, max-age=31536000, immutable"
        )

        # 4. Construct Public CDN URL
        public_url = f"https://assets.myseattlesearch.com/{r2_key}"
        print(f"   🖼️ Converted & uploaded logo to R2: {r2_key}")
        return public_url

    except Exception as e:
        print(f"   ⚠️ Logo process notice for {team_slug}: {e}")
        return logo_url

def main():
    print("📅 Starting Weekly Sports Metadata & Logo Pipeline...")
    s3_client = get_r2_client()

    # Base PNW Team Definitions
    teams_meta = [
        {"teamName": "Seattle Seahawks", "slug": "seattle-seahawks", "sport": "Football", "level": "Professional", "gender": "Men", "homeFacilityName": "Lumen Field", "facilityCity": "Seattle", "facilityCoordinates": "47.5952, -122.3316", "logo_src": "https://assets-sports-gcp.thescore.com/football/team/24/logo.png"},
        {"teamName": "Seattle Mariners", "slug": "seattle-mariners", "sport": "Baseball", "level": "Professional", "gender": "Men", "homeFacilityName": "T-Mobile Park", "facilityCity": "Seattle", "facilityCoordinates": "47.5914, -122.3323", "logo_src": "https://www.mlbstatic.com/team-logos/136.svg"},
        {"teamName": "Seattle Kraken", "slug": "seattle-kraken", "sport": "Hockey", "level": "Professional", "gender": "Men", "homeFacilityName": "Climate Pledge Arena", "facilityCity": "Seattle", "facilityCoordinates": "47.6221, -122.3540", "logo_src": "https://assets.nhle.com/logos/nhl/svg/SEA_light.svg"},
        {"teamName": "Seattle Sounders FC", "slug": "seattle-sounders-fc", "sport": "Soccer", "level": "Professional", "gender": "Men", "homeFacilityName": "Lumen Field", "facilityCity": "Seattle", "facilityCoordinates": "47.5952, -122.3316", "logo_src": "https://assets-sports-gcp.thescore.com/soccer/team/1004/logo.png"},
        {"teamName": "Seattle Storm", "slug": "seattle-storm", "sport": "Basketball", "level": "Professional", "gender": "Women", "homeFacilityName": "Climate Pledge Arena", "facilityCity": "Seattle", "facilityCoordinates": "47.6221, -122.3540", "logo_src": "https://assets-sports-gcp.thescore.com/basketball/team/wnba/sea/logo.png"},
        {"teamName": "Seattle Reign FC", "slug": "seattle-reign-fc", "sport": "Soccer", "level": "Professional", "gender": "Women", "homeFacilityName": "Lumen Field", "facilityCity": "Seattle", "facilityCoordinates": "47.5952, -122.3316", "logo_src": "https://assets-sports-gcp.thescore.com/soccer/team/18525/logo.png"},
        {"teamName": "Tacoma Rainiers", "slug": "tacoma-rainiers", "sport": "Baseball", "level": "Minor League", "gender": "Men", "homeFacilityName": "Cheney Stadium", "facilityCity": "Tacoma", "facilityCoordinates": "47.2383, -122.4936", "logo_src": "https://www.mlbstatic.com/team-logos/529.svg"},
        {"teamName": "Washington Huskies", "slug": "washington-huskies", "sport": "Multi-Sport", "level": "College (NCAA D1)", "gender": "Coed", "homeFacilityName": "Husky Stadium", "facilityCity": "Seattle", "facilityCoordinates": "47.6503, -122.3016", "logo_src": "https://a.espncdn.com/i/teamlogos/ncaa/500/264.png"},
        {"teamName": "Washington State Cougars", "slug": "washington-state-cougars", "sport": "Multi-Sport", "level": "College (NCAA D1)", "gender": "Coed", "homeFacilityName": "Gesa Field", "facilityCity": "Pullman", "facilityCoordinates": "46.7320, -117.1600", "logo_src": "https://a.espncdn.com/i/teamlogos/ncaa/500/265.png"},
        {"teamName": "Gonzaga Bulldogs", "slug": "gonzaga-bulldogs", "sport": "Basketball", "level": "College (NCAA D1)", "gender": "Coed", "homeFacilityName": "McCarthey Athletic Center", "facilityCity": "Spokane", "facilityCoordinates": "47.6669, -117.4025", "logo_src": "https://a.espncdn.com/i/teamlogos/ncaa/500/2250.png"}
    ]

    processed_teams = []
    for t in teams_meta:
        print(f"Processing {t['teamName']}...")
        r2_logo_url = process_and_upload_logo(s3_client, t.get("logo_src"), t["slug"])
        
        t_clean = dict(t)
        t_clean["logo"] = r2_logo_url
        t_clean.pop("logo_src", None)
        processed_teams.append(t_clean)

    output = {
        "last_updated_utc": datetime.now(timezone.utc).isoformat(),
        "total_teams": len(processed_teams),
        "teams": processed_teams
    }

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"✅ Saved clean weekly sports metadata & logos to {OUTPUT_PATH}")

if __name__ == "__main__":
    main()