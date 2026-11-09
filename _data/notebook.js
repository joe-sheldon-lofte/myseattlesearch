// File: data/notebook.js
import fs from "node:fs";
import path from "node:path";

// Zero-dependency .env loader for local development
function ensureEnvLoaded() {
  const envPath = path.join(process.cwd(), ".env");
  if (fs.existsSync(envPath)) {
    const raw = fs.readFileSync(envPath, "utf-8");
    for (const line of raw.split("\n")) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith("#")) continue;
      const eqIdx = trimmed.indexOf("=");
      if (eqIdx > 0) {
        const key = trimmed.slice(0, eqIdx).trim();
        let val = trimmed.slice(eqIdx + 1).trim();
        if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'"))) {
          val = val.slice(1, -1);
        }
        if (!process.env[key]) {
          process.env[key] = val;
        }
      }
    }
  }
}

export default async function() {
  ensureEnvLoaded();

  const accountId = process.env.CF_ACCOUNT_ID;
  const databaseId = process.env.CF_D1_DATABASE_ID;
  const apiToken = process.env.CF_D1_API_TOKEN || process.env.CF_API_TOKEN;

  let rawPosts = [];

  // Direct Cloudflare D1 Query
  if (accountId && databaseId && apiToken) {
    try {
      const url = `https://api.cloudflare.com/client/v4/accounts/${accountId}/d1/database/${databaseId}/query`;
      const response = await fetch(url, {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${apiToken}`,
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          sql: "SELECT * FROM notebook WHERE hold_status = 'active' ORDER BY published_at DESC;"
        })
      });

      if (response.ok) {
        const json = await response.json();
        const results = json.result?.[0]?.results;
        if (Array.isArray(results)) {
          rawPosts = results;
        }
      } else {
        const errText = await response.text();
        console.warn(`[notebook.js] Cloudflare D1 HTTP ${response.status}:`, errText);
      }
    } catch (err) {
      console.warn("[notebook.js] Cloudflare D1 fetch error:", err.message);
    }
  } else {
    console.warn("[notebook.js] Missing Cloudflare D1 environment variables. Check .env configuration.");
  }

  // Fallback to local mock if database is offline or empty
  if (rawPosts.length === 0) {
    const fallbackLocations = [
      path.join(process.cwd(), "data", "notebook.json"),
      path.join(process.cwd(), "_data", "notebook.json")
    ];
    for (const p of fallbackLocations) {
      if (fs.existsSync(p)) {
        try {
          rawPosts = JSON.parse(fs.readFileSync(p, "utf-8"));
          break;
        } catch (e) {}
      }
    }
  }

  // Defensive Guard: Never return undefined. An empty array allows Eleventy to compile cleanly.
  if (!Array.isArray(rawPosts) || rawPosts.length === 0) {
    return [];
  }

  // Load publishers directory to match publisher_id
  let publishersIndex = {};
  const pubLocations = [
    path.join(process.cwd(), "data", "publishers.json"),
    path.join(process.cwd(), "_data", "publishers.json")
  ];
  for (const pubPath of pubLocations) {
    if (fs.existsSync(pubPath)) {
      try {
        const pubData = JSON.parse(fs.readFileSync(pubPath, "utf-8"));
        if (Array.isArray(pubData)) {
          pubData.forEach(p => {
            const key = p.id || p.publisher_id || p.pro_id;
            if (key) publishersIndex[key] = p;
          });
        } else if (typeof pubData === "object") {
          publishersIndex = pubData;
        }
        break;
      } catch (e) {}
    }
  }

  // Parse JSON fields and bind publisher profiles
  const parseJson = (val) => {
    if (typeof val === "string") {
      try { return JSON.parse(val); } catch (e) { return []; }
    }
    return val || [];
  };

  return rawPosts.map(post => {
    const pub = publishersIndex[post.publisher_id];
    return {
      id: post.id,
      slug: post.slug,
      title: post.title,
      body: post.body,
      hold_status: post.hold_status || "active",
      published_at: post.published_at,
      updated_at: post.updated_at,
      cities: parseJson(post.cities),
      images: parseJson(post.images),
      attachments: parseJson(post.attachments),
      external_links: parseJson(post.external_links),
      author: pub ? (pub.name || pub.full_name) : "Joe Sheldon",
      author_role: pub ? pub.role : "Redfin Senior Agent",
      author_image: pub ? (pub.avatar || pub.image) : "/assets/brand/joe-sheldon-headshot.webp"
    };
  });
}