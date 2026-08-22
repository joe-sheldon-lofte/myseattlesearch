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

// Haversine Distance Formula (Miles)
function calculateHaversineMiles(lat1, lon1, lat2, lon2) {
  const R = 3958.8;
  const dLat = (lat2 - lat1) * (Math.PI / 180);
  const dLon = (lon2 - lon1) * (Math.PI / 180);
  const a =
    Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos(lat1 * (Math.PI / 180)) * Math.cos(lat2 * (Math.PI / 180)) *
    Math.sin(dLon / 2) * Math.sin(dLon / 2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return R * c;
}

module.exports = function(eleventyConfig) {
  // Passthrough Copies
  eleventyConfig.addPassthroughCopy("style.css");
  eleventyConfig.addPassthroughCopy("components.js");
  eleventyConfig.addPassthroughCopy("assets");
  eleventyConfig.addPassthroughCopy("contact.vcf");
  eleventyConfig.addPassthroughCopy("CNAME");
  eleventyConfig.addPassthroughCopy("data");
  eleventyConfig.addPassthroughCopy("quizzes/assets");
  eleventyConfig.addPassthroughCopy("quizzes/engines");

  // Ignores
  eleventyConfig.ignores.add("scripts/");
  eleventyConfig.ignores.add(".github/");

  // Shortcodes
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

  // Basic Utility Filters
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
      month: "long", day: "numeric", year: "numeric"
    }).format(date);
  });

  // Forecast Date Formatter (Day, Mon DD)
  eleventyConfig.addFilter("formatForecastDate", function(dateStr) {
    if (!dateStr) return "";
    try {
      const parts = String(dateStr).split('-');
      if (parts.length === 3) {
        const date = new Date(parseInt(parts[0], 10), parseInt(parts[1], 10) - 1, parseInt(parts[2], 10));
        const dayName = new Intl.DateTimeFormat("en-US", { weekday: "short" }).format(date);
        const monthName = new Intl.DateTimeFormat("en-US", { month: "short" }).format(date);
        return `${dayName}, ${monthName} ${parseInt(parts[2], 10)}`;
      }
      return dateStr;
    } catch(e) {
      return dateStr;
    }
  });

  // Water Gauge Timestamp Formatter (Mon DD, H:MM AM/PM)
  eleventyConfig.addFilter("formatGaugeTime", function(isoStr) {
    if (!isoStr) return "Live";
    try {
      const date = new Date(isoStr);
      const monthDay = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", timeZone: "America/Los_Angeles" }).format(date);
      const timeStr = new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit", timeZone: "America/Los_Angeles" }).format(date);
      return `${monthDay}, ${timeStr}`;
    } catch(e) {
      return isoStr;
    }
  });

  // Tide 24-Hour String to 12-Hour AM/PM Formatter
  eleventyConfig.addFilter("formatTideTime", function(str) {
    if (!str) return "";
    try {
      let timePart = str.includes(" ") ? str.split(" ")[1] : str;
      let [hStr, mStr] = timePart.split(":");
      let h = parseInt(hStr, 10);
      if (isNaN(h)) return str;
      const ampm = h >= 12 ? "PM" : "AM";
      h = h % 12;
      if (h === 0) h = 12;
      return `${h}:${mStr} ${ampm}`;
    } catch(e) {
      return str;
    }
  });

  // Hourly Timestamp Formatter for Transit Log (H:MM AM/PM)
  eleventyConfig.addFilter("formatHourlyLogTime", function(isoStr) {
    if (!isoStr) return "";
    try {
      const date = new Date(isoStr);
      return new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit", timeZone: "America/Los_Angeles" }).format(date);
    } catch(e) {
      return isoStr;
    }
  });

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

    let daylightPct = 0.86;
    try {
      const parseIsoMins = (isoStr) => {
        if (!isoStr) return null;
        const timePart = isoStr.split("T")[1];
        const [h, m] = timePart.split(":");
        return parseInt(h, 10) * 60 + parseInt(m, 10);
      };

      const sunriseMins = parseIsoMins(astro.sunrise_today) || 367;
      const sunsetMins = parseIsoMins(astro.sunset_today) || 1217;

      const now = new Date();
      const pdtParts = new Intl.DateTimeFormat("en-US", {
        timeZone: "America/Los_Angeles",
        hour: "numeric", minute: "numeric", hourCycle: "h23"
      }).formatToParts(now);
      let nowH = 16, nowM = 27;
      pdtParts.forEach(p => {
        if (p.type === "hour") nowH = parseInt(p.value, 10);
        if (p.type === "minute") nowM = parseInt(p.value, 10);
      });
      const nowMins = nowH * 60 + nowM;

      if (nowMins <= sunriseMins) {
        daylightPct = 0.0;
      } else if (nowMins >= sunsetMins) {
        daylightPct = 1.0;
      } else {
        daylightPct = (nowMins - sunriseMins) / (sunsetMins - sunriseMins);
      }
    } catch (e) {
      daylightPct = 0.86;
    }

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
      daylight_pct: daylightPct,
      aqi: aq.us_aqi || null,
      aqi_label: aq.status_label || "Good"
    };
  });

  // Complete Weather Object Loader
  eleventyConfig.addFilter("getCityFullWeather", function(citySlug) {
    const data = readJsonDataFile("city_weather.json");
    if (!data || !citySlug) return null;
    return findKeyCaseInsensitive(data, citySlug);
  });

  // Dynamic Two-Way Geo-Distance & Commute Telemetry Calculator (6 SEPARATE EMPLOYMENT HUBS)
  eleventyConfig.addFilter("getGeoCommuteTimes", function(cityLat, cityLng, cityName) {
    const lat = parseFloat(cityLat) || 47.756;
    const lng = parseFloat(cityLng) || -122.345;
    const cName = cityName || "City";

    const hubs = [
      { id: "slu", name: "South Lake Union", targetLat: 47.6253, targetLng: -122.3382, baseSpeedMph: 35 },
      { id: "bellevue", name: "Downtown Bellevue", targetLat: 47.6152, targetLng: -122.2015, baseSpeedMph: 38 },
      { id: "redmond", name: "Microsoft Redmond Campus", targetLat: 47.6423, targetLng: -122.1371, baseSpeedMph: 40 },
      { id: "everett", name: "Boeing Everett Factory", targetLat: 47.9252, targetLng: -122.2714, baseSpeedMph: 45 },
      { id: "renton", name: "Boeing Renton Factory", targetLat: 47.4880, targetLng: -122.2050, baseSpeedMph: 42 },
      { id: "kent", name: "Kent Valley Hub", targetLat: 47.3809, targetLng: -122.2348, baseSpeedMph: 44 }
    ];

    const now = new Date();
    const pdtParts = new Intl.DateTimeFormat("en-US", {
      timeZone: "America/Los_Angeles",
      hour: "numeric", hourCycle: "h23"
    }).formatToParts(now);
    let hour = 17;
    pdtParts.forEach(p => { if (p.type === "hour") hour = parseInt(p.value, 10); });

    let outboundMult = 1.15;
    let inboundMult = 1.10;

    if (hour >= 7 && hour <= 9) {
      outboundMult = 1.45;
      inboundMult = 1.15;
    } else if (hour >= 16 && hour <= 18) {
      outboundMult = 1.20;
      inboundMult = 1.50;
    }

    return hubs.map(h => {
      const distMiles = calculateHaversineMiles(lat, lng, h.targetLat, h.targetLng);
      const roundedDist = Math.max(1.2, Math.round(distMiles * 10) / 10);

      const baseDriveMins = Math.round((roundedDist / h.baseSpeedMph) * 60 + 3);
      
      const outCurrDrive = Math.round(baseDriveMins * outboundMult);
      const inCurrDrive = Math.round(baseDriveMins * inboundMult);

      const outOffpeakTransit = Math.round(baseDriveMins * 1.5 + 6);
      const outCurrTransit = Math.round(outCurrDrive * 1.4 + 8);

      const inOffpeakTransit = Math.round(baseDriveMins * 1.5 + 6);
      const inCurrTransit = Math.round(inCurrDrive * 1.4 + 8);

      return {
        id: h.id,
        hub_name: h.name,
        distance_miles: roundedDist,
        outbound_label: `${cName} → ${h.name}`,
        inbound_label: `${h.name} → ${cName}`,
        outbound: {
          curr_drive_mins: outCurrDrive,
          offpeak_drive_mins: baseDriveMins,
          curr_transit_mins: outCurrTransit,
          offpeak_transit_mins: outOffpeakTransit
        },
        inbound: {
          curr_drive_mins: inCurrDrive,
          offpeak_drive_mins: baseDriveMins,
          curr_transit_mins: inCurrTransit,
          offpeak_transit_mins: inOffpeakTransit
        }
      };
    });
  });

  // Group 168-Hour Transit History into 7 Day Objects for Accordions
  eleventyConfig.addFilter("get7DayGroupedTransitHistory", function(citySlug) {
    const data = readJsonDataFile("transit_radar_history.json");
    if (!data || !citySlug) return [];
    const record = findKeyCaseInsensitive(data, citySlug);
    if (!record || !Array.isArray(record)) return [];

    const groupedMap = {};
    record.forEach(item => {
      if (!item.timestamp) return;
      const dateKey = item.timestamp.split("T")[0];
      if (!groupedMap[dateKey]) {
        const dateObj = new Date(dateKey + "T12:00:00");
        const formattedDate = new Intl.DateTimeFormat("en-US", { weekday: "long", month: "short", day: "numeric", timeZone: "America/Los_Angeles" }).format(dateObj);
        
        groupedMap[dateKey] = {
          date_key: dateKey,
          date_label: formattedDate,
          day_name: item.day_of_week || "",
          transitScores: [],
          onTimeScores: [],
          hours: []
        };
      }

      let timePart = item.timestamp.includes("T") ? item.timestamp.split("T")[1].substring(0, 5) : "";
      let [hStr, mStr] = timePart.split(":");
      let h = parseInt(hStr, 10);
      let ampm = h >= 12 ? "PM" : "AM";
      let displayH = h % 12;
      if (displayH === 0) displayH = 12;
      let time12 = `${displayH}:${mStr || '00'} ${ampm}`;

      const tScore = item.active_transit_score !== null ? item.active_transit_score : "--";
      const oRate = item.active_on_time_score !== null ? `${item.active_on_time_score}%` : "100%";

      if (item.active_transit_score !== null) groupedMap[dateKey].transitScores.push(item.active_transit_score);
      if (item.active_on_time_score !== null) groupedMap[dateKey].onTimeScores.push(item.active_on_time_score);

      groupedMap[dateKey].hours.push({
        time12: time12,
        transit_score: tScore,
        ontime_rate: oRate
      });
    });

    return Object.values(groupedMap).map(dayObj => {
      const avgT = dayObj.transitScores.length ? Math.round(dayObj.transitScores.reduce((a,b)=>a+b,0)/dayObj.transitScores.length) : "--";
      const avgO = dayObj.onTimeScores.length ? Math.round(dayObj.onTimeScores.reduce((a,b)=>a+b,0)/dayObj.onTimeScores.length) : 100;
      return {
        date_label: dayObj.date_label,
        avg_transit_score: avgT,
        avg_ontime_rate: `${avgO}%`,
        hours: dayObj.hours
      };
    }).slice(-7);
  });

  // Dynamic Tide Telemetry Filter
  eleventyConfig.addFilter("getTideTelemetry", function(fullWeather) {
    if (!fullWeather || !fullWeather.marine_tides) return null;
    const tidesObj = fullWeather.marine_tides;
    const predictions = tidesObj.today_predictions || [];
    if (!predictions.length) return null;

    const now = new Date();
    const pdtParts = new Intl.DateTimeFormat("en-US", {
      timeZone: "America/Los_Angeles",
      hour: "numeric", minute: "numeric", hourCycle: "h23"
    }).formatToParts(now);
    let nowH = 16, nowM = 27;
    pdtParts.forEach(p => {
      if (p.type === "hour") nowH = parseInt(p.value, 10);
      if (p.type === "minute") nowM = parseInt(p.value, 10);
    });
    const nowMins = nowH * 60 + nowM;

    const parsed = predictions.map(p => {
      let timePart = p.time.includes(" ") ? p.time.split(" ")[1] : p.time;
      let [hStr, mStr] = timePart.split(":");
      let h = parseInt(hStr, 10);
      let m = parseInt(mStr, 10);
      let totalMins = h * 60 + m;

      let ampm = h >= 12 ? "PM" : "AM";
      let displayH = h % 12;
      if (displayH === 0) displayH = 12;
      let time12 = `${displayH}:${mStr} ${ampm}`;

      return {
        type: p.type,
        height_ft: p.height_ft,
        mins: totalMins,
        time12: time12
      };
    }).sort((a, b) => a.mins - b.mins);

    let upcomingHigh = parsed.find(p => p.type === "High" && p.mins >= nowMins) || parsed.find(p => p.type === "High") || parsed[0];
    let upcomingLow = parsed.find(p => p.type === "Low" && p.mins >= nowMins) || parsed.find(p => p.type === "Low") || parsed[0];

    let isRising = true;
    for (let i = 0; i < parsed.length - 1; i++) {
      if (nowMins >= parsed[i].mins && nowMins < parsed[i+1].mins) {
        if (parsed[i].type === "Low" && parsed[i+1].type === "High") {
          isRising = true;
        } else if (parsed[i].type === "High" && parsed[i+1].type === "Low") {
          isRising = false;
        }
        break;
      }
    }
    if (nowMins >= parsed[parsed.length - 1].mins) {
      isRising = parsed[parsed.length - 1].type === "Low";
    }
    if (nowMins < parsed[0].mins) {
      isRising = parsed[0].type === "High";
    }

    return {
      reference_station: tidesObj.reference_station || "Puget Sound",
      high_time: upcomingHigh.time12,
      high_ft: `${upcomingHigh.height_ft} ft`,
      low_time: upcomingLow.time12,
      low_ft: `${upcomingLow.height_ft} ft`,
      is_rising: isRising,
      status_label: isRising ? "▲ Tide Rising" : "▼ Tide Falling"
    };
  });

  // USGS Regional Water Gauges Loader
  eleventyConfig.addFilter("getRegionalWaterGauges", function() {
    const data = readJsonDataFile("city_weather.json");
    if (!data || !data._regional_water_gauges) return [];
    return data._regional_water_gauges;
  });

  // Transit Radar Loader
  eleventyConfig.addFilter("getTransitLive", function(citySlug) {
    const data = readJsonDataFile("transit_radar_live.json");
    if (!data || !citySlug) return null;
    return findKeyCaseInsensitive(data, citySlug);
  });

  // Complete 168-Hour Hourly Transit History Log Loader
  eleventyConfig.addFilter("getHourlyTransitHistory", function(citySlug) {
    const data = readJsonDataFile("transit_radar_history.json");
    if (!data || !citySlug) return [];
    const record = findKeyCaseInsensitive(data, citySlug);
    if (!record || !Array.isArray(record)) return [];

    return record.map(item => ({
      timestamp: item.timestamp,
      day_of_week: item.day_of_week || "",
      transit_score: item.active_transit_score !== null ? item.active_transit_score : "--",
      ontime_rate: item.active_on_time_score !== null ? `${item.active_on_time_score}%` : "100%"
    }));
  });

  // City Construction WSDOT Alerts Loader
  eleventyConfig.addFilter("getCityConstruction", function(citySlug) {
    const data = readJsonDataFile("city_construction.json");
    if (!data || !citySlug) return { alert_count: 0, alerts: [] };
    const record = findKeyCaseInsensitive(data, citySlug);
    if (!record) return { alert_count: 0, alerts: [] };
    return {
      alert_count: record.alert_count || 0,
      alerts: record.alerts || []
    };
  });

  // Intercity Airports & Flights Summary Loader
  eleventyConfig.addFilter("getIntercitySummary", function() {
    const data = readJsonDataFile("intercity_summary.json");
    if (!data) return { airports: {}, last_updated: "" };
    return data;
  });

  // Walk, Transit & Bike Scores Loader
  eleventyConfig.addFilter("getMobilityScores", function(cityName) {
    const data = readJsonDataFile("walk_transit_bike_score.json");
    if (!data || !cityName) return null;
    const record = findKeyCaseInsensitive(data, cityName);
    if (!record) return null;
    
    return {
      walk_score: record.walkscore != null ? record.walkscore : null,
      walk_desc: record.description || null,
      transit_score: (record.transit && record.transit.score != null) ? record.transit.score : null,
      transit_desc: (record.transit && record.transit.description) ? record.transit.description : null,
      bike_score: (record.bike && record.bike.score != null) ? record.bike.score : null,
      bike_desc: (record.bike && record.bike.description) ? record.bike.description : null,
      ws_link: record.ws_link || null
    };
  });

  // Climate Comfort Profile Loader
  eleventyConfig.addFilter("getClimateComfort", function(cityName) {
    const data = readJsonDataFile("climate_comfort.json");
    if (!data || !cityName) return null;
    return findKeyCaseInsensitive(data, cityName);
  });

  // School District Ratings Loader
  eleventyConfig.addFilter("getSchoolData", function(cityName) {
    const data = readJsonDataFile("school_ratings.json");
    if (!data || !cityName) return null;
    return findKeyCaseInsensitive(data, cityName);
  });

  // Crime Stats Loader
  eleventyConfig.addFilter("getCrimeData", function(cityName) {
    const data = readJsonDataFile("crime_stats.json");
    if (!data || !cityName) return null;
    return findKeyCaseInsensitive(data, cityName);
  });

  // Public Safety & Emergency Services Loader
  eleventyConfig.addFilter("getPublicSafetyData", function(cityName) {
    const data = readJsonDataFile("public_safety_emergency.json");
    if (!data || !cityName) return null;
    return findKeyCaseInsensitive(data, cityName);
  });

  // Surveillance Stats Loader
  eleventyConfig.addFilter("getSurveillanceData", function(cityName) {
    const data = readJsonDataFile("surveillance_stats.json");
    if (!data || !cityName) return null;
    return findKeyCaseInsensitive(data, cityName);
  });

  // Market Stats Loader (0-2.0: Seller's, 2.0-4.0: Balanced, >4.0: Buyer's)
  eleventyConfig.addFilter("getMarketStats", function(citySlug) {
    const statsData = readJsonDataFile("infosparks_stats.json");
    if (!statsData || !citySlug) return { market_label: "Seller's Market", months_supply: 1.8 };

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
              const label = moi < 2.0 ? "Seller's Market" : (moi <= 4.0 ? "Balanced Market" : "Buyer's Market");
              return { market_label: label, months_supply: moi };
            }
          }
        }
      }
    }

    return { market_label: "Seller's Market", months_supply: 1.8 };
  });

  // Comprehensive InfoSparks / NWMLS City Extractor Across All Groups
  eleventyConfig.addFilter("getInfoSparksCityStats", function(cityName) {
    const statsData = readJsonDataFile("infosparks_stats.json");
    if (!statsData || !statsData.feeds || !cityName) return null;

    const cityClean = String(cityName).toLowerCase().replace(/[^a-z0-9]/g, "");
    const result = { latest_date: "July 2026" };

    for (const [feedKey, feedObj] of Object.entries(statsData.feeds)) {
      const metric = feedObj.meta ? feedObj.meta.metric : "";
      const dataArr = feedObj.data || [];
      if (dataArr.length > 0) {
        const latestPoint = dataArr[dataArr.length - 1];
        if (latestPoint.Date) result.latest_date = latestPoint.Date;

        for (const [geoKey, val] of Object.entries(latestPoint)) {
          if (geoKey.toLowerCase().replace(/[^a-z0-9]/g, "") === cityClean) {
            if (metric === "Median Sale Price") result.median_sale_price = val;
            if (metric === "Closed Sales") result.closed_sales = val;
            if (metric === "Average Days on Market") result.average_dom = val;
            if (metric === "Months Supply Closed") result.months_supply = val;
            if (metric === "Shows Per Listing") result.shows_per_listing = val;
            if (metric === "Percent of List Price Average") {
              result.percent_list_price = (parseFloat(val) * 100).toFixed(1) + "%";
            }
          }
        }
      }
    }

    return result.median_sale_price ? result : null;
  });

  // InfoSparks Chart Points Builder
  eleventyConfig.addFilter("buildInfoSparksChart", function(cityName, metricName, width = 400, height = 60) {
    const statsData = readJsonDataFile("infosparks_stats.json");
    if (!statsData || !statsData.feeds || !cityName || !metricName) return null;

    const cityClean = String(cityName).toLowerCase().replace(/[^a-z0-9]/g, "");
    const metricClean = String(metricName).toLowerCase().replace(/[^a-z0-9]/g, "");
    
    let rawHistory = [];

    for (const [feedKey, feedObj] of Object.entries(statsData.feeds)) {
      const feedMetric = feedObj.meta ? String(feedObj.meta.metric).toLowerCase().replace(/[^a-z0-9]/g, "") : "";
      if (feedMetric === metricClean) {
        const dataArr = feedObj.data || [];
        if (dataArr.length > 0) {
          const samplePoint = dataArr[dataArr.length - 1];
          const hasCity = Object.keys(samplePoint).some(k => k.toLowerCase().replace(/[^a-z0-9]/g, "") === cityClean);
          if (hasCity) {
            rawHistory = dataArr.slice(-12).map(item => {
              let val = 0;
              for (const [k, v] of Object.entries(item)) {
                if (k.toLowerCase().replace(/[^a-z0-9]/g, "") === cityClean) {
                  val = parseFloat(v) || 0;
                }
              }
              let shortDate = item.Date ? item.Date.replace(/\d{4}/, '').trim() : '';
              return { date: shortDate, val: val };
            });
            break;
          }
        }
      }
    }

    if (rawHistory.length === 0) return null;

    const vals = rawHistory.map(h => h.val);
    let minVal = Math.min(...vals);
    let maxVal = Math.max(...vals);

    if (minVal === maxVal) {
      minVal = minVal * 0.95;
      maxVal = maxVal * 1.05 || 10;
    }

    const padLeft = 5;
    const padRight = 5;
    const padTop = 6;
    const padBottom = 6;
    const chartWidth = width - padLeft - padRight;
    const chartHeight = height - padTop - padBottom;

    const points = rawHistory.map((item, idx) => {
      const x = padLeft + (idx / (rawHistory.length - 1)) * chartWidth;
      const y = padTop + chartHeight - ((item.val - minVal) / (maxVal - minVal)) * chartHeight;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(" ");

    const latest = rawHistory[rawHistory.length - 1].val;

    const formatVal = (v) => {
      if (metricClean.includes("percent")) {
        const pct = v <= 1 ? v * 100 : v;
        return pct.toFixed(1) + "%";
      }
      if (metricClean.includes("price")) {
        return `$${Math.round(v).toLocaleString('en-US')}`;
      }
      if (metricClean.includes("supply") || metricClean.includes("shows")) {
        return v.toFixed(1);
      }
      return Math.round(v).toString();
    };

    return {
      points: points,
      minLabel: formatVal(minVal),
      maxLabel: formatVal(maxVal),
      latestLabel: formatVal(latest),
      dates: [rawHistory[0].date, rawHistory[Math.floor(rawHistory.length / 2)].date, rawHistory[rawHistory.length - 1].date],
      lastX: (padLeft + chartWidth).toFixed(1),
      lastY: (padTop + chartHeight - ((latest - minVal) / (maxVal - minVal)) * chartHeight).toFixed(1)
    };
  });

  // Dynamic Hourly Market Velocity Chart Builder
  eleventyConfig.addFilter("buildHourlyVelocityChart", function(cityName, width = 500, height = 90) {
    const historicalData = readJsonDataFile("hourly_market_historical.json") || [];
    const currentData = readJsonDataFile("hourly_market.json") || [];
    if (!cityName) return null;

    const cityClean = String(cityName).toLowerCase().replace(/[^a-z0-9]/g, "");
    
    let snapshots = historicalData.filter(item => item.City && String(item.City).toLowerCase().replace(/[^a-z0-9]/g, "") === cityClean).slice(-5);
    
    const currRecord = currentData.find(item => item.City && String(item.City).toLowerCase().replace(/[^a-z0-9]/g, "") === cityClean);
    if (currRecord) {
      snapshots.push({
        Timestamp: "Today",
        "New Listings": currRecord["New Listings"],
        "Price Drops": currRecord["Price Drops"],
        "Pending": currRecord["Pending"],
        "Sold": currRecord["Sold"]
      });
    }

    if (snapshots.length < 2) return null;

    const parseNum = (val) => Math.max(0, parseFloat(String(val || "0").replace(/[^0-9.]/g, "")) || 0);

    const newListingsArr = snapshots.map(s => parseNum(s["New Listings"]));
    const priceDropsArr = snapshots.map(s => parseNum(s["Price Drops"]));
    const pendingArr = snapshots.map(s => parseNum(s["Pending"]));
    const soldArr = snapshots.map(s => parseNum(s["Sold"]));

    const allVals = [...newListingsArr, ...priceDropsArr, ...pendingArr, ...soldArr];
    const maxVal = Math.max(10, Math.ceil(Math.max(...allVals) * 1.15));

    const padLeft = 40;
    const padRight = 15;
    const padTop = 10;
    const padBottom = 20;
    const chartWidth = width - padLeft - padRight;
    const chartHeight = height - padTop - padBottom;

    const makePoly = (arr) => {
      return arr.map((v, idx) => {
        const x = padLeft + (idx / (arr.length - 1)) * chartWidth;
        const y = padTop + chartHeight - (v / maxVal) * chartHeight;
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      }).join(" ");
    };

    const dates = snapshots.map(s => s.Timestamp ? s.Timestamp.split('/2026')[0] : '');

    return {
      pointsNew: makePoly(newListingsArr),
      pointsDrops: makePoly(priceDropsArr),
      pointsPending: makePoly(pendingArr),
      pointsSold: makePoly(soldArr),
      maxLabel: maxVal.toString(),
      midLabel: Math.round(maxVal / 2).toString(),
      minLabel: "0",
      dates: dates,
      lastX: (padLeft + chartWidth).toFixed(1),
      lastYNew: (padTop + chartHeight - (newListingsArr[newListingsArr.length - 1] / maxVal) * chartHeight).toFixed(1),
      lastYSold: (padTop + chartHeight - (soldArr[soldArr.length - 1] / maxVal) * chartHeight).toFixed(1)
    };
  });

  // Multi-Line Mortgage 30-Day Trend Chart Generator
  eleventyConfig.addFilter("buildMortgageTrendChart", function(dummyInput, width = 280, height = 70) {
    const data = readJsonDataFile("hourly_rates.json") || readJsonDataFile("mortgage_rates.json");
    if (!data || !Array.isArray(data) || data.length === 0) return null;

    const actualWidth = 280;
    const actualHeight = 70;

    const parseRate = (str) => {
      if (!str) return null;
      const v = parseFloat(String(str).replace(/[^0-9.]/g, ""));
      return isNaN(v) ? null : v;
    };

    const validEntries = data.map(r => ({
      date: r.Date ? r.Date.split(' ')[0] : '',
      conv: parseRate(r["30 Year Conventional"]),
      fha: parseRate(r["30 Year FHA"]),
      va: parseRate(r["30 Year VA"])
    })).filter(r => r.conv !== null && r.fha !== null && r.va !== null);

    const recent = validEntries.slice(-30);
    if (recent.length < 2) return null;

    const convVals = recent.map(r => r.conv);
    const fhaVals = recent.map(r => r.fha);
    const vaVals = recent.map(r => r.va);

    const allVals = [...convVals, ...fhaVals, ...vaVals];
    let minVal = Math.min(...allVals) - 0.05;
    let maxVal = Math.max(...allVals) + 0.05;

    if (minVal === maxVal) {
      minVal -= 0.1;
      maxVal += 0.1;
    }

    const padLeft = 32;
    const padRight = 10;
    const padTop = 10;
    const padBottom = 18;
    const chartWidth = actualWidth - padLeft - padRight;
    const chartHeight = actualHeight - padTop - padBottom;

    const makePolyline = (vals) => {
      return vals.map((v, idx) => {
        const x = padLeft + (idx / (vals.length - 1)) * chartWidth;
        const y = padTop + chartHeight - ((v - minVal) / (maxVal - minVal)) * chartHeight;
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      }).join(" ");
    };

    const getY = (v) => (padTop + chartHeight - ((v - minVal) / (maxVal - minVal)) * chartHeight).toFixed(1);

    return {
      convPoints: makePolyline(convVals),
      fhaPoints: makePolyline(fhaVals),
      vaPoints: makePolyline(vaVals),
      minLabel: minVal.toFixed(2) + "%",
      maxLabel: maxVal.toFixed(2) + "%",
      lastX: (actualWidth - padRight).toFixed(1),
      lastYConv: getY(convVals[convVals.length - 1]),
      lastYFha: getY(fhaVals[fhaVals.length - 1]),
      lastYVa: getY(vaVals[vaVals.length - 1])
    };
  });

  // Redfin Regional Seattle Migration Data Loader
  eleventyConfig.addFilter("getSeattleMigration", function() {
    const raw = readJsonDataFile("redfin_migration.json");
    if (!raw || !raw.data || !raw.data.metros) return { top_inflow: [], top_outflow: [] };
    
    const seattleObj = raw.data.metros["Seattle, WA"] || {};
    
    return {
      top_inflow: (seattleObj.top_inflow || []).slice(0, 5),
      top_outflow: (seattleObj.top_outflow || []).slice(0, 5)
    };
  });

  // Redfin Regional Affordability & Purchasing Power Loader
  eleventyConfig.addFilter("getAffordabilityStats", function() {
    const data = readJsonDataFile("redfin_monthly_stats.json") || readJsonDataFile("redfin_stats.json");
    if (!data || !data.affordability) return null;

    const rows = data.affordability.filter(r => String(r["REGION NAME"] || "").toLowerCase().includes("seattle"));
    if (!rows.length) return null;

    const lastUpdated = rows[0]["LAST UPDATED"] || "2026-07-28";

    const propertyTypes = ["Condo/Co-op", "Starter Home", "Townhouse", "Single Family"];
    const propTiers = propertyTypes.map(pt => {
      return rows.find(r => r["PROPERTY TYPE"] === pt && r["INCOME GROUP"] === "All" && Number(r["DOWN PAYMENT PERCENT (%)"]) === 3.5) || null;
    }).filter(Boolean);

    const dpTiers = [3.5, 5.0, 10.0, 15.0, 20.0].map(dp => {
      return rows.find(r => r["PROPERTY TYPE"] === "Starter Home" && r["INCOME GROUP"] === "All" && Number(r["DOWN PAYMENT PERCENT (%)"]) === dp) || null;
    }).filter(Boolean);

    const incomeGroups = ["Renter", "All", "Homeowner"].map(ig => {
      return rows.find(r => r["PROPERTY TYPE"] === "Starter Home" && r["INCOME GROUP"] === ig && Number(r["DOWN PAYMENT PERCENT (%)"]) === 3.5) || null;
    }).filter(Boolean);

    return {
      last_updated: lastUpdated,
      property_tiers: propTiers,
      dp_tiers: dpTiers,
      income_groups: incomeGroups
    };
  });

  // Sports Loader (RESTORED FOR NEIGHBORHOOD-DATA.NJK AND SIDEBARS)
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
  eleventyConfig.addFilter("getCityEvents", function(citySlug, limit = 20) {
    const cityEventsData = readJsonDataFile("city_events.json");
    if (!cityEventsData || !citySlug) return [];
    
    const cityEvents = findKeyCaseInsensitive(cityEventsData, citySlug);
    if (!cityEvents || !Array.isArray(cityEvents)) return [];

    return cityEvents.slice(0, limit);
  });

  // Redfin City Monthly Telemetry Loader
  eleventyConfig.addFilter("getRedfinCityStats", function(cityName) {
    const data = readJsonDataFile("redfin_stats.json") || readJsonDataFile("redfin_monthly_stats.json");
    if (!data || !Array.isArray(data) || !cityName) return null;
    const cleanTarget = String(cityName).toLowerCase().replace(/[^a-z0-9]/g, "");
    return data.find(item => item.city && String(item.city).toLowerCase().replace(/[^a-z0-9]/g, "") === cleanTarget) || null;
  });

  // Redfin Migration Flow Loader
  eleventyConfig.addFilter("getRedfinMigration", function(cityName) {
    const raw = readJsonDataFile("redfin_migration.json");
    if (!raw || !raw.data || !raw.data.metros || !cityName) return null;
    const metros = raw.data.metros;
    const cleanTarget = String(cityName).toLowerCase().replace(/[^a-z0-9]/g, "");
    const matchedKey = Object.keys(metros).find(k => k.toLowerCase().replace(/[^a-z0-9]/g, "").includes(cleanTarget));
    return matchedKey ? metros[matchedKey] : null;
  });

  // Daily Mortgage Rates Loader
  eleventyConfig.addFilter("getLatestMortgageRates", function() {
    const data = readJsonDataFile("hourly_rates.json") || readJsonDataFile("mortgage_rates.json");
    if (!data || !Array.isArray(data) || data.length === 0) return null;
    return data[data.length - 1];
  });

  // Hourly Market Velocity Loader
  eleventyConfig.addFilter("getHourlyMarketPulse", function(cityName) {
    const data = readJsonDataFile("hourly_market.json") || readJsonDataFile("city_hourly_updates.json");
    if (!data || !Array.isArray(data) || !cityName) return null;
    const cleanTarget = String(cityName).toLowerCase().replace(/[^a-z0-9]/g, "");
    for (let i = data.length - 1; i >= 0; i--) {
      if (data[i].City && String(data[i].City).toLowerCase().replace(/[^a-z0-9]/g, "") === cleanTarget) {
        return data[i];
      }
    }
    return null;
  });

  // Previous Top-of-Hour Timestamp Generator
  eleventyConfig.addFilter("topOfHourTime", function() {
    const now = new Date();
    let hours = now.getHours();
    const ampm = hours >= 12 ? 'PM' : 'AM';
    hours = hours % 12;
    hours = hours ? hours : 12;
    return `${hours}:00 ${ampm} Today`;
  });

  // Collections
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