/* File: _data/personalStats.js */
const fs = require('fs');
const path = require('path');

module.exports = function() {
  const filePath = path.join(__dirname, '../data/stats.json');
  
  if (!fs.existsSync(filePath)) {
    console.warn("⚠️ Data Engine Warning: 'data/stats.json' not found. Falling back to empty object.");
    return {
      "Closed Sales": "--",
      "Total Sales Volume": "--",
      "Average Rating": "--"
    };
  }

  try {
    const rawData = fs.readFileSync(filePath, 'utf-8');
    return JSON.parse(rawData);
  } catch (error) {
    console.error("❌ Critical Data Engine Parsing Failure (stats.json):", error);
    return {};
  }
};