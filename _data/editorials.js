// File: _data/editorials.js (or helper in .eleventy.js)
const fs = require('fs');
const path = require('path');
const markdownIt = require('markdown-it')({ html: true, breaks: true });

function getActiveEpisodeNumber(neighborhoodRecord, buildDate = new Date()) {
  const targetDate = new Date(buildDate);
  const candidates = [];

  for (let i = 1; i <= 12; i++) {
    // Support all core CSV/JSON date key conventions
    const val = neighborhoodRecord[`EPDate${i}`] || 
                neighborhoodRecord[`EP Date ${i}`] || 
                neighborhoodRecord[`ep_date_${i}`] ||
                neighborhoodRecord[`EP_Date_${i}`];
    if (val) {
      const d = new Date(val);
      if (!isNaN(d.getTime())) {
        candidates.push({ ep: i, date: d });
      }
    }
  }

  // Sort chronologically
  candidates.sort((a, b) => a.date - b.date);

  // Find nearest recent past date (<= buildDate)
  const past = candidates.filter(c => c.date <= targetDate);
  if (past.length > 0) {
    return past[past.length - 1].ep;
  }
  
  // Cycle rollover fallback (e.g. early January before EP1)
  return candidates.length > 0 ? candidates[candidates.length - 1].ep : 1;
}

function resolveNeighborhoodEditorial(neighborhoodSlug, epNumber) {
  const filePath = path.join(process.cwd(), 'data', 'editorials', `${neighborhoodSlug}.md`);
  if (!fs.existsSync(filePath)) return null;

  const rawMd = fs.readFileSync(filePath, 'utf-8');
  const targetMarker = `### **EP${epNumber}**`;
  const startIndex = rawMd.indexOf(targetMarker);
  
  if (startIndex === -1) return null;

  // Extract from target header past the marker
  const afterMarker = rawMd.slice(startIndex + targetMarker.length);
  
  // Find where the next episode begins (or end of file)
  const nextMatch = afterMarker.match(/\n###\s+\*\*EP\d+\*\*/);
  const epContent = nextMatch ? afterMarker.slice(0, nextMatch.index) : afterMarker;

  return markdownIt.render(epContent.trim());
}

module.exports = { getActiveEpisodeNumber, resolveNeighborhoodEditorial };