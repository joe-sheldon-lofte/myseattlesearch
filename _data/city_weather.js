// File: _data/city_weather.js
const fs = require('fs');
const path = require('path');

module.exports = function() {
  const filePath = path.join(__dirname, '../data/city_weather.json');
  if (fs.existsSync(filePath)) {
    return JSON.parse(fs.readFileSync(filePath, 'utf8'));
  }
  return {};
};