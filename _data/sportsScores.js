/* File: _data/sportsScores.js */
const fs = require('fs');
const path = require('path');

module.exports = function() {
  const fileSource = path.join(__dirname, '../data/sports_scores.json');
  if (fs.existsSync(fileSource)) {
    try {
      return JSON.parse(fs.readFileSync(fileSource, 'utf8'));
    } catch (e) {
      console.error('❌ Build failure reading sports scores payload:', e);
    }
  }
  return []; // Fallback empty array prevents build failures
};