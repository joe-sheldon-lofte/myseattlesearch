const fs = require('fs');
const path = require('path');

module.exports = function() {
  const eventsPath = path.join(__dirname, '../data/events.json');
  const hostsPath = path.join(__dirname, '../data/eventhosts.json');
  
  let allEvents = [];
  let rawHosts = [];

  if (fs.existsSync(eventsPath)) {
    try {
      allEvents = JSON.parse(fs.readFileSync(eventsPath, 'utf-8'));
    } catch (e) {
      console.error("❌ Data Error: Failed to parse events.json:", e);
    }
  }

  if (fs.existsSync(hostsPath)) {
    try {
      rawHosts = JSON.parse(fs.readFileSync(hostsPath, 'utf-8'));
    } catch (e) {
      console.error("❌ Data Error: Failed to parse eventhosts.json:", e);
    }
  }

  // YYYY-MM-DD -> MM/DD/YYYY
  function formatDisplayDate(dateStr) {
    if (!dateStr) return '';
    const parts = dateStr.split('-');
    if (parts.length === 3) {
      return `${parts[1]}/${parts[2]}/${parts[0]}`;
    }
    return dateStr;
  }

  // Smart Time Formatter (Handles 24h or existing 12h AM/PM strings without duplicating)
  function formatDisplayTime(timeStr) {
    if (!timeStr) return '';
    let cleanStr = String(timeStr).trim();

    if (/am|pm/i.test(cleanStr)) {
      return cleanStr.replace(/\s+/g, ' ').toUpperCase();
    }

    const parts = cleanStr.split(':');
    if (parts.length >= 2) {
      let hour = parseInt(parts[0], 10);
      if (isNaN(hour)) return cleanStr;

      let minute = parts[1].substring(0, 2);
      const ampm = hour >= 12 ? 'PM' : 'AM';
      hour = hour % 12;
      hour = hour ? hour : 12;
      return `${hour}:${minute} ${ampm}`;
    }

    return cleanStr;
  }

  // ISO-8601 24-Hour Formatter for Schema.org Validation
  function toIsoDateTime(dateStr, timeStr) {
    if (!dateStr) return '';
    if (!timeStr) return `${dateStr}T00:00:00-07:00`;
    let clean = String(timeStr).trim();
    let isPM = /pm/i.test(clean);
    let isAM = /am/i.test(clean);
    let numbers = clean.replace(/[^0-9:]/g, '').split(':');
    let hour = parseInt(numbers[0] || '0', 10);
    let minute = numbers[1] ? numbers[1].substring(0, 2) : '00';
    
    if (isPM && hour < 12) hour += 12;
    if (isAM && hour === 12) hour = 0;
    
    let hh = String(hour).padStart(2, '0');
    let mm = String(minute).padStart(2, '0');
    return `${dateStr}T${hh}:${mm}:00-07:00`;
  }

  // Resilient multi-key normalization directory mapping loop
  const hostsLookup = {};
  const hostsListNormalized = [];

  rawHosts.forEach(h => {
    if (!h) return;
    const rawId = h['Host ID'] !== undefined ? h['Host ID'] : h['id'];
    if (rawId !== undefined && rawId !== null) {
      const cleanId = String(rawId).trim().toLowerCase().replace('.0', '');
      const normalizedHost = {
        id: cleanId,
        name: h['Host Name'] || h['name'] || '',
        phone: h['Host Phone'] || h['phone'] || '',
        email: h['Host Email'] || h['email'] || '',
        website: h['Host Website'] || h['website'] || '',
        description: h['Host Description'] || h['description'] || '',
        photo: h['Host Photo Link'] || h['photo'] || ''
      };
      hostsLookup[cleanId] = normalizedHost;
      hostsListNormalized.push(normalizedHost);
    }
  });

  const now = new Date();
  const laDateString = now.toLocaleDateString('en-US', { timeZone: 'America/Los_Angeles' });
  const todayMidnight = new Date(laDateString);

  const featured = [];
  const partner = [];
  const allActive = [];

  allEvents.forEach(event => {
    if (!event.id || event.status !== 'Active' || !event.display) return;

    // Direct host relation stitching fallback
    let eventHosts = event.hosts || [];
    if (eventHosts.length === 0 && event.hostIds) {
      const idParts = String(event.hostIds).split(',');
      idParts.forEach(idStr => {
        const cleanId = idStr.trim().toLowerCase().replace('.0', '');
        if (hostsLookup[cleanId]) {
          eventHosts.push(hostsLookup[cleanId]);
        }
      });
    } else {
      eventHosts = eventHosts.map(h => {
        const hId = String(h.id || h['Host ID'] || '').trim().toLowerCase().replace('.0', '');
        return hostsLookup[hId] || h;
      });
    }
    event.hosts = eventHosts;

    // Inject human-readable display parameters
    event.displayDate = formatDisplayDate(event.date);
    event.displayStartTime = formatDisplayTime(event.startTime);
    event.displayEndTime = formatDisplayTime(event.endTime);

    // Inject valid ISO-8601 timestamps for Schema.org
    event.isoStartDate = toIsoDateTime(event.date, event.startTime);
    event.isoEndDate = toIsoDateTime(event.date, event.endTime);

    allActive.push(event);

    if (event.date) {
      const eventDateObj = new Date(event.date + 'T00:00:00');
      if (eventDateObj < todayMidnight) return;
    }

    const isHostedByJoe = event.hosts && event.hosts.some(h => String(h.id) === '1');
    if (isHostedByJoe) {
      featured.push(event);
    } else {
      partner.push(event);
    }
  });

  const sortChronologically = (a, b) => new Date(a.date) - new Date(b.date);
  featured.sort(sortChronologically);
  partner.sort(sortChronologically);

  return {
    featured,
    partner,
    allActive,
    hostsList: hostsListNormalized
  };
};