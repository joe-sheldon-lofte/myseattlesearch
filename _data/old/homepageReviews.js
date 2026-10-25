/* File: _data/homepageReviews.js */
const fs = require('fs');
const path = require('path');

module.exports = function() {
  const filePath = path.join(__dirname, '../data/reviews.json');
  
  console.log(`\n🔍 [Reviews Engine] Attempting to read data sink from: ${filePath}`);
  
  if (!fs.existsSync(filePath)) {
    console.warn("⚠️ [Reviews Engine] Local file 'data/reviews.json' not found. Falling back to empty array.");
    return [];
  }

  try {
    const rawData = fs.readFileSync(filePath, 'utf-8');
    const reviewsCollection = JSON.parse(rawData);
    
    console.log(`📊 [Reviews Engine] Successfully loaded ${reviewsCollection.length} total raw records from JSON.`);
    
    // Hardened extraction block to filter matching rows regardless of layout anomalies
    const validHomepageEntries = reviewsCollection.filter((review, index) => {
      if (!review) return false;
      
      const targetFlag = review['index.html'];
      const textBody = review['Full Review'];
      
      const matchesPage = targetFlag && String(targetFlag).trim().toLowerCase() === 'x';
      const hasValidText = textBody && String(textBody).trim().length > 0;
      
      return matchesPage && hasValidText;
    });

    console.log(`🎯 [Reviews Engine] Filter matched ${validHomepageEntries.length} items flagged with 'x' for index.html.`);

    // Build-Time Randomization Loop (Fisher-Yates Shuffle Engine)
    for (let i = validHomepageEntries.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [validHomepageEntries[i], validHomepageEntries[j]] = [validHomepageEntries[j], validHomepageEntries[i]];
    }

    const finalSelection = validHomepageEntries.slice(0, 3);
    console.log(`🚀 [Reviews Engine] Randomly captured exactly ${finalSelection.length} static cards for Nunjucks unrolling.\n`);
    
    return finalSelection;
  } catch (error) {
    console.error("❌ [Reviews Engine] Critical internal failure during processing pass:", error);
    return [];
  }
};