/* File: components.js */

class UniversalHeader extends HTMLElement {
    connectedCallback() {
        this.innerHTML = `
        <header class="main-header">
            <div class="nav-container">
                <a href="index.html" class="nav-brand">Joe Sheldon</a>
                <button class="hamburger" id="hamburgerMenu" aria-label="Toggle Menu">
                    <span class="bar"></span>
                    <span class="bar"></span>
                    <span class="bar"></span>
                </button>
            </div>
            
            <nav class="fullscreen-menu" id="navMenu">
                <div class="menu-content-wrapper">
                    <ul class="menu-links">
                        <li><a href="index.html">Home</a></li>
                        <li><a href="stats.html">Market Insights</a></li>
                        <li><a href="news.html">Market News</a></li>
                        <li><a href="searches.html">Curated Searches</a></li>
                        <li><a href="sellers.html">Sell with Joe</a></li>
                        <li><a href="movedna.html">MoveDNA Assessment</a></li>
                        <li><a href="events.html">Classes & Events</a></li>
                        <li><a href="professionals.html">Preferred Professionals</a></li>
                    </ul>
                    
                    <div class="menu-socials">
                        <a href="https://www.instagram.com/seattlesagent" target="_blank" aria-label="Instagram">
                            <svg class="social-icon" viewBox="0 0 24 24" fill="currentColor">
                                <path d="M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zM12 0C8.741 0 8.333.014 7.053.072 2.695.272.273 2.69.073 7.052.014 8.333 0 8.741 0 12c0 3.259.014 3.668.072 4.948.2 4.358 2.618 6.78 6.98 6.98C8.333 23.986 8.741 24 12 24c3.259 0 3.668-.014 4.948-.072 4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98C15.668.014 15.259 0 12 0zm0 5.838a6.162 6.162 0 100 12.324 6.162 6.162 0 000-12.324zM12 16a4 4 0 110-8 4 4 0 010 8zm6.406-11.845a1.44 1.44 0 100 2.881 1.44 1.44 0 000-2.881z"/>
                            </svg>
                        </a>
                        <a href="https://www.tiktok.com/@seattlespremieragent" target="_blank" aria-label="TikTok">
                            <svg class="social-icon" viewBox="0 0 24 24" fill="currentColor">
                                <path d="M19.59 6.69a4.83 4.83 0 01-3.77-4.25V2h-3.45v13.67a2.89 2.89 0 01-5.2 1.74 2.89 2.89 0 012.31-4.64 2.93 2.93 0 01.88.13V9.4a6.84 6.84 0 00-1-.05A6.33 6.33 0 005 20.1a6.34 6.34 0 0010.86-4.43v-7a8.16 8.16 0 004.77 1.52v-3.4a4.85 4.85 0 01-1.04-.1z"/>
                            </svg>
                        </a>
                    </div>
                </div>
            </nav>
        </header>
        `;

        const hamburger = this.querySelector('#hamburgerMenu');
        const navMenu = this.querySelector('#navMenu');
        const body = document.body;

        hamburger.addEventListener('click', () => {
            hamburger.classList.toggle('active');
            navMenu.classList.toggle('active');
            if(navMenu.classList.contains('active')) {
                body.style.overflow = 'hidden';
            } else {
                body.style.overflow = 'auto';
            }
        });
    }
}

class UniversalFooter extends HTMLElement {
    async connectedCallback() {
        this.innerHTML = `
        <footer>
            <div class="footer-content" style="max-width: 1000px; margin: 0 auto; width: 100%;">
                <img src="assets/images/redfin.png" alt="Redfin Logo" class="footer-logo">
                <p class="office-address">3400 188th St SW, Ste 165<br>Lynnwood, WA 98037</p>
                <p style="margin-top: 1rem; font-size: 0.8rem; opacity: 0.6;"><a href="hereforyou.html" style="color: var(--premier-beige); text-decoration: underline;">My Commitment to Housing Equity & Resources</a></p>
                
                <div id="dynamic-disclaimers-box" style="max-width: 750px; margin: 1.75rem auto 0 auto; padding-top: 1.25rem; border-top: 1px solid rgba(239, 236, 229, 0.15); font-size: 0.72rem; line-height: 1.5; text-align: justify; opacity: 0.5; color: var(--premier-beige); padding-left: 1rem; padding-right: 1rem; box-sizing: border-box;"></div>
            </div>
        </footer>
        `;

        const disclaimerBox = this.querySelector('#dynamic-disclaimers-box');
        const disclaimersUrl = 'https://docs.google.com/spreadsheets/d/e/2PACX-1vQyiu3qLYVO9khl6k5s_whzg_UZFzKu7-RHc5fa2tpe3aIlf4wm4IaqQeVd75enhpJvS_lxXgfQRfQ_/pub?gid=107250527&single=true&output=csv';

        let currentPageName = window.location.pathname.split('/').pop().toLowerCase().trim();
        if (!currentPageName || currentPageName === "") currentPageName = "index.html";

        try {
            const response = await fetch(disclaimersUrl);
            if (!response.ok) throw new Error('Data endpoint unreachable');
            const csvText = await response.text();

            const parseCSVRows = (text) => {
                const lines = [];
                let row = [""];
                let inQuotes = false;

                for (let i = 0; i < text.length; i++) {
                    let char = text[i];
                    let nextChar = text[i+1];
                    if (char === '"') {
                        if (inQuotes && nextChar === '"') { row[row.length - 1] += '"'; i++; }
                        else { inQuotes = !inQuotes; }
                    } else if (char === ',' && !inQuotes) {
                        row.push('');
                    } else if ((char === '\r' || char === '\n') && !inQuotes) {
                        if (char === '\r' && nextChar === '\n') { i++; }
                        lines.push(row);
                        row = [''];
                    } else {
                        row[row.length - 1] += char;
                    }
                }
                if (row.length > 1 || row[0] !== '') lines.push(row);
                return lines;
            };

            const allRows = parseCSVRows(csvText);
            if (allRows.length < 2) { disclaimerBox.style.display = 'none'; return; }

            let siteWideText = '';
            let pageSpecificText = '';

            for (let i = 1; i < allRows.length; i++) {
                const row = allRows[i];
                if (!row || row.length < 2) continue;

                const targetKey = row[0].trim().toLowerCase();
                const textValue = row[1].trim();

                if (targetKey === 'site') {
                    siteWideText = textValue;
                } else if (targetKey === currentPageName) {
                    pageSpecificText = textValue;
                }
            }

            let outputMarkup = '';
            if (siteWideText) {
                outputMarkup += `<p style="margin: 0 0 0.75rem 0; text-align: justify;">${siteWideText}</p>`;
            }
            if (pageSpecificText) {
                outputMarkup += `<p style="margin: 0; text-align: justify;">${pageSpecificText}</p>`;
            }

            if (outputMarkup) {
                disclaimerBox.innerHTML = outputMarkup;
            } else {
                disclaimerBox.style.display = 'none';
            }

        } catch (error) {
            console.error("Regulatory disclosure generation error:", error);
            disclaimerBox.style.display = 'none';
        }

        if (!document.getElementById('cloudflare-analytics-beacon')) {
            const cfScript = document.createElement('script');
            cfScript.id = 'cloudflare-analytics-beacon';
            cfScript.defer = true;
            cfScript.src = 'https://static.cloudflareinsights.com/beacon.min.js';
            cfScript.setAttribute('data-cf-beacon', '{"token": "792b225c84044723a9fbe4e808359d11"}');
            document.head.appendChild(cfScript);
        }
    }
}

class LocalReviews extends HTMLElement {
    async connectedCallback() {
        const limit = parseInt(this.getAttribute('limit')) || 3;
        
        let pageName = window.location.pathname.split('/').pop().toLowerCase().trim();
        if (!pageName || pageName === "") pageName = "index.html";

        this.innerHTML = `<div class="reviews-component-grid" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 1.5rem; width: 100%; margin: 2rem 0;">Loading reviews...</div>`;
        const gridContainer = this.querySelector('.reviews-component-grid');

        try {
            const response = await fetch('./data/Stats_Reviews%20-%20Reviews.csv');
            if (!response.ok) throw new Error('Network file retrieval failed');
            const csvText = await response.text();

            const parseCSVRows = (text) => {
                const lines = [];
                let row = [""];
                let inQuotes = false;

                for (let i = 0; i < text.length; i++) {
                    let char = text[i];
                    let nextChar = text[i+1];
                    if (char === '"') {
                        if (inQuotes && nextChar === '"') { row[row.length - 1] += '"'; i++; }
                        else { inQuotes = !inQuotes; }
                    } else if (char === ',' && !inQuotes) {
                        row.push('');
                    } else if ((char === '\r' || char === '\n') && !inQuotes) {
                        if (char === '\r' && nextChar === '\n') { i++; }
                        lines.push(row);
                        row = [''];
                    } else {
                        row[row.length - 1] += char;
                    }
                }
                if (row.length > 1 || row[0] !== '') lines.push(row);
                return lines;
            };

            const allRows = parseCSVRows(csvText);
            if (allRows.length < 2) { gridContainer.innerHTML = ''; return; }

            const headers = allRows[0].map(h => h.trim().toLowerCase());
            const targetPageIndex = headers.indexOf(pageName);

            if (targetPageIndex === -1) { gridContainer.innerHTML = ''; return; }

            const indexReviewer = headers.indexOf('reviewer');
            const indexRating = headers.indexOf('star rating');
            const indexSnippet = headers.indexOf('snippet');
            const indexFull = headers.indexOf('full review');

            const validReviews = [];
            for (let i = 1; i < allRows.length; i++) {
                const currentRow = allRows[i];
                if (!currentRow[targetPageIndex]) continue;
                
                const pageMarker = currentRow[targetPageIndex].trim().toLowerCase();
                if (pageMarker === 'x') {
                    validReviews.push({
                        reviewer: currentRow[indexReviewer] || 'Verified Client',
                        rating: parseInt(currentRow[indexRating]) || 5,
                        snippet: currentRow[indexSnippet] ? currentRow[indexSnippet].trim() : '',
                        fullText: currentRow[indexFull] || ''
                    });
                }
            }

            if (validReviews.length === 0) { gridContainer.innerHTML = ''; return; }

            for (let i = validReviews.length - 1; i > 0; i--) {
                const j = Math.floor(Math.random() * (i + 1));
                [validReviews[i], validReviews[j]] = [validReviews[j], validReviews[i]];
            }

            const selectedReviews = validReviews.slice(0, limit);

            gridContainer.innerHTML = selectedReviews.map(rev => {
                const stars = '★'.repeat(rev.rating) + '☆'.repeat(5 - rev.rating);
                const snippetMarkup = rev.snippet && rev.snippet !== "" 
                    ? `<h4 style="margin: 0 0 0.75rem 0; font-size: 1.05rem; font-style: italic; color: #222222; line-height: 1.4;">"${rev.snippet}"</h4>`
                    : '';

                return `
                    <div class="review-component-card" style="background: #ffffff; padding: 1.75rem; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.05); display: flex; flex-direction: column; border-top: 5px solid #C13030;">
                        <div style="color: #C13030; font-size: 1rem; font-weight: 800; margin-bottom: 0.75rem; letter-spacing: 0.5px;">5.0 <span style="font-size: 1.1rem; letter-spacing: 1px;">${stars}</span></div>
                        ${snippetMarkup}
                        <p style="margin: 0 0 1.25rem 0; font-size: 0.95rem; color: #222222; line-weight: 500; line-height: 1.6;">${rev.fullText}</p>
                        <div style="font-size: 0.8rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; color: #222222; opacity: 0.7;">— ${rev.reviewer}</div>
                    </div>
                `;
            }).join('');

        } catch (error) {
            console.error('Contextual reviews execution error:', error);
            gridContainer.innerHTML = '';
        }
    }
}

/**
 * polymorphic, Scalable Native Quiz Evaluation Web Component
 * Syntax call: <quiz-engine quiz-id="1"></quiz-engine>
 */
/* File: components.js (QuizEngine Section Update) */

class QuizEngine extends HTMLElement {
    constructor() {
        super();
        this.quizData = null;
        this.questions = [];
        this.routing = [];
        this.currentStep = -1;
        this.leadInfo = { firstName: '', lastName: '', email: '', phone: '' };
        this.answers = [];
        this.scores = { typeA: 0, typeB: 0, typeC: 0, typeD: 0, typeE: 0, typeF: 0 };
        this.totalTallyScore = 0;
    }

    async connectedCallback() {
        const quizIdAttr = this.getAttribute('quiz-id');
        if (!quizIdAttr) {
            this.innerHTML = `<div style="color:red; font-weight:bold; padding:1rem; text-align:center;">Engine Error: Attribute 'quiz-id' is required.</div>`;
            return;
        }
        
        this.innerHTML = `<div style="text-align:center; padding:3rem; font-size:1.1rem; color:#666;">Hydrating dynamic strategy options...</div>`;
        
        try {
            // Read from the clean local fast JSON compilation cache
            const response = await fetch('./data/quizzes.json');
            const data = await response.json();
            this.quizData = data[quizIdAttr];
            
            if (!this.quizData) {
                this.innerHTML = `<div style="color:red; font-weight:bold; padding:1rem; text-align:center;">Engine Error: Quiz ID ${quizIdAttr} not found in localized database.</div>`;
                return;
            }

            this.questions = this.quizData.questions || [];
            this.routing = this.quizData.routing || [];

            // 📅 EXECUTE SCHEDULING CALENDAR DATE GATE ROUTINES
            if (!this.checkDateAvailability()) {
                this.innerHTML = `
                    <div class="profile-card quiz-container-card" style="max-width:600px; margin:2rem auto; padding:3rem 2.5rem; background:#fff; border-radius:12px; box-shadow:0 10px 30px rgba(0,0,0,0.08); text-align:center; border-top:6px solid #ccc;">
                        <div style="font-size:3rem; margin-bottom:1rem;">📅</div>
                        <h3 style="color:#333; margin:0 0 0.75rem 0;">Assessment Unavailable</h3>
                        <p style="color:#666; font-size:0.95rem; line-height:1.5; margin:0;">This quiz strategy module is not available at this time. Please check back later or join our upcoming buyer/seller classes.</p>
                    </div>`;
                return;
            }

            this.renderOnboarding();
        } catch (err) {
            console.error("Quiz Engine Initialization Interrupted:", err);
            this.innerHTML = `<div style="color:red; font-weight:bold; padding:1rem; text-align:center;">Failed to compile quiz metadata pipeline.</div>`;
        }
    }

    checkDateAvailability() {
        if (!this.quizData.startDate && !this.quizData.endDate) return true; // Empty fields mean no restrictions
        
        const today = new Date();
        today.setHours(0,0,0,0); // Zero out hours to match row dates perfectly

        if (this.quizData.startDate) {
            const start = new Date(this.quizData.startDate + "T00:00:00");
            if (today < start) return false;
        }

        if (this.quizData.endDate) {
            const end = new Date(this.quizData.endDate + "T00:00:00");
            if (today > end) return false;
        }

        return true;
    }

    renderOnboarding() {
        this.innerHTML = `
            <div class="profile-card quiz-container-card" style="max-width:600px; margin:2rem auto; padding:2.5rem; background:#fff; border-radius:12px; box-shadow:0 10px 30px rgba(0,0,0,0.08); border-top: 6px solid #A6192E;">
                <h2 style="text-align:center; color:#A6192E; margin-top:0; font-size:1.6rem; line-height:1.3;">${this.quizData.webTitle}</h2>
                <p style="text-align:center; color:#555; line-height:1.6; margin-bottom:2rem; font-size:0.98rem;">${this.quizData.introText}</p>
                
                <form id="quiz-lead-form" style="display:flex; flex-direction:column; gap:1.25rem;">
                    <div style="display:grid; grid-template-columns:1fr 1fr; gap:1rem;">
                        <div>
                            <label style="display:block; font-size:0.85rem; font-weight:700; margin-bottom:0.4rem; color:#333;">First Name *</label>
                            <input type="text" id="quiz-firstName" required style="width:100%; padding:0.75rem; border:1px solid #ccc; border-radius:6px; box-sizing:border-box; font-size:0.95rem;">
                        </div>
                        <div>
                            <label style="display:block; font-size:0.85rem; font-weight:700; margin-bottom:0.4rem; color:#333;">Last Name *</label>
                            <input type="text" id="quiz-lastName" required style="width:100%; padding:0.75rem; border:1px solid #ccc; border-radius:6px; box-sizing:border-box; font-size:0.95rem;">
                        </div>
                    </div>
                    <div>
                        <label style="display:block; font-size:0.85rem; font-weight:700; margin-bottom:0.4rem; color:#333;">Email Address *</label>
                        <input type="email" id="quiz-email" required style="width:100%; padding:0.75rem; border:1px solid #ccc; border-radius:6px; box-sizing:border-box; font-size:0.95rem;">
                    </div>
                    <div>
                        <label style="display:block; font-size:0.85rem; font-weight:700; margin-bottom:0.4rem; color:#333;">Phone Number *</label>
                        <input type="tel" id="quiz-phone" required style="width:100%; padding:0.75rem; border:1px solid #ccc; border-radius:6px; box-sizing:border-box; font-size:0.95rem;">
                    </div>
                    <button type="submit" class="btn btn-primary" style="margin-top:1rem; padding:0.9rem; font-size:1rem; font-weight:bold; letter-spacing:0.5px;">Begin Strategy Blueprint</button>
                </form>
            </div>
        `;

        this.querySelector('#quiz-lead-form').addEventListener('submit', (e) => {
            e.preventDefault();
            this.leadInfo.firstName = this.querySelector('#quiz-firstName').value.trim();
            this.leadInfo.lastName = this.querySelector('#quiz-lastName').value.trim();
            this.leadInfo.email = this.querySelector('#quiz-email').value.trim();
            this.leadInfo.phone = this.querySelector('#quiz-phone').value.trim();
            
            this.currentStep = 0;
            this.renderQuestion();
        });
    }

    renderQuestion() {
        if (this.currentStep >= this.questions.length) {
            this.processCalculationsAndSubmit();
            return;
        }

        const rawQuestion = this.questions[this.currentStep];
        const parts = rawQuestion.split('||');
        const questionText = parts[0].trim();
        const progressPercentage = Math.round(((this.currentStep) / this.questions.length) * 100);

        let interfaceHTML = '';

        if (this.quizData.scoringType === 'matrix_4quadrant') {
            interfaceHTML = `
                <p style="font-size:0.9rem; color:#888; text-align:center; font-weight:bold; margin-bottom:0.5rem;">Rate your level of agreement:</p>
                <div style="display:grid; grid-template-columns: repeat(10, 1fr); gap:6px; margin:2rem 0 1rem 0;">
                    ${Array.from({length: 10}, (_, i) => i + 1).map(num => `
                        <button type="button" class="matrix-choice-btn" data-val="${num}" style="padding: 0.8rem 0; border:1px solid #ddd; background:#fff; font-weight:bold; border-radius:6px; cursor:pointer; transition:all 0.2s ease; font-size:0.95rem;">${num}</button>
                    `).join('')}
                </div>
                <div style="display:flex; justify-content:space-between; font-size:0.78rem; font-weight:700; color:#666; padding:0 4px; margin-bottom:2rem;">
                    <span>1 - Strongly Disagree</span>
                    <span>10 - Strongly Agree</span>
                </div>
            `;
        } else {
            const choices = parts[1].split('|').map(c => c.trim());
            interfaceHTML = `
                <div style="display:flex; flex-direction:column; gap:0.9rem; margin:2rem 0;">
                    ${choices.map((choice) => {
                        const pointsMatch = choice.match(/\[(\d+)\]/);
                        const pointsValue = pointsMatch ? parseInt(pointsMatch[1]) : 0;
                        const clearText = choice.replace(/\[\d+\]/, '').trim();
                        return `
                            <button type="button" class="tally-choice-btn" data-points="${pointsValue}" data-text="${clearText}" style="text-align:left; padding:1rem; border:1px solid #ddd; background:#fff; border-radius:8px; cursor:pointer; transition:all 0.2s ease; font-size:0.98rem; line-height:1.4; font-weight:500;">${clearText}</button>
                        `;
                    }).join('')}
                </div>
            `;
        }

        this.innerHTML = `
            <div class="profile-card quiz-container-card" style="max-width:600px; margin:2rem auto; padding:2.5rem; background:#fff; border-radius:12px; box-shadow:0 10px 30px rgba(0,0,0,0.08); min-height:350px; display:flex; flex-direction:column; justify-content:space-between; box-sizing:border-box;">
                <div>
                    <div style="width:100%; background:#eee; height:6px; border-radius:3px; margin-bottom:2rem; overflow:hidden;">
                        <div style="width:${progressPercentage}%; background:#A6192E; height:100%; transition:width 0.3s ease;"></div>
                    </div>
                    <div style="font-size:0.8rem; font-weight:800; color:#A6192E; text-transform:uppercase; letter-spacing:1px; margin-bottom:0.5rem; text-align:center;">Statement ${this.currentStep + 1} of ${this.questions.length}</div>
                    <h3 style="text-align:center; font-size:1.22rem; font-weight:600; line-height:1.5; color:#222; margin:0 0 1.5rem 0; padding:0 10px;">"${questionText}"</h3>
                </div>
                <div>${interfaceHTML}</div>
            </div>
        `;

        this.querySelectorAll('.matrix-choice-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const numericValue = parseInt(btn.getAttribute('data-val'));
                const traitBucket = parts[1] ? parts[1].trim() : 'typeA';
                
                this.answers.push(numericValue);
                if (this.scores[traitBucket] !== undefined) this.scores[traitBucket] += numericValue;
                
                this.currentStep++;
                this.renderQuestion();
            });
        });

        this.querySelectorAll('.tally-choice-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const points = parseInt(btn.getAttribute('data-points'));
                const chosenText = btn.getAttribute('data-text');
                
                this.answers.push(chosenText + " [" + points + "]");
                this.totalTallyScore += points;
                
                this.currentStep++;
                this.renderQuestion();
            });
        });
    }

    async processCalculationsAndSubmit() {
        this.innerHTML = `
            <div class="profile-card quiz-container-card" style="max-width:600px; margin:2rem auto; padding:4rem 2.5rem; background:#fff; border-radius:12px; box-shadow:0 10px 30px rgba(0,0,0,0.08); text-align:center;">
                <div class="spinner" style="border: 4px solid rgba(166,25,46,0.1); border-left-color: #A6192E; border-radius: 50%; width: 40px; height: 40px; animation: spin 1s linear infinite; margin: 0 auto 1.5rem auto;"></div>
                <h3 style="color:#222; margin:0 0 0.5rem 0;">Analyzing Metrics...</h3>
                <p style="color:#666; font-size:0.95rem; margin:0;">Securing your strategic blueprint vault access token.</p>
                <style>@keyframes spin { to { transform: rotate(360deg); } }</style>
            </div>
        `;

        let outcomeKey = '';
        let finalOutcome = '';
        let dynamicRedirectDestinationUrl = '';

        if (this.quizData.scoringType === 'matrix_4quadrant') {
            let highestVal = -1;
            for (const [bucket, value] of Object.entries(this.scores)) {
                if (value > highestVal) {
                    highestVal = value;
                    outcomeKey = bucket;
                }
            }
            
            for (const rStr of this.routing) {
                if (rStr.includes('||')) {
                    const rParts = rStr.split('||');
                    if (rParts[0].trim() === outcomeKey) {
                        dynamicRedirectDestinationUrl = rParts[1].trim(); // Grabs whatever full URL structure you wrote!
                        
                        // Extract a pretty outcome name string for tracking databases
                        let baselineExtract = dynamicRedirectDestinationUrl.split('/').pop().replace('.html', '');
                        if (baselineExtract.includes('#')) baselineExtract = baselineExtract.split('#')[1];
                        finalOutcome = baselineExtract.split('-').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
                        break;
                    }
                }
            }
        } else {
            for (const rStr of this.routing) {
                if (rStr.includes('||')) {
                    const rParts = rStr.split('||');
                    const rangeParts = rParts[0].trim().split('-');
                    const min = parseInt(rangeParts[0]);
                    const max = parseInt(rangeParts[1]);
                    
                    if (this.totalTallyScore >= min && this.totalTallyScore <= max) {
                        dynamicRedirectDestinationUrl = rParts[1].trim();
                        outcomeKey = rParts[0].trim();
                        
                        let baselineExtract = dynamicRedirectDestinationUrl.split('/').pop().replace('.html', '');
                        if (baselineExtract.includes('#')) baselineExtract = baselineExtract.split('#')[1];
                        finalOutcome = baselineExtract.split('-').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
                        break;
                    }
                }
            }
        }

        const submissionPayload = {
            quizId: this.quizData.id,
            firstName: this.leadInfo.firstName,
            lastName: this.leadInfo.lastName,
            email: this.leadInfo.email,
            phone: this.leadInfo.phone,
            outcomeKey: outcomeKey,
            finalOutcome: finalOutcome,
            totalTallyScore: this.totalTallyScore,
            scores: this.scores,
            answers: this.answers
        };

        try {
            fetch(this.quizData.webhookUrl, {
                method: 'POST',
                mode: 'no-cors',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(submissionPayload)
            });
        } catch (postErr) {
            print("Payload buffer dispatch exception logs:", postErr);
        }

        // Forward the client's name out via parameter strings to authorize dynamic layout greetings
        const parameterGlue = dynamicRedirectDestinationUrl.includes('?') ? '&' : '?';
        const finalTargetLink = dynamicRedirectDestinationUrl + parameterGlue + "name=" + encodeURIComponent(this.leadInfo.firstName);

        setTimeout(() => {
            window.location.href = finalTargetLink;
        }, 600);
    }
}

customElements.define('universal-header', UniversalHeader);
customElements.define('universal-footer', UniversalFooter);
customElements.define('local-reviews', LocalReviews);
customElements.define('quiz-engine', QuizEngine);