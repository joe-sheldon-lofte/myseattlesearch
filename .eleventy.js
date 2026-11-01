// File: .eleventy.js
const fs = require('fs');
const path = require('path');

module.exports = function(eleventyConfig) {
  // Passthrough Asset Copies (strictly lowercase directory paths)
  eleventyConfig.addPassthroughCopy("style.css");
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

  // Universal Substring & Keyed Array Filter (resolves missing filter_contains error)
  eleventyConfig.addFilter("filter_contains", function(arr, property, targetValue) {
    if (!arr || !Array.isArray(arr)) return [];
    if (!property) return arr;

    // Single-argument array check: array | filter_contains("substring")
    if (targetValue === undefined) {
      const match = String(property).trim().toLowerCase();
      return arr.filter(item => String(item).toLowerCase().includes(match));
    }

    // Keyed object array check: array | filter_contains("tags", "sports-collegiate")
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