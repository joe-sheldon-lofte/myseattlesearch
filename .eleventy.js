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

  // Category Grammar & Formatting Filter ("breweries,beer_gardens" -> "Breweries & Beer Gardens")
  eleventyConfig.addFilter("formatCategoryLabel", function(catStr) {
    if (!catStr) return "Local Favorites";
    let clean = String(catStr).replace(/_/g, " ");
    let parts = clean.split(",").map(s => s.trim()).filter(Boolean);
    parts = parts.map(p => p.replace(/\b\w/g, l => l.toUpperCase()));
    
    if (parts.length === 0) return "Local Favorites";
    if (parts.length === 1) return parts[0];
    if (parts.length === 2) return `${parts[0]} & ${parts[1]}`;
    return `${parts.slice(0, -1).join(", ")}, & ${parts[parts.length - 1]}`;
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

  // Weather Loader
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
        const suffix = h < 12 ? "AM" : "PM";
        if (h > 12) h -= 12;
        if (h === 0) h = 12;
        return `${h}:${mStr} ${suffix}`;
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

  // Transit Radar Loader
  eleventyConfig.addFilter("getTransitLive", function(citySlug) {
    const data = readJsonDataFile("transit_radar_live.json");
    if (!data || !citySlug) return null;
    return findKeyCaseInsensitive(data, citySlug);
  });

  // Market Stats Loader
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

  // Sports Loader
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

  // Regional News Matcher
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

  // Monthly Featured Yelp Spots
  eleventyConfig.addFilter("getMonthlyFeaturedSpots", function(citySlug, cityDataRecord) {
    const cityBusinesses = readJsonDataFile("city_businesses.json");
    if (!cityBusinesses || !citySlug) {
      return { categoryLabel: "Local Favorites", spots: [], monthName: "August" };
    }

    const cityRecord = findKeyCaseInsensitive(cityBusinesses, citySlug);
    if (!cityRecord) return { categoryLabel: "Local Favorites", spots: [], monthName: "August" };

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

    return {
      monthName: currentMonthName,
      categoryLabel: String(catVal),
      spots: spots.slice(0, 3)
    };
  });

  // Editorial Extractor
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

  // City Events Loader
  eleventyConfig.addFilter("getCityEvents", function(citySlug) {
    const cityEventsData = readJsonDataFile("city_events.json");
    if (!cityEventsData || !citySlug) return [];
    
    const cityEvents = findKeyCaseInsensitive(cityEventsData, citySlug);
    if (!cityEvents || !Array.isArray(cityEvents)) return [];

    return cityEvents.slice(0, 5);
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