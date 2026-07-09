/* File: _data/city_data.js */

// This acts as a proxy, safely passing ONLY the city_data JSON into Eleventy's build engine 
// while protecting the compiler from NaN syntax errors inside the other automated data files.
/* File: _data/city_data.js */

const rawData = require('../data/city_data.json');

// Create an empty array to hold the unique cities, and a Set to track what we've seen
const uniqueCities = [];
const seenCities = new Set();

for (const item of rawData) {
    // We assume the column name for the city in your JSON is "City". 
    // If it's lowercase "city" or "Name", change `item.City` to match your JSON exactly.
    if (!seenCities.has(item.City)) {
        seenCities.add(item.City);
        uniqueCities.push(item);
    }
}

// Pass the perfectly deduplicated list to Eleventy
module.exports = uniqueCities;