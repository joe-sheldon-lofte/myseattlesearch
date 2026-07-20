const fs = require('fs');
const path = require('path');

module.exports = function() {
  const filePath = path.join(__dirname, '../data/professionals.json');
  
  if (!fs.existsSync(filePath)) {
    console.warn("⚠️ Data Engine Warning: 'data/professionals.json' not found inside vendor module.");
    return { vendors: [], categories: [] };
  }

  try {
    const rawData = fs.readFileSync(filePath, 'utf-8');
    let data = JSON.parse(rawData);
    
    // Enforce basic cleanup constraints
    data = data.filter(row => row && row['Category'] && String(row['Category']).trim() && row['Business/Vendor Name'] && String(row['Business/Vendor Name']).trim());

    // Alphanumeric sorting: Sort by Category first, then by Business Name
    data.sort((a, b) => {
      const compareCategory = String(a['Category']).trim().localeCompare(String(b['Category']).trim());
      if (compareCategory !== 0) return compareCategory;
      return String(a['Business/Vendor Name']).trim().localeCompare(String(b['Business/Vendor Name']).trim());
    });

    // Process each record to build layout fields matching legacy selectors
    const processedVendors = data.map(row => {
      const category = String(row['Category']).trim();
      const rawName = String(row['Business/Vendor Name']).trim();
      
      let name = rawName;
      let company = '';
      
      // Separate company parentheticals from the primary business name
      const match = rawName.match(/^(.*?)\s*\((.*?)\)$/);
      if (match) {
        name = match[1].trim();
        company = match[2].trim();
      }

      // Generate a URL-safe slug for individual professional landing pages
      const slug = rawName.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)+/g, '');

      let phone = row['Phone Number'] || '';
      phone = String(phone).trim();
      const phoneClean = phone.replace(/[^\d]/g, '');

      const email = row['Email'] ? String(row['Email']).trim() : '';
      
      let website = row['Website'] ? String(row['Website']).trim() : '';
      if (website && !website.startsWith('http')) {
        website = 'https://' + website;
      }

      const additionalInfo = row['Additional Info'] ? String(row['Additional Info']).trim() : '';
      const legalReq = row['Legal Requirements'] ? String(row['Legal Requirements']).trim() : '';
      const legalLink = row['Legal Requirements Link'] ? String(row['Legal Requirements Link']).trim() : '';

      return {
        category,
        name,
        company,
        slug,
        phone,
        phoneClean,
        email,
        website,
        additionalInfo,
        legalReq,
        legalLink
      };
    });

    // Collect unique, sorted categories to build the filter pills using raw names
    const categoriesSet = new Set();
    processedVendors.forEach(item => {
      categoriesSet.add(item.category);
    });
    
    const uniqueCategories = Array.from(categoriesSet).sort();

    return {
      vendors: processedVendors,
      categories: uniqueCategories
    };
  } catch (error) {
    console.error("❌ Critical Error processing vendor payload metadata:", error);
    return { vendors: [], categories: [] };
  }
};