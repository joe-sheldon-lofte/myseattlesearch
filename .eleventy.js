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
   * Replicates the compact layout definitions, upper-right anchors,
   * color profiles, and smart responsive footer layout splits.
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

    let htmlOutput = `<div class="notebook-static-feed" style="max-width: 800px; margin: 0 auto; display: flex; flex-direction: column; gap: 1.5rem; width: 100%;">`;

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

      let cardStyle = `border-radius: 6px; width: 100%; box-sizing: border-box; text-align: left; position: relative;`;
      let navLabel = "View Entry →";
      let textStyle = `color: var(--premier-charcoal); margin: 0;`;

      if (isPost) {
        cardStyle += ` padding: 1.25rem; background-color: var(--card-accent-color); border: none;`;
        textStyle = `color: white; font-size: 1.15rem; font-weight: 600; line-height: 1.45; margin: 0;`;
        navLabel = "View Post →";
      } else if (isNote) {
        cardStyle += ` padding: 1.5rem; border: 3px solid var(--card-accent-color); background-color: var(--dynamic-bg-highlight);`;
        navLabel = "View Note →";
      } else if (isArticle) {
        cardStyle += ` padding: 1.75rem; border: 1px solid var(--card-accent-color); background-color: white;`;
        navLabel = "View Article →";
      }

      htmlOutput += `
        <article class="notebook-card type-${typeLower}" style="${cardStyle}">
          <header style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem;">
            <span style="text-transform: uppercase; letter-spacing: 0.05em; font-weight: 800; font-size: 0.8rem; color: ${isPost ? 'white' : 'var(--card-accent-color)'};">${item.data.type}</span>
            <a href="${item.url}" style="font-weight: 700; text-decoration: underline; text-underline-offset: 3px; font-size: 0.85rem; color: ${isPost ? 'white' : 'var(--card-accent-color)'};">${navLabel}</a>
          </header>
          
          ${!isPost && item.data.headline ? `<h2 style="margin: 0 0 0.4rem 0; font-size: ${isNote ? '1.35rem' : '1.5rem'}; font-weight: 800; color: var(--premier-charcoal); line-height: 1.2;">${item.data.headline}</h2>` : ''}
          ${isArticle && item.data.subhead ? `<p style="margin: 0 0 0.75rem 0; font-size: 1rem; font-style: italic; color: rgba(0,0,0,0.6);">${item.data.subhead}</p>` : ''}
          
          <div class="notebook-body" style="${textStyle} margin-bottom: 0.85rem;">
      `;

      if (isArticle) {
        const cleanContent = item.templateContent.replace(/<[^>]*>/g, '').trim();
        const teaserText = cleanContent.split(' ').slice(0, 35).join(' ') + '...';
        htmlOutput += `<p style="margin: 0;">${teaserText}</p>`;
      } else {
        htmlOutput += item.templateContent;
      }

      htmlOutput += `
          </div>
          
          <footer style="display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; background-color: ${isPost ? 'rgba(255,255,255,0.15)' : 'rgba(0,0,0,0.03)'}; padding: 0.4rem 0.75rem; border-radius: 4px; font-size: 0.8rem; gap: 0.5rem;">
            <div style="flex: 1 1 260px; font-weight: 500; color: ${isPost ? 'white' : 'rgba(0,0,0,0.65)'};">
              By: ${item.data.author || "Joe Sheldon"} • ${displayDate}
            </div>
            <div style="flex: 1 1 auto; display: flex; justify-content: flex-end; gap: 0.5rem; align-items: center;">
              <button class="notebook-share-btn" data-url="${absoluteUrl}" data-title="${item.data.headline || 'Notebook Update'}" style="background: white; border: 1px solid rgba(0,0,0,0.15); padding: 0.25rem 0.5rem; border-radius: 3px; font-weight: 600; cursor: pointer; font-size: 0.75rem; color: var(--premier-charcoal); display: inline-flex; align-items: center; gap: 0.25rem;">🔄 Share</button>
              <a href="${chatRedirectUrl}" style="background: white; border: 1px solid rgba(0,0,0,0.15); padding: 0.25rem 0.5rem; border-radius: 3px; font-weight: 600; text-decoration: none; font-size: 0.75rem; color: var(--premier-charcoal); display: inline-flex; align-items: center; gap: 0.25rem;">💬 Reply</a>
            </div>
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