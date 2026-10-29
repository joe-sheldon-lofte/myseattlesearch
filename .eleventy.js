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
  eleventyConfig.ignores.add(".github/");

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
      data: "data" // Auto-discovers all ./data/*.json as global objects
    }
  };
};