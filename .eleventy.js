/* File: .eleventy.js */

module.exports = function(eleventyConfig) {
  // 1. Pass through universal styling and web components
  eleventyConfig.addPassthroughCopy("style.css");
  eleventyConfig.addPassthroughCopy("components.js");
  
  // 2. Pass through global assets and necessary root files
  eleventyConfig.addPassthroughCopy("assets");
  eleventyConfig.addPassthroughCopy("contact.vcf");
  eleventyConfig.addPassthroughCopy("CNAME");

  // 3. CRITICAL: Pass through the data folder untouched. 
  eleventyConfig.addPassthroughCopy("data");

  // 4. Pass through headless quiz dependencies
  eleventyConfig.addPassthroughCopy("quizzes/assets");
  eleventyConfig.addPassthroughCopy("quizzes/engines");

  // 5. FORCE 1:1 HTML COPY
  eleventyConfig.addPassthroughCopy("*.html"); 
  eleventyConfig.addPassthroughCopy("quizzes/**/*.html");

  // 6. Explicitly ignore backend Python scripts and GitHub actions
  eleventyConfig.ignores.add("scripts/");
  eleventyConfig.ignores.add(".github/");

  // --- NEW: GLOBAL BUILD TIMESTAMP SHORTCODE ---
  eleventyConfig.addShortcode("buildTime", function() {
    const now = new Date();
    const formattingRules = {
      timeZone: 'America/Los_Angeles',
      year: 'numeric',
      month: 'long',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
      timeZoneName: 'short'
    };
    // Returns clean programmatic text output: "July 09, 2026 at 1:15 PM PDT"
    return new Intl.DateTimeFormat('en-US', formattingRules).format(now).replace(',', ' at');
  });

  return {
    htmlTemplateEngine: false, 
    templateFormats: ["njk", "md"], 
    
    dir: {
      input: ".",          
      output: "_site",     
      includes: "_includes"
    }
  };
};