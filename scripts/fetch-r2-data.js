const fs = require("fs");
const path = require("path");
const {
  S3Client,
  ListObjectsV2Command,
  GetObjectCommand,
  PutObjectCommand
} = require("@aws-sdk/client-s3");

const BUCKET = process.env.R2_DATA_BUCKET_NAME;
const ENDPOINT = process.env.R2_ENDPOINT_URL;
const ACCESS_KEY_ID = process.env.R2_ALL_ACCESS_TOKEN;
const SECRET_ACCESS_KEY = process.env.R2_ALL_SECRET_ACCESS_KEY;

if (!BUCKET || !ENDPOINT || !ACCESS_KEY_ID || !SECRET_ACCESS_KEY) {
  console.error("Missing required R2 environment variables.");
  process.exit(1);
}

const s3 = new S3Client({
  region: "auto",
  endpoint: ENDPOINT,
  credentials: {
    accessKeyId: ACCESS_KEY_ID,
    secretAccessKey: SECRET_ACCESS_KEY
  }
});

const LOCAL_DATA_DIR = path.join(__dirname, "..", "data");

async function streamToBuffer(stream) {
  const chunks = [];
  for await (const chunk of stream) {
    chunks.push(Buffer.from(chunk));
  }
  return Buffer.concat(chunks);
}

async function listR2JsonKeys() {
  const keys = new Set();
  let continuationToken;
  do {
    const res = await s3.send(
      new ListObjectsV2Command({
        Bucket: BUCKET,
        Prefix: "data/",
        ContinuationToken: continuationToken
      })
    );
    for (const item of res.Contents || []) {
      if (item.Key && item.Key.endsWith(".json")) {
        keys.add(item.Key);
      }
    }
    continuationToken = res.IsTruncated ? res.NextContinuationToken : undefined;
  } while (continuationToken);
  return keys;
}

async function main() {
  fs.mkdirSync(LOCAL_DATA_DIR, { recursive: true });
  const r2Keys = await listR2JsonKeys();

  // One-time seed: upload any local data/*.json files not yet in R2 data/
  const localFiles = fs.readdirSync(LOCAL_DATA_DIR).filter(f => f.endsWith(".json"));
  for (const file of localFiles) {
    const r2Key = `data/${file}`;
    if (!r2Keys.has(r2Key)) {
      const body = fs.readFileSync(path.join(LOCAL_DATA_DIR, file));
      await s3.send(
        new PutObjectCommand({
          Bucket: BUCKET,
          Key: r2Key,
          Body: body,
          ContentType: "application/json"
        })
      );
      r2Keys.add(r2Key);
      console.log(`Seeded ${r2Key} to R2.`);
    }
  }

  // Download all data/*.json files from R2 into ./data/
  for (const key of r2Keys) {
    const fileName = key.replace(/^data\//, "");
    if (!fileName || fileName.includes("/")) continue;
    const obj = await s3.send(new GetObjectCommand({ Bucket: BUCKET, Key: key }));
    const buf = await streamToBuffer(obj.Body);
    fs.writeFileSync(path.join(LOCAL_DATA_DIR, fileName), buf);
    console.log(`Synced ${key} -> data/${fileName}`);
  }
}

main().catch(err => {
  console.error("R2 Data Sync Failed:", err);
  process.exit(1);
});
