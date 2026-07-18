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

  // --- GLOBAL BUILD TIMESTAMP SHORTCODE ---
  eleventyConfig.addShortcode("buildTime", function() {
    const now = new Date();
    
    const dateStr = new Intl.DateTimeFormat("en-US", {
      timeZone: "America/Los_Angeles",
      month: "long",
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

  // Universal Number & Currency Formatting Filter
  eleventyConfig.addFilter("localeString", function(value) {
    if (!value) return "0";
    return Number(value).toLocaleString('en-US');
  });

  // --- STATIC POST CALENDAR DATE COMPILER ---
  // Fixes the wildly long machine-clock timestamp strings at build time
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

  // --- DYNAMIC DISCLAIMER RESOLVER FILTER ---
  eleventyConfig.addFilter("getDisclaimer", function(pageUrl, disclaimers) {
    if (!disclaimers) return "";
    
    let pageName = pageUrl || "";
    if (pageName === "/" || pageName === "") {
      pageName = "index.html";
    } else {
      if (pageName.startsWith("/")) {
        pageName = pageName.substring(1);
      }
      if (pageName.endsWith("/")) {
        pageName = pageName.substring(0, pageName.length - 1);
      }
      if (!pageName.includes(".html")) {
        const firstSegment = pageName.split('/')[0];
        pageName = firstSegment + ".html";
      }
    }
    
    return disclaimers[pageName] || "";
  });

  /**
   * Pure Build-Time Static Notebook Content Shortcode
   * Mirrors the exact visibility rules, button designs, and typography profiles 
   * of the master pagination timeline engine to ensure uniform layout alignment.
   */
  eleventyConfig.addShortcode("renderNotebook", function(collectionsAll, typeFilter = "", tagFilter = "", limit = 25) {
    let filteredItems = collectionsAll.filter(item => item.data.layout && item.data.layout.includes("post") && item.data.type);

    if (typeFilter) {
      const allowedTypes = typeFilter.split(",").map(t => t.trim().toLowerCase());
      filteredItems = filteredItems.filter(item => allowedTypes.includes(item.data.type.toLowerCase()));
    }

    if (tagFilter) {
      const allowedTags = tagFilter.split(",").map(t => t.trim().toLowerCase());
      filteredItems = filteredItems.filter(item => {
        if (!item.data.tags) return false;
        const itemTags = item.data.tags.map(t => t.toLowerCase());
        return allowedTags.some(tag => itemTags.includes(tag));
      });
    }

    filteredItems.sort((a, b) => new Date(b.data.date) - new Date(a.data.date));
    const limitedItems = filteredItems.slice(0, parseInt(limit, 10));

    if (limitedItems.length === 0) {
      return `<p style="text-align: center; color: var(--card-accent-color); font-style: italic; margin: 2rem 0;">No matching notebook entries found.</p>`;
    }

    let htmlOutput = `<div class="notebook-static-feed" style="max-width: 800px; margin: 0 auto; display: flex; flex-direction: column; gap: 2rem; width: 100%;">`;

    limitedItems.forEach(item => {
      const typeLower = item.data.type.toLowerCase();
      const isPost = typeLower === "post";
      const isNote = typeLower === "note";
      const isArticle = typeLower === "article";
      
      const absoluteUrl = `https://myseattlesearch.com${item.url}`;
      const chatRedirectUrl = `/chat/?reply_to=${item.fileSlug}`;

      const displayDate = new Date(item.data.date).toLocaleDateString("en-US", {
        timeZone: "America/Los_Angeles",
        year: "numeric",
        month: "long",
        day: "numeric"
      });

      let cardStyle = `border-radius: 8px; width: 100%; box-sizing: border-box; text-align: left; transition: transform 0.2s;`;
      let navLabel = "View Entry →";

      if (isPost) {
        cardStyle += ` padding: 1.5rem; border: 3px solid var(--card-accent-color); background-color: var(--dynamic-bg-highlight); font-size: 1.15rem; font-weight: 600; line-height: 1.5;`;
        navLabel = "View Post →";
      } else if (isNote) {
        cardStyle += ` padding: 2rem; border: 1px solid rgba(0,0,0,0.15); background-color: #ffffff; font-size: 1.05rem;`;
        navLabel = "View Note →";
      } else if (isArticle) {
        cardStyle += ` padding: 2.5rem; border: 1px solid rgba(0,0,0,0.1); background-color: #ffffff; font-size: 1rem;`;
        navLabel = "Read Full Article →";
      }

      htmlOutput += `
        <article class="notebook-card type-${typeLower}" style="${cardStyle}">
          <header style="margin-bottom: 1rem; border-bottom: 1px solid rgba(0,0,0,0.05); padding-bottom: 0.75rem;">
            <div style="display: flex; justify-content: space-between; align-items: center; font-size: 0.85rem; color: rgba(0,0,0,0.6);">
              <span>By ${item.data.author || "Joe Sheldon"} • ${displayDate}</span>
              <span style="text-transform: uppercase; letter-spacing: 0.05em; font-weight: 700; color: var(--card-accent-color);">${item.data.type}</span>
            </div>
            ${!isPost && item.data.headline ? `<h2 style="margin: 0.75rem 0 0 0; font-size: ${isNote ? '1.5rem' : '1.75rem'}; font-weight: 800; color: var(--premier-charcoal); line-height: 1.2;">${item.data.headline}</h2>` : ''}
            ${isArticle && item.data.subhead ? `<p style="margin: 0.35rem 0 0 0; font-size: 1.05rem; font-style: italic; color: rgba(0,0,0,0.7);">${item.data.subhead}</p>` : ''}
          </header>
          
          <div class="notebook-body" style="line-height: 1.6; margin-bottom: 1.5rem; color: var(--premier-charcoal);">
      `;

      if (isArticle) {
        const cleanContent = item.templateContent.replace(/<[^>]*>/g, '').trim();
        const teaserText = cleanContent.split(' ').slice(0, 40).join(' ') + '...';
        htmlOutput += `<p>${teaserText}</p>`;
      } else {
        htmlOutput += item.templateContent;
      }

      htmlOutput += `
          </div>
          
          <footer style="display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 1rem; border-top: 1px solid rgba(0,0,0,0.08); padding-top: 1rem; margin-top: 1rem;">
            <div class="interactive-actions" style="display: flex; flex-wrap: wrap; gap: 0.75rem; align-items: center;">
              <a href="${item.url}" style="color: var(--card-accent-color); font-weight: 700; text-decoration: underline; text-underline-offset: 4px; font-size: 0.95rem; margin-right: 0.5rem;">${navLabel}</a>
              <button class="notebook-share-btn" data-url="${absoluteUrl}" data-title="${item.data.headline || 'Notebook Update'}" style="background: #ffffff; border: 1px solid rgba(0,0,0,0.15); padding: 0.4rem 0.8rem; border-radius: 4px; font-weight: 600; cursor: pointer; display: inline-flex; align-items: center; gap: 0.4rem; font-size: 0.85rem; color: var(--premier-charcoal);">
                🔄 Share
              </button>
              <a href="${chatRedirectUrl}" style="background: #ffffff; border: 1px solid rgba(0,0,0,0.15); padding: 0.4rem 0.8rem; border-radius: 4px; font-weight: 600; text-decoration: none; color: var(--premier-charcoal); display: inline-flex; align-items: center; gap: 0.4rem; font-size: 0.85rem;">
                💬 Chat Reply
              </a>
            </div>
            ${item.data.tags ? `
              <div class="notebook-tags" style="display: flex; gap: 0.4rem;">
                ${item.data.tags.map(tag => `<span style="background-color: rgba(0,0,0,0.05); font-size: 0.75rem; padding: 0.2rem 0.5rem; border-radius: 4px; font-weight: 500; color: var(--premier-charcoal);">#${tag}</span>`).join('')}
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