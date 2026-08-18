const fs = require('fs');
const path = require('path');

function readJsonDataFile(filename) {
  const filePath = path.join(__dirname, "data", filename);
  if (!fs.existsSync(filePath)) return null;
  try {
    const raw = fs.readFileSync(filePath, "utf-8");
    return JSON.parse(raw);
  } catch (e) {
    console.error(`Error parsing data/${filename}:`, e);
    return null;
  }
}

function findKeyCaseInsensitive(obj, targetKey) {
  if (!obj || !targetKey) return null;
  const cleanTarget = String(targetKey).toLowerCase().replace(/[^a-z0-9]/g, "");
  const matchedKey = Object.keys(obj).find(k => k.toLowerCase().replace(/[^a-z0-9]/g, "") === cleanTarget);
  return matchedKey ? obj[matchedKey] : null;
}

module.exports = function(eleventyConfig) {
  eleventyConfig.addPassthroughCopy("style.css");
  eleventyConfig.addPassthroughCopy("components.js");
  eleventyConfig.addPassthroughCopy("assets");
  eleventyConfig.addPassthroughCopy("contact.vcf");
  eleventyConfig.addPassthroughCopy("CNAME");
  eleventyConfig.addPassthroughCopy("data");
  eleventyConfig.addPassthroughCopy("quizzes/assets");
  eleventyConfig.addPassthroughCopy("quizzes/engines");

  eleventyConfig.ignores.add("scripts/");
  eleventyConfig.ignores.add(".github/");

  eleventyConfig.addFilter("cssmin", function(code) {
    if (!code) return "";
    return code
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .replace(/\s+/g, " ")
      .replace(/\s*([\{\}\:\;\,])\s*/g, "$1")
      .replace(/;\}/g, "}")
      .trim();
  });

  eleventyConfig.addShortcode("buildTime", function() {
    const now = new Date();
    const dateStr = new Intl.DateTimeFormat("en-US", {
      timeZone: "America/Los_Angeles",
      month: "long", day: "numeric", year: "numeric"
    }).format(now);
    const timeStr = new Intl.DateTimeFormat("en-US", {
      timeZone: "America/Los_Angeles",
      hour: "numeric", minute: "2-digit", timeZoneName: "short"
    }).format(now);
    return `${dateStr} at ${timeStr}`;
  });

  eleventyConfig.addFilter("localeString", function(value) {
    if (!value) return "0";
    return Number(value).toLocaleString('en-US');
  });

  eleventyConfig.addFilter("postDate", function(dateObj) {
    if (!dateObj) return "";
    const date = new Date(dateObj);
    return new Intl.DateTimeFormat("en-US", {
      timeZone: "America/Los_Angeles",
      month: "long", day: "numeric", year: "numeric"
    }).format(date);
  });

  eleventyConfig.addFilter("getDisclaimer", function(pageUrl, disclaimers) {
    if (!disclaimers) return "";
    let pageName = pageUrl || "";
    if (pageName === "/" || pageName === "") {
      pageName = "index.html";
    } else {
      if (pageName.startsWith("/")) pageName = pageName.substring(1);
      if (pageName.endsWith("/")) pageName = pageName.substring(0, pageName.length - 1);
      if (!pageName.includes(".html")) {
        pageName = pageName.split('/')[0] + ".html";
      }
    }
    return disclaimers[pageName] || "";
  });

  // Hero Pool Image Randomizer Filter
  eleventyConfig.addFilter("getRandomHeroImages", function(heroImages, county) {
    if (Array.isArray(heroImages) && heroImages.length >= 3 && heroImages[0]) {
      return heroImages;
    }
    const isSno = String(county || "").toLowerCase().includes("snohomish");
    const folder = isSno ? "snohomish" : "king";
    const maxCount = isSno ? 13 : 17;
    
    const indices = [];
    while (indices.length < 3) {
      const r = Math.floor(Math.random() * maxCount) + 1;
      if (!indices.includes(r)) indices.push(r);
    }
    
    return indices.map(idx => `https://assets.myseattlesearch.com/neighborhood/hero-pools/${folder}/${idx}.webp`);
  });

  // 1. Weather & AQI Data Loader
  eleventyConfig.addFilter("getCityWeather", function(citySlug) {
    const data = readJsonDataFile("city_weather.json");
    if (!data || !citySlug) return null;
    
    const record = findKeyCaseInsensitive(data, citySlug);
    if (!record) return null;

    const curr = record.current || {};
    const astro = record.astronomy || {};
    const aq = record.air_quality || {};
    const forecast = record.forecast_7_day || {};

    const tempVal = curr.temp_f != null ? Math.round(curr.temp_f) : null;
    const tempHigh = forecast.temp_max && forecast.temp_max[0] != null ? Math.round(forecast.temp_max[0]) : null;
    const tempLow = forecast.temp_min && forecast.temp_min[0] != null ? Math.round(forecast.temp_min[0]) : null;

    const formatIsoTime = (isoStr) => {
      if (!isoStr) return "";
      try {
        const timePart = isoStr.split("T")[1];
        const [hStr, mStr] = timePart.split(":");
        let h = parseInt(hStr, 10);
        const suffix = h < 12 ? "A" : "P";
        if (h > 12) h -= 12;
        if (h === 0) h = 12;
        return `${h}:${mStr}${suffix}`;
      } catch (e) {
        return isoStr;
      }
    };

    const code = curr.weather_code;
    const condMap = {
      0: "Sunny", 1: "Mainly Clear", 2: "Partly Cloudy", 3: "Overcast",
      45: "Foggy", 51: "Drizzle", 61: "Rain", 71: "Snow", 80: "Showers", 95: "Thunderstorm"
    };

    return {
      temp: tempVal,
      temp_high: tempHigh,
      temp_low: tempLow,
      condition: condMap[code] || "Sunny",
      sunrise: formatIsoTime(astro.sunrise_today),
      sunset: formatIsoTime(astro.sunset_today),
      aqi: aq.us_aqi || null,
      aqi_label: aq.status_label || "Good"
    };
  });

  // 2. Active Transit Score Loader
  eleventyConfig.addFilter("getTransitLive", function(citySlug) {
    const data = readJsonDataFile("transit_radar_live.json");
    if (!data || !citySlug) return null;
    return findKeyCaseInsensitive(data, citySlug);
  });

  // 3. Market Hotness Stats Loader
  eleventyConfig.addFilter("getMarketStats", function(citySlug) {
    const statsData = readJsonDataFile("infosparks_stats.json");
    if (!statsData || !citySlug) return { market_label: "Seller's Market" };

    const cityClean = String(citySlug).toLowerCase().replace(/[^a-z0-9]/g, "");
    const feeds = statsData.feeds || {};
    
    for (const [feedKey, feedObj] of Object.entries(feeds)) {
      if (feedObj.meta && feedObj.meta.metric === "Months Supply Closed") {
        const dataArr = feedObj.data || [];
        if (dataArr.length > 0) {
          const latestPoint = dataArr[dataArr.length - 1];
          for (const [geoKey, val] of Object.entries(latestPoint)) {
            if (geoKey.toLowerCase().replace(/[^a-z0-9]/g, "") === cityClean) {
              const moi = parseFloat(val);
              const label = moi < 4.0 ? "Seller's Market" : (moi <= 6.0 ? "Balanced Market" : "Buyer's Market");
              return { market_label: label, months_supply: moi };
            }
          }
        }
      }
    }

    return { market_label: "Seller's Market" };
  });

  // 4. Sports Priority Cascade Filter
  eleventyConfig.addFilter("getTopSportsGame", function() {
    const sportsData = readJsonDataFile("hourly_sports.json");
    if (!sportsData) return null;

    const liveGames = sportsData.live_games || [];
    const recentFinals = sportsData.recent_finals || [];
    const upcomingGames = sportsData.upcoming_games || [];

    const candidate = liveGames[0] || recentFinals[0] || upcomingGames[0] || null;
    if (!candidate) return null;

    const shortTeam = (name) => {
      if (!name) return "";
      if (name.includes("Mariners")) return "SEA";
      if (name.includes("Yankees")) return "NYY";
      if (name.includes("Angels")) return "LAA";
      if (name.includes("Seahawks")) return "SEA";
      if (name.includes("Rainiers")) return "TAC";
      if (name.includes("Cardinals")) return "ARI";
      if (name.includes("Panthers")) return "CAR";
      const parts = name.split(" ");
      return parts[parts.length - 1].substring(0, 3).toUpperCase();
    };

    const homeName = candidate.home_team || candidate.homeTeam || "Seattle Mariners";
    const awayName = candidate.away_team || candidate.awayTeam || "LA Angels";

    return {
      league: candidate.league === "MLB/MiLB" ? "MLB Baseball" : (candidate.league || "MLB Baseball"),
      status: String(candidate.status || "FINAL").toUpperCase(),
      homeTeam: homeName,
      homeScore: candidate.home_score !== undefined ? candidate.home_score : (candidate.homeScore || "0"),
      homeRecord: candidate.home_record || candidate.homeRecord || "88-74",
      awayTeam: awayName,
      awayScore: candidate.away_score !== undefined ? candidate.away_score : (candidate.awayScore || "0"),
      awayRecord: candidate.away_record || candidate.awayRecord || "63-99",
      venue: candidate.venue || "T-Mobile Park • Home Game",
      logoUrl: candidate.logoUrl || "https://assets.myseattlesearch.com/repomove/mariners-logo.webp",
      homeShort: shortTeam(homeName),
      awayShort: shortTeam(awayName)
    };
  });

  // 5. Regional News Matcher Filter
  eleventyConfig.addFilter("getRegionalNews", function(newsRegion, limit = 5) {
    const newsData = readJsonDataFile("market_news.json") || readJsonDataFile("news.json");
    if (!newsData) return [];
    
    const regionClean = (newsRegion || "").toLowerCase().replace(/[^a-z0-9]/g, "");

    let articles = [];
    if (Array.isArray(newsData)) {
      articles = newsData.filter(item => {
        const itemReg = (item.news_region || item.region || item.category || "").toLowerCase().replace(/[^a-z0-9]/g, "");
        return itemReg.includes(regionClean) || regionClean.includes(itemReg);
      });
      if (!articles.length) articles = newsData;
    } else if (typeof newsData === 'object') {
      const matchedKey = Object.keys(newsData).find(k => k.toLowerCase().replace(/[^a-z0-9]/g, "").includes(regionClean));
      articles = matchedKey ? newsData[matchedKey] : (newsData["default"] || newsData["all"] || Object.values(newsData)[0] || []);
    }

    return articles.slice(0, limit);
  });

  // 6. Monthly Featured Yelp Spots Filter
  eleventyConfig.addFilter("getMonthlyFeaturedSpots", function(citySlug, cityDataRecord) {
    const cityBusinesses = readJsonDataFile("city_businesses.json");
    if (!cityBusinesses || !citySlug) {
      return { categoryLabel: "Local Favorites", spots: [], headerBadge: "" };
    }

    const cityRecord = findKeyCaseInsensitive(cityBusinesses, citySlug);
    if (!cityRecord) return { categoryLabel: "Local Favorites", spots: [], headerBadge: "" };

    const monthNames = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
    const now = new Date();
    const monthIndex = now.getMonth() + 1;
    const currentMonthName = monthNames[now.getMonth()];

    const catVal = cityDataRecord ? (cityDataRecord[`FeatCat${monthIndex}`] || cityDataRecord[`FEATCAT${monthIndex}`] || "coffee") : "coffee";
    const primaryCatSlug = String(catVal).split(",")[0].trim().toLowerCase().replace(/[^a-z0-9]/g, "");
    
    const bizCategoryData = cityRecord.categories || {};
    
    let rawSpots = [];
    if (bizCategoryData[primaryCatSlug]) {
      rawSpots = bizCategoryData[primaryCatSlug];
    } else {
      const matchedCatKey = Object.keys(bizCategoryData).find(k => k.toLowerCase().replace(/[^a-z0-9]/g, "").includes(primaryCatSlug));
      if (matchedCatKey) {
        rawSpots = bizCategoryData[matchedCatKey];
      } else {
        const firstAvailable = Object.keys(bizCategoryData)[0];
        rawSpots = firstAvailable ? bizCategoryData[firstAvailable] : [];
      }
    }

    const uniqueSpotsMap = new Map();
    rawSpots.forEach(s => {
      if (s && s.name && !uniqueSpotsMap.has(s.name)) {
        uniqueSpotsMap.set(s.name, s);
      }
    });

    const spots = Array.from(uniqueSpotsMap.values());
    const categoryDisplay = String(catVal).replace(/_/g, " ").replace(/\b\w/g, l => l.toUpperCase());

    return {
      monthName: currentMonthName,
      categoryLabel: categoryDisplay,
      headerBadge: `${currentMonthName}'s Feature: ${categoryDisplay}`,
      spots: spots.slice(0, 3)
    };
  });

  // 7. Markdown Editorial Paragraph Extractor
  eleventyConfig.addFilter("getEditorialParagraphs", function(citySlug) {
    if (!citySlug) return [];
    
    const now = new Date();
    const currentMonth = now.getMonth() + 1;
    
    const filePath = path.join(__dirname, "data", "editorials", `${citySlug}.md`);
    if (!fs.existsSync(filePath)) return [];

    try {
      const fileContent = fs.readFileSync(filePath, "utf-8").replace(/\r\n/g, "\n").replace(/\r/g, "\n");
      
      const epHeaderRegex = new RegExp(`(?:^|\\n)#+\\s*\\**EP${currentMonth}\\**`, 'i');
      const matchIndex = fileContent.search(epHeaderRegex);
      
      if (matchIndex === -1) return [];

      const contentFromHeader = fileContent.slice(matchIndex);
      
      const nextHeaderRegex = /\n#+\s*\**EP\d+/i;
      const nextHeaderMatch = contentFromHeader.slice(1).search(nextHeaderRegex);
      
      const rawSection = nextHeaderMatch !== -1 
        ? contentFromHeader.slice(0, nextHeaderMatch + 1) 
        : contentFromHeader;

      const rawBlocks = rawSection.split(/\n\s*\n/);
      
      const paragraphs = [];
      rawBlocks.forEach(p => {
        const pClean = p.replace(/\n/g, " ").trim();
        if (pClean && !pClean.startsWith("#") && !pClean.startsWith("EVENT OFFSETS")) {
          paragraphs.push(pClean);
        }
      });

      return paragraphs.slice(0, 4);
    } catch (e) {
      console.error(`Error reading editorial markdown for ${citySlug}:`, e);
      return [];
    }
  });

  // 8. Municipal & City Events Loader
  eleventyConfig.addFilter("getCityEvents", function(citySlug) {
    const cityEventsData = readJsonDataFile("city_events.json");
    if (!cityEventsData || !citySlug) return [];
    
    const cityEvents = findKeyCaseInsensitive(cityEventsData, citySlug);
    if (!cityEvents || !Array.isArray(cityEvents)) return [];

    return cityEvents.slice(0, 5);
  });

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
        year: "numeric", month: "long", day: "numeric"
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

  eleventyConfig.addCollection("posts", function(collectionApi) {
    return collectionApi.getFilteredByGlob("posts/*.md");
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