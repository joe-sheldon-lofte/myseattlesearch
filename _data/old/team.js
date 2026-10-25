/* File: _data/team.js */
const fs = require('fs');
const path = require('path');

module.exports = function() {
  const teamFilePath = path.join(__dirname, '../data/team.json');
  let rosterArray = [];

  if (fs.existsSync(teamFilePath)) {
    try {
      rosterArray = JSON.parse(fs.readFileSync(teamFilePath, 'utf-8'));
    } catch (error) {
      console.error("❌ Data Engine Error: Failed to parse team.json payload:", error);
    }
  }

  // Resilient multi-title string matching handles expanded structural roles seamlessly
  const seniorAgent = rosterArray.find(m => m.position && m.position.includes('Senior Agent')) || null;
  const loanOfficer = rosterArray.find(m => m.position && m.position.includes('Executive Loan Officer')) || null;
  const transactionCoordinator = rosterArray.find(m => m.position === 'Transaction Coordinator') || null;
  const listingCoordinator = rosterArray.find(m => m.position === 'Listing Coordinator') || null;
  
  const coverageColleagues = rosterArray.filter(m => m.position && m.position.includes('Coverage Colleague'));
  const salesManager = rosterArray.find(m => m.position === 'Sales Manager') || null;
  const associateAgents = rosterArray.filter(m => m.position === 'Associate Agent');
  
  const eligiblePages = rosterArray.filter(m => m.teamPage === true);

  return {
    allMembers: rosterArray,
    eligiblePages,
    seniorAgent,
    loanOfficer,
    transactionCoordinator,
    listingCoordinator,
    coverageColleagues,
    salesManager,
    associateAgents
  };
};