module.exports = function(eleventyConfig) {
  // 1. Pass through universal styling and web components
  eleventyConfig.addPassthroughCopy("style.css");
  eleventyConfig.addPassthroughCopy("components.js");
  
  // 2. Pass through global assets and necessary root files
  eleventyConfig.addPassthroughCopy("assets");
  eleventyConfig.addPassthroughCopy("contact.vcf");
  eleventyConfig.addPassthroughCopy("CNAME");

  // 3. CRITICAL: Pass through the data folder untouched
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

  // --- GLOBAL BUILD TIMESTAMP SHORTCODE ---
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
    // Returns clean programmatic text output matching local time metrics
    return new Intl.DateTimeFormat('en-US', formattingRules).format(now).replace(',', ' at');
  });

  // Universal Number & Currency Formatting Filter
  eleventyConfig.addFilter("localeString", function(value) {
    if (!value) return "0";
    return Number(value).toLocaleString('en-US');
  });

  // --- DYNAMIC DISCLAIMER RESOLVER FILTER ---
  eleventyConfig.addFilter("getDisclaimer", function(pageUrl, disclaimers) {
    if (!disclaimers) return "";
    
    let pageName = pageUrl || "";
    if (pageName === "/" || pageName === "") {
      pageName = "index.html";
    } else {
      // Clean up the URL string format
      if (pageName.startsWith("/")) {
        pageName = pageName.substring(1);
      }
      if (pageName.endsWith("/")) {
        pageName = pageName.substring(0, pageName.length - 1);
      }
      // Map directory indexes (like /news/) to their parent category signature
      if (!pageName.includes(".html")) {
        const firstSegment = pageName.split('/')[0];
        pageName = firstSegment + ".html";
      }
    }
    
    return disclaimers[pageName] || "";
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