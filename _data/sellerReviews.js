/* File: _data/sellerReviews.js */
const fs = require('fs');
const path = require('path');

module.exports = function() {
  const filePath = path.join(__dirname, '../data/reviews.json');
  
  if (!fs.existsSync(filePath)) {
    console.warn("⚠️ Data Engine Warning: 'data/reviews.json' not found inside seller module. Falling back to empty array.");
    return [];
  }

  try {
    const rawData = fs.readFileSync(filePath, 'utf-8');
    const reviewsCollection = JSON.parse(rawData);
    
    // Filter rows specifically flagged with an 'x' for sellers.html execution
    const validSellerEntries = reviewsCollection.filter(review => {
      if (!review) return false;
      
      const targetFlag = review['sellers.html'];
      const textBody = review['Full Review'];
      
      const matchesPage = targetFlag && String(targetFlag).trim().toLowerCase() === 'x';
      const hasValidText = textBody && String(textBody).trim().length > 0;
      
      return matchesPage && hasValidText;
    });

    // Build-Time Randomization Loop (Fisher-Yates Shuffle Engine)
    for (let i = validSellerEntries.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [validSellerEntries[i], validSellerEntries[j]] = [validSellerEntries[j], validSellerEntries[i]];
    }

    // Extract a maximum slice of exactly 3 clean static elements
    return validSellerEntries.slice(0, 3);
  } catch (error) {
    console.error("❌ Critical Data Engine Shuffling Failure (sellerReviews):", error);
    return [];
  }
};