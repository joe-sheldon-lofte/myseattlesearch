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

  // 5. Explicitly ignore backend Python scripts and GitHub actions
  eleventyConfig.ignores.add("scripts/");
  eleventyConfig.ignores.add(".github/");

  // --- GLOBAL BUILD TIMESTAMP SHORTCODE (Solves the "Double At" date bug) ---
  eleventyConfig.addShortcode("buildTime", function() {
    const now = new Date();
    
    // Pass A: Formats only the calendar date (e.g., "July 14, 2026")
    const dateStr = new Intl.DateTimeFormat("en-US", {
      timeZone: "America/Los_Angeles",
      month: "long",
      day: "numeric",
      year: "numeric"
    }).format(now);
    
    // Pass B: Formats only the clock time (e.g., "6:26 PM PDT")
    const timeStr = new Intl.DateTimeFormat("en-US", {
      timeZone: "America/Los_Angeles",
      hour: "numeric",
      minute: "2-digit",
      timeZoneName: "short"
    }).format(now);
    
    // Manually stitch together with a single, clean "at" string
    return `${dateStr} at ${timeStr}`;
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

  /**
   * Pure Build-Time Static Notebook Content Shortcode
   * Compiles flat semantic HTML cards based on type, tag, and quantity filters.
   * Eliminates client-side browser hydration and layout lag.
   */
  eleventyConfig.addShortcode("renderNotebook", function(collectionsAll, typeFilter = "", tagFilter = "", limit = 25) {
    // Robust layout detection ensures compatibility with normalized template strings
    let filteredItems = collectionsAll.filter(item => item.data.layout && item.data.layout.includes("post") && item.data.type);

    // Filter by individual post types if specified (supports comma-separated matching loops)
    if (typeFilter) {
      const allowedTypes = typeFilter.split(",").map(t => t.trim().toLowerCase());
      filteredItems = filteredItems.filter(item => allowedTypes.includes(item.data.type.toLowerCase()));
    }

    // Filter by hyper-local comma-separated tag parameters literal matching loops
    if (tagFilter) {
      const allowedTags = tagFilter.split(",").map(t => t.trim().toLowerCase());
      filteredItems = filteredItems.filter(item => {
        if (!item.data.tags) return false;
        const itemTags = item.data.tags.map(t => t.toLowerCase());
        return allowedTags.some(tag => itemTags.includes(tag));
      });
    }

    // Enforce strict chronological order (Newest first)
    filteredItems.sort((a, b) => new Date(b.data.date) - new Date(a.data.date));

    // Slice data output array to the requested limit parameter
    const limitedItems = filteredItems.slice(0, parseInt(limit, 10));

    if (limitedItems.length === 0) {
      return `<p style="text-align: center; color: var(--card-accent-color); font-style: italic; margin: 2rem 0;">No matching notebook entries found.</p>`;
    }

    // Generate flat, pre-compiled HTML markup structures
    let htmlOutput = `<div class="notebook-static-feed" style="max-width: 800px; margin: 0 auto; display: flex; flex-direction: column; gap: 2.5rem; width: 100%;">`;

    limitedItems.forEach(item => {
      const isPost = item.data.type.toLowerCase() === "post";
      const isNote = item.data.type.toLowerCase() === "note";
      const isArticle = item.data.type.toLowerCase() === "article";
      
      const absoluteUrl = `https://myseattlesearch.com${item.url}`;
      const chatRedirectUrl = `/chat/?reply_to=${item.fileSlug}`;

      // Format human-readable date display parameter
      const displayDate = new Date(item.data.date).toLocaleDateString("en-US", {
        year: "numeric",
        month: "long",
        day: "numeric"
      });

      // Construct conditional visual styles using central layout custom properties switchboard
      let cardStyle = `padding: 2rem; border-radius: 8px; width: 100%; box-sizing: border-box; text-align: left;`;
      if (isPost) {
        cardStyle += ` border: 3px solid var(--card-accent-color); background-color: var(--dynamic-bg-highlight); box-shadow: 0 4px 12px rgba(0,0,0,0.05); font-size: 1.15rem; font-weight: 500;`;
      } else {
        cardStyle += ` border: 1px solid rgba(0,0,0,0.1); background-color: #ffffff;`;
      }

      htmlOutput += `
        <article class="notebook-card type-${item.data.type.toLowerCase()}" style="${cardStyle}">
          <header style="margin-bottom: 1.25rem;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem; font-size: 0.85rem; color: rgba(0,0,0,0.6);">
              <span>By ${item.data.author || "Joe Sheldon"} • ${displayDate}</span>
              <span style="text-transform: uppercase; letter-spacing: 0.05em; font-weight: 700; color: var(--card-accent-color);">${item.data.type}</span>
            </div>
            <h2 style="margin: 0 0 0.5rem 0; font-size: ${isPost ? '1.75rem' : '1.5rem'}; line-height: 1.2; font-weight: 800; color: var(--premier-charcoal);">${item.data.title}</h2>
            ${item.data.headline && item.data.headline !== item.data.title ? `<h3 style="margin: 0 0 0.25rem 0; font-size: 1.15rem; font-weight: 600; opacity: 0.85; color: var(--premier-charcoal);">${item.data.headline}</h3>` : ''}
            ${item.data.subhead && item.data.subhead !== item.data.title ? `<p style="margin: 0; font-size: 1rem; font-style: italic; opacity: 0.75; color: var(--premier-charcoal);">${item.data.subhead}</p>` : ''}
          </header>
          
          <div class="notebook-body" style="line-height: 1.6; margin-bottom: 1.5rem; color: var(--premier-charcoal);">
      `;

      if (isArticle) {
        // Strip tags and compile down an automated clean teaser block for long articles
        const cleanContent = item.templateContent.replace(/<[^>]*>/g, '').trim();
        const teaserText = cleanContent.split(' ').slice(0, 40).join(' ') + '...';
        htmlOutput += `
          <p>${teaserText}</p>
          <div style="margin-top: 1rem;">
            <a href="${item.url}" style="display: inline-block; color: var(--card-accent-color); font-weight: 700; text-decoration: underline; text-underline-offset: 4px;">Read Full Article →</a>
          </div>
        `;
      } else {
        // Render content fully for posts and text notes
        htmlOutput += item.templateContent;
      }

      htmlOutput += `
          </div>
          
          <footer style="display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 1rem; border-top: 1px solid rgba(0,0,0,0.08); padding-top: 1.25rem;">
            <div class="interactive-actions" style="display: flex; gap: 1rem;">
              <button class="notebook-share-btn" data-url="${absoluteUrl}" data-title="${item.data.title}" style="background: none; border: 1px solid rgba(0,0,0,0.15); padding: 0.5rem 1rem; border-radius: 4px; font-weight: 600; cursor: pointer; display: flex; align-items: center; gap: 0.5rem; font-size: 0.9rem; transition: background 0.2s; color: var(--premier-charcoal);">
                🔄 Share / Repost
              </button>
              <a href="${chatRedirectUrl}" style="background: none; border: 1px solid rgba(0,0,0,0.15); padding: 0.5rem 1rem; border-radius: 4px; font-weight: 600; text-decoration: none; color: var(--premier-charcoal); display: flex; align-items: center; gap: 0.5rem; font-size: 0.9rem; transition: background 0.2s;">
                💬 Reply via Live Chat
              </a>
            </div>
            ${item.data.tags ? `
              <div class="notebook-tags" style="display: flex; gap: 0.5rem;">
                ${item.data.tags.map(tag => `<span style="background-color: rgba(0,0,0,0.05); font-size: 0.8rem; padding: 0.25rem 0.6rem; border-radius: 20px; font-weight: 500; color: var(--premier-charcoal);">#${tag}</span>`).join('')}
              </div>
            ` : ''}
          </footer>
        </article>
      `;
    });

    htmlOutput += `</div>`;
    return htmlOutput;
  });

  // --- AUTOMATED VIRTUAL NOTEBOOK COLLECTION ---
  // Targets the filesystem path directly to populate collections.posts flawlessly
  eleventyConfig.addCollection("posts", function(collectionApi) {
    return collectionApi.getFilteredByGlob("src/posts/*.md");
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