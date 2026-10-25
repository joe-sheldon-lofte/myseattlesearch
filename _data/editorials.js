// File: _data/editorials.js
const fs = require('fs');
const path = require('path');

function slugify(text) {
  if (!text) return '';
  return String(text)
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9\s-]/g, '')
    .replace(/[\s_]+/g, '-')
    .replace(/-+/g, '-');
}

function parseDate(str) {
  if (!str) return null;
  const s = String(str).trim();
  // Match YYYY-MM-DD
  const isoMatch = s.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
  if (isoMatch) {
    return new Date(parseInt(isoMatch[1], 10), parseInt(isoMatch[2], 10) - 1, parseInt(isoMatch[3], 10));
  }
  const d = new Date(s);
  return isNaN(d.getTime()) ? null : d;
}

module.exports = function() {
  const editorialsMap = {};
  const dataDir = path.join(__dirname, '../data');
  const cityDataPath = path.join(dataDir, 'city_data.json');
  const editorialsDir = path.join(dataDir, 'editorials');

  if (!fs.existsSync(cityDataPath) || !fs.existsSync(editorialsDir)) {
    return editorialsMap;
  }

  let cities = [];
  try {
    const raw = fs.readFileSync(cityDataPath, 'utf8');
    cities = JSON.parse(raw);
  } catch (err) {
    console.error('Error reading city_data.json in _data/editorials.js:', err);
    return editorialsMap;
  }

  const now = new Date();

  cities.forEach(city => {
    const cityName = city.City || city.name;
    if (!cityName) return;

    const slug = slugify(cityName);
    const mdPath = path.join(editorialsDir, `${slug}.md`);

    if (!fs.existsSync(mdPath)) return;

    let mdContent = '';
    try {
      mdContent = fs.readFileSync(mdPath, 'utf8');
    } catch (e) {
      return;
    }

    // Inspect EPDate1 through EPDate12
    const validEps = [];
    for (let i = 1; i <= 12; i++) {
      const dateVal = city[`EPDate${i}`] || city[`EP Date ${i}`] || city[`EPdate${i}`] || city[`ep_date_${i}`];
      if (dateVal) {
        const parsed = parseDate(dateVal);
        if (parsed) {
          validEps.push({ ep: i, date: parsed });
        }
      }
    }

    // Filter to dates <= current build date
    const pastEps = validEps.filter(item => item.date <= now);
    let activeEp = 1;

    if (pastEps.length > 0) {
      pastEps.sort((a, b) => a.date - b.date);
      activeEp = pastEps[pastEps.length - 1].ep;
    } else if (validEps.length > 0) {
      validEps.sort((a, b) => a.date - b.date);
      activeEp = validEps[0].ep;
    }

    // Slice markdown between `### **EP{activeEp}**` and the next `### **EP` or EOF
    const epRegex = new RegExp(`###\\s*\\*\\*EP${activeEp}\\*\\*([\\s\\S]*?)(?=###\\s*\\*\\*EP|$)`, 'i');
    const match = mdContent.match(epRegex);

    if (match && match[1]) {
      const rawText = match[1].trim();
      const paragraphs = rawText
        .split(/\r?\n\s*\r?\n/)
        .map(p => p.trim())
        .filter(p => p.length > 0 && !p.startsWith('#'));

      const html = paragraphs.map(p => `<p>${p}</p>`).join('\n');

      editorialsMap[slug] = html;
      editorialsMap[cityName.toLowerCase()] = html;
      editorialsMap[cityName] = html;
    }
  });

  return editorialsMap;
};