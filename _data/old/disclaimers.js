const fs = require('fs');
const path = require('path');

module.exports = function() {
  const filePath = path.join(__dirname, '../data/disclaimers.json');
  
  if (!fs.existsSync(filePath)) {
    console.warn("⚠️ Data Engine Warning: 'data/disclaimers.json' not found. Falling back to empty object.");
    return {
      "site": ""
    };
  }

  try {
    const rawData = fs.readFileSync(filePath, 'utf-8');
    return JSON.parse(rawData);
  } catch (error) {
    console.error("❌ Critical Data Engine Parsing Failure (disclaimers.json):", error);
    return {};
  }
};