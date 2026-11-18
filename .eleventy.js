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

  // Collection & Array Utility Filters (Jinja2-compatible helpers for Nunjucks widgets)
  eleventyConfig.addFilter("filter_by", function(collection, keyOrObj, value) {
    if (!collection) return [];
    const items = Array.isArray(collection)
      ? collection
      : (typeof collection === "object" ? Object.values(collection) : []);

    if (keyOrObj && typeof keyOrObj === "object") {
      return items.filter(item =>
        item && Object.entries(keyOrObj).every(([k, v]) => String(item[k]) === String(v))
      );
    }

    if (typeof keyOrObj === "string") {
      if (value === undefined) {
        return items.filter(item => item && Boolean(item[keyOrObj]));
      }
      return items.filter(item => item && String(item[keyOrObj]) === String(value));
    }

    return items;
  });

  eleventyConfig.addFilter("map", function(collection, attrOrOpts) {
    if (!collection) return [];
    const items = Array.isArray(collection)
      ? collection
      : (typeof collection === "object" ? Object.values(collection) : []);

    const key = typeof attrOrOpts === "string"
      ? attrOrOpts
      : (attrOrOpts && typeof attrOrOpts === "object" ? attrOrOpts.attribute : null);

    if (!key) return items;
    return items.map(item => (item && item[key] !== undefined ? item[key] : null));
  });

  eleventyConfig.addFilter("unique", function(arr) {
    if (!arr) return [];
    const items = Array.isArray(arr) ? arr : Object.values(arr);
    return Array.from(new Set(items.filter(v => v !== null && v !== undefined && v !== "")));
  });

  eleventyConfig.addFilter("unique_by", function(arr, key) {
    if (!arr || !Array.isArray(arr)) return [];
    if (!key) return Array.from(new Set(arr));
    const seen = new Set();
    return arr.filter(item => {
      if (!item || item[key] === undefined || item[key] === null) return false;
      const val = String(item[key]);
      if (seen.has(val)) return false;
      seen.add(val);
      return true;
    });
  });

  eleventyConfig.addFilter("sort_by", function(arr, key, reverse = false) {
    if (!arr) return [];
    const items = Array.isArray(arr) ? [...arr] : Object.values(arr);
    items.sort((a, b) => {
      const va = a && key ? a[key] : a;
      const vb = b && key ? b[key] : b;
      if (va === vb) return 0;
      if (va === null || va === undefined) return 1;
      if (vb === null || vb === undefined) return -1;
      if (typeof va === "number" && typeof vb === "number") {
        return reverse ? vb - va : va - vb;
      }
      const cmp = String(va).localeCompare(String(vb), "en", { numeric: true, sensitivity: "base" });
      return reverse ? -cmp : cmp;
    });
    return items;
  });

  eleventyConfig.addFilter("sort_by_date_desc", function(arr, key = "game_date") {
    if (!arr || !Array.isArray(arr)) return [];
    return [...arr].sort((a, b) => new Date(b && b[key] ? b[key] : 0) - new Date(a && a[key] ? a[key] : 0));
  });

  eleventyConfig.addFilter("find_by", function(arr, key, value) {
    if (!arr) return null;
    const items = Array.isArray(arr) ? arr : Object.values(arr);
    return items.find(item => item && String(item[key]) === String(value)) || null;
  });

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

  // Publisher Dynamic Lookup Filter (Option A - No fallback / Truth in Data)
  eleventyConfig.addFilter("getPublisher", function(publisherId, publishers) {
    if (!publisherId || !publishers) return null;
    const list = Array.isArray(publishers) ? publishers : Object.values(publishers);
    return list.find(p => String(p.id || p.publisher_id || p.pro_id) === String(publisherId)) || null;
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

  // Dynamic Metro & State SVG Coordinate Resolver (reads data/us_metro_coords.json)
  let metroCoordsCache = null;
  eleventyConfig.addFilter("resolveMetroPoint", function(regionName) {
    if (!metroCoordsCache) {
      const coordsPath = path.join(__dirname, "data", "us_metro_coords.json");
      if (fs.existsSync(coordsPath)) {
        try {
          metroCoordsCache = JSON.parse(fs.readFileSync(coordsPath, "utf-8"));
        } catch (e) {
          console.error("Error reading us_metro_coords.json:", e);
          metroCoordsCache = {};
        }
      } else {
        metroCoordsCache = {};
      }
    }

    if (!regionName) return null;
    const clean = String(regionName).trim();
    if (metroCoordsCache[clean]) return metroCoordsCache[clean];

    const stateMatch = clean.match(/,\s*([A-Z]{2})$/);
    if (stateMatch && metroCoordsCache[stateMatch[1]]) {
      return metroCoordsCache[stateMatch[1]];
    }
    return null;
  });

  // Custom Nunjucks Test: Jinja2 "none" compatibility for widget partials
  eleventyConfig.amendLibrary("njk", function(njkEnv) {
    njkEnv.addTest("none", function(value) {
      return value === null || value === undefined || value === "";
    });
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
