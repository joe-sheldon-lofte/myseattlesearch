/* File: _data/sales.js */
const fs = require('fs');
const path = require('path');

module.exports = function() {
  const filePath = path.join(__dirname, '../data/sales.json');
  if (fs.existsSync(filePath)) {
    const rawData = fs.readFileSync(filePath, 'utf-8');
    let salesData = JSON.parse(rawData);

    // Process Regional Taxonomy
    salesData = salesData.map(property => {
      if (!property.City) return { ...property, regions: ['other'] };
      
      const city = property.City.trim().toLowerCase();
      const regionsList = [];

      const kingCountyCities = [
        'seattle', 'bellevue', 'kirkland', 'shoreline', 'renton', 'kent', 
        'federal way', 'auburn', 'lake forest park', 'kenmore', 'woodinville', 
        'issaquah', 'sammamish', 'burien', 'seatac', 'covington', 'maple valley'
      ];
      const snohomishCountyCities = [
        'everett', 'edmonds', 'lynwood', 'lynnwood', 'marysville', 'snohomish', 
        'mountlake terrace', 'brier', 'lake stevens', 'stanwood', 'bothell'
      ];
      const northSoundCities = [
        'anacortes', 'bellingham', 'blaine', 'ferndale', 'mount vernon', 
        'sedro woolley', 'la conner'
      ];

      if (kingCountyCities.includes(city)) regionsList.push('king-county');
      if (snohomishCountyCities.includes(city)) regionsList.push('snohomish-county');
      if (northSoundCities.includes(city)) regionsList.push('north-sound');

      // Dual-Tagging Overlap Policy
      const overlapCities = ['edmonds', 'lynwood', 'lynnwood', 'everett', 'lake stevens', 'snohomish', 'stanwood'];
      if (overlapCities.includes(city)) regionsList.push('north-sound');

      if (regionsList.length === 0) regionsList.push('other');

      return { ...property, regions: regionsList };
    });

    // Master Sort: Active -> Pending -> Sold (Newest First)
    const statusPriority = { 'Active': 1, 'Pending': 2, 'Sold': 3 };

    salesData.sort((a, b) => {
      if (statusPriority[a.Status] !== statusPriority[b.Status]) {
        return statusPriority[a.Status] - statusPriority[b.Status];
      }
      if (a.Status === 'Sold') {
        const dateA = a['Selling Date'] ? new Date(a['Selling Date']) : new Date(0);
        const dateB = b['Selling Date'] ? new Date(b['Selling Date']) : new Date(0);
        return dateB - dateA; 
      }
      return 0;
    });

    return salesData;
  }
  return [];
};