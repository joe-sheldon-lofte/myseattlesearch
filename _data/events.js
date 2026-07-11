/* File: _data/events.js */
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

  // 24h Time -> 12h Standard AM/PM
  function formatDisplayTime(timeStr) {
    if (!timeStr) return '';
    const parts = timeStr.split(':');
    if (parts.length >= 2) {
      let hour = parseInt(parts[0], 10);
      const minute = parts[1];
      const ampm = hour >= 12 ? 'PM' : 'AM';
      hour = hour % 12;
      hour = hour ? hour : 12;
      return `${hour}:${minute} ${ampm}`;
    }
    return timeStr;
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