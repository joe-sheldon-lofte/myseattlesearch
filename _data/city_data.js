/* File: _data/city_data.js */

const rawData = require('../data/city_data.json');

const uniqueCities = [];
const seenCities = new Set();

for (const item of rawData) {
  if (item.City && !seenCities.has(item.City)) {
    seenCities.add(item.City);

    // Create a clean URL slug (e.g. "Lake Forest Park" -> "lake-forest-park")
    const slug = item.City
      .toLowerCase()
      .trim()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '');

    uniqueCities.push({
      ...item, // Retains all raw original JSON properties as fallbacks
      name: item.City,
      slug: slug,
      county: item.County,
      
      // School & Academic Mappings
      schoolDistrict: item["School District"],
      ospiDistrictId: item["OSPI District ID"],
      schoolWebsite: item["School Website"],
      
      // Civic & Emergency URL Mappings
      cityWebsite: item["City Website"],
      permitUrl: item["Permit URL"],
      policeUrl: item["Police URL"],
      policeDepartment: item["Police Department Name"],
      fireDepartment: item["Fire Department Name"],
      wsrbRating: item["FD WSRB Rating"],
      
      // Geographic & Demographics
      latitude: item.Latitude,
      longitude: item.Longitude,
      population: item.FallbackPopulation,
      landSquareMiles: item["Land Area Square Mileage"]
    });
  }
}

// Passes the normalized array to Eleventy under global data key `city_data`
module.exports = uniqueCities;