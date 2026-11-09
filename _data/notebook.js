// File: _data/notebook.js
const fs = require("fs");
const path = require("path");

module.exports = async function() {
  let rawPosts = [];

  // 1. Fetch from D1 via Cloudflare REST API or Worker API
  const accountId = process.env.CLOUDFLARE_ACCOUNT_ID;
  const databaseId = process.env.CLOUDFLARE_D1_DATABASE_ID;
  const apiToken = process.env.CLOUDFLARE_D1_API_TOKEN;
  const workerEndpoint = process.env.CMS_NOTEBOOK_API_URL;

  if (workerEndpoint) {
    try {
      const res = await fetch(workerEndpoint);
      if (res.ok) rawPosts = await res.json();
    } catch (err) {
      console.warn("[notebook.js] Worker endpoint fetch failed:", err.message);
    }
  } else if (accountId && databaseId && apiToken) {
    try {
      const url = `https://api.cloudflare.com/client/v4/accounts/${accountId}/d1/database/${databaseId}/raw`;
      const res = await fetch(url, {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${apiToken}`,
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          sql: "SELECT * FROM notebook WHERE hold_status = 'active' ORDER BY datetime(published_at) DESC"
        })
      });

      if (res.ok) {
        const json = await res.json();
        const results = json.result?.[0]?.results;
        if (results && results.columns && results.rows) {
          rawPosts = results.rows.map(row => {
            const entry = {};
            results.columns.forEach((col, idx) => { entry[col] = row[idx]; });
            return entry;
          });
        }
      }
    } catch (err) {
      console.warn("[notebook.js] Cloudflare D1 direct API fetch failed:", err.message);
    }
  }

  // Fallback: Check for local mock or cached file
  if (!rawPosts || rawPosts.length === 0) {
    const localFallback = path.join(__dirname, "notebook.json");
    if (fs.existsSync(localFallback)) {
      try {
        rawPosts = JSON.parse(fs.readFileSync(localFallback, "utf-8"));
      } catch (e) {}
    }
  }

  // If no posts are retrieved, return an empty array to prevent Eleventy pagination crash
  if (!Array.isArray(rawPosts) || rawPosts.length === 0) {
    console.warn("[notebook.js] No notebook posts retrieved. Returning empty array.");
    return [];
  }

  // 2. Load and index publishers from data/publishers.json
  let publishersIndex = {};
  const pubPath = path.join(process.cwd(), "data", "publishers.json");
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
    } catch (e) {
      console.warn("[notebook.js] Error reading publishers.json:", e.message);
    }
  }

  // 3. Normalize JSON string fields and join publisher data
  return rawPosts.map(post => {
    const parseField = (val) => {
      if (typeof val === "string") {
        try { return JSON.parse(val); } catch (e) { return []; }
      }
      return val || [];
    };

    const images = parseField(post.images);
    const attachments = parseField(post.attachments);
    const externalLinks = parseField(post.external_links);
    const cities = parseField(post.cities);

    const pub = publishersIndex[post.publisher_id];

    return {
      id: post.id,
      slug: post.slug,
      title: post.title,
      body: post.body,
      hold_status: post.hold_status || "active",
      published_at: post.published_at,
      updated_at: post.updated_at,
      cities: cities,
      images: images,
      attachments: attachments,
      external_links: externalLinks,
      author: pub ? (pub.name || pub.full_name) : "Joe Sheldon",
      author_role: pub ? pub.role : "Redfin Senior Agent",
      author_image: pub ? (pub.avatar || pub.image) : "/assets/brand/joe-sheldon-headshot.webp"
    };
  });
};