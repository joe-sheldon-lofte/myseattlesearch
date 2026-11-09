// File: .eleventy.js
const fs = require('fs');
const path = require('path');

module.exports = function(eleventyConfig) {
  // Passthrough Asset Copies (strictly lowercase directory paths)
  eleventyConfig.addPassthroughCopy("style.css");
  eleventyConfig.addPassthroughCopy("css");
  eleventyConfig.addPassthroughCopy("assets"); // Automatically passes through assets/js/*
  eleventyConfig.addPassthroughCopy("contact.vcf");
  eleventyConfig.addPassthroughCopy("data"); // Passthrough for browser runtime fetch operations
  eleventyConfig.addPassthroughCopy("quizzes/assets");
  eleventyConfig.addPassthroughCopy("quizzes/engines");
  eleventyConfig.addPassthroughCopy({ "scripts/utilities": "scripts/utilities" });

  // Optional CNAME passthrough handling
  if (fs.existsSync(path.join(__dirname, "cname"))) {
    eleventyConfig.addPassthroughCopy("cname");
  } else if (fs.existsSync(path.join(__dirname, "CNAME"))) {
    eleventyConfig.addPassthroughCopy("CNAME");
  }

  // Ignored Directories & Source Scripts
  eleventyConfig.ignores.add("scripts/*.py");
  eleventyConfig.ignores.add(".github/**");
  eleventyConfig.ignores.add("_deprecated/**");

  // Global Dynamic Variables (resolves {{ buildTime }} in footer.njk)
  eleventyConfig.addGlobalData("buildTime", () => {
    const now = new Date();
    const dateStr = new Intl.DateTimeFormat("en-US", {
      timeZone: "America/Los_Angeles",
      month: "short", 
      day: "numeric", 
      year: "numeric"
    }).format(now);
    const timeStr = new Intl.DateTimeFormat("en-US", {
      timeZone: "America/Los_Angeles",
      hour: "numeric", 
      minute: "2-digit", 
      timeZoneName: "short"
    }).format(now);
    return `${dateStr} at ${timeStr}`;
  });

  // Cloudflare R2 Storage Metric Hook
  eleventyConfig.addGlobalData("r2_storage", () => {
    const candidates = [
      path.join(__dirname, "_data", "r2_storage.json"),
      path.join(__dirname, "data", "r2_storage.json")
    ];
    for (const p of candidates) {
      if (fs.existsSync(p)) {
        try {
          return JSON.parse(fs.readFileSync(p, "utf-8"));
        } catch (e) {
          console.error("Error reading r2_storage.json:", e);
        }
      }
    }
    return { usedGB: "0.00" };
  });

  // Cloudflare D1 Social Notebook Data Hook
  eleventyConfig.addGlobalData("notebook", async () => {
    // 1. Ensure .env is read if Node hasn't pre-loaded it locally
    const envPath = path.join(__dirname, ".env");
    if (fs.existsSync(envPath)) {
      const rawEnv = fs.readFileSync(envPath, "utf-8");
      for (const line of rawEnv.split("\n")) {
        const trimmed = line.trim();
        if (!trimmed || trimmed.startsWith("#")) continue;
        const eqIdx = trimmed.indexOf("=");
        if (eqIdx > 0) {
          const key = trimmed.slice(0, eqIdx).trim();
          let val = trimmed.slice(eqIdx + 1).trim();
          if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'"))) {
            val = val.slice(1, -1);
          }
          if (!process.env[key]) process.env[key] = val;
        }
      }
    }

    const accountId = process.env.CF_ACCOUNT_ID;
    const databaseId = process.env.CF_D1_DATABASE_ID;
    const apiToken = process.env.CF_D1_API_TOKEN || process.env.CF_API_TOKEN;

    let rawPosts = [];

    // 2. Direct Query to Cloudflare D1 REST API
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
          console.warn(`[notebook] Cloudflare D1 HTTP ${response.status}:`, errText);
        }
      } catch (err) {
        console.warn("[notebook] Cloudflare D1 fetch error:", err.message);
      }
    }

    // 3. Optional local mock fallback if offline or empty
    if (rawPosts.length === 0) {
      const candidates = [
        path.join(__dirname, "data", "notebook.json"),
        path.join(__dirname, "_data", "notebook.json")
      ];
      for (const p of candidates) {
        if (fs.existsSync(p)) {
          try {
            rawPosts = JSON.parse(fs.readFileSync(p, "utf-8"));
            break;
          } catch (e) {}
        }
      }
    }

    // Defensive Guard: Always return an array so Eleventy's pagination never halts
    if (!Array.isArray(rawPosts) || rawPosts.length === 0) {
      return [];
    }

    // 4. Load publishers directory to match publisher_id
    let publishersIndex = {};
    const pubCandidates = [
      path.join(__dirname, "data", "publishers.json"),
      path.join(__dirname, "_data", "publishers.json")
    ];
    for (const pubPath of pubCandidates) {
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
  });

  // Universal Production Utility Filters
  eleventyConfig.addFilter("cssmin", function(code) {
    if (!code) return "";
    return code
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .replace(/\s+/g, " ")
      .replace(/\s*([\{\}\:\;\,])\s*/g, "$1")
      .replace(/;\}/g, "}")
      .trim();
  });

  eleventyConfig.addFilter("localeString", function(value) {
    if (value === null || value === undefined || value === "" || isNaN(value)) return "0";
    return Number(value).toLocaleString('en-US');
  });

  eleventyConfig.addFilter("postDate", function(dateObj) {
    if (!dateObj) return "";
    const date = new Date(dateObj);
    return new Intl.DateTimeFormat("en-US", {
      timeZone: "America/Los_Angeles",
      month: "long", 
      day: "numeric", 
      year: "numeric"
    }).format(date);
  });

  // Universal Substring & Keyed Array Filter
  eleventyConfig.addFilter("filter_contains", function(arr, property, targetValue) {
    if (!arr || !Array.isArray(arr)) return [];
    if (!property) return arr;

    if (targetValue === undefined) {
      const match = String(property).trim().toLowerCase();
      return arr.filter(item => String(item).toLowerCase().includes(match));
    }

    const match = String(targetValue).trim().toLowerCase();
    return arr.filter(item => {
      const val = item[property];
      if (!val) return false;
      if (Array.isArray(val)) {
        return val.some(entry => String(entry).toLowerCase().includes(match));
      }
      return String(val).toLowerCase().includes(match);
    });
  });

  // Sports Telemetry Filter
  eleventyConfig.addFilter("recentLevelGames", function(teams, level = "Professional", count = 6) {
    if (!teams || !Array.isArray(teams)) return [];

    const allGames = [];
    const targetLevel = String(level).trim().toLowerCase();

    teams
      .filter(team => String(team.level).trim().toLowerCase() === targetLevel && Array.isArray(team.recentGames))
      .forEach(team => {
        team.recentGames.forEach(game => {
          allGames.push({
            ...game,
            teamName: team.teamName,
            teamRecord: team.currentRecord || "",
            teamSite: team.teamSite || "",
            sport: team.sport || "Athletics"
          });
        });
      });

    allGames.sort((a, b) => new Date(b.game_date) - new Date(a.game_date));
    return allGames.slice(0, count);
  });

  // Collections (posts archive)
  eleventyConfig.addCollection("posts", function(collectionApi) {
    return collectionApi.getFilteredByGlob("posts/*.md");
  });

  // Canonical Eleventy Engine Configuration
  return {
    htmlTemplateEngine: false, 
    templateFormats: ["njk", "md"], 
    dir: {
      input: ".",          
      output: "_site",     
      includes: "_includes",
      data: "data"
    }
  };
};