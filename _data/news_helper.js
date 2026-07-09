/* File: _data/news_helper.js */
const fs = require("fs");
const path = require("path");

module.exports = function() {
  const sourceDataFile = path.join(__dirname, "../data/market_news.json");
  
  if (!fs.existsSync(sourceDataFile)) {
    return [];
  }
  
  const rawPayload = JSON.parse(fs.readFileSync(sourceDataFile, "utf8"));
  
  const routerConfiguration = [
    { name: "All News", slug: "", filterKey: "all" },
    { name: "Real Estate", slug: "real-estate", filterKey: "real-estate" },
    { name: "Business", slug: "business", filterKey: "business" },
    { name: "North Sound", slug: "north-sound", filterKey: "north-sound" },
    { name: "Seattle", slug: "seattle", filterKey: "seattle" },
    { name: "Eastside", slug: "eastside", filterKey: "eastside" },
    { name: "Snohomish County", slug: "snohomish-county", filterKey: "snohomish-county" },
    { name: "South King", slug: "south-king", filterKey: "south-king" }
  ];

  return routerConfiguration.map(route => {
    let categorizedStories = [];
    
    if (route.filterKey === "all") {
      categorizedStories = rawPayload;
    } else if (route.filterKey === "snohomish-county") {
      categorizedStories = rawPayload.filter(story => 
        story.category === "snohomish-county" || story.category === "north-sound"
      );
    } else {
      categorizedStories = rawPayload.filter(story => story.category === route.filterKey);
    }

    // Capture the top 50 strictly sorted stories for the channel feed layout
    const slice50 = categorizedStories.slice(0, 50);

    const dynamicCities = new Set();
    const dynamicSources = new Set();

    slice50.forEach(story => {
      dynamicSources.add(story.source);
      if (story.cities && story.cities.length > 0) {
        story.cities.forEach(city => dynamicCities.add(city));
      }
    });

    return {
      subCategoryName: route.name,
      activeFilter: route.filterKey,
      permalinkPath: route.slug ? `news/${route.slug}/index.html` : "news/index.html",
      articles: slice50,
      tabs: routerConfiguration,
      sidebarCities: Array.from(dynamicCities).sort(),
      sidebarSources: Array.from(dynamicSources).sort()
    };
  });
};