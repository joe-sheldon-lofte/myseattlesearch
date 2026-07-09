/* File: components.js */

class UniversalHeader extends HTMLElement {
    connectedCallback() {
        this.innerHTML = `
        <header class="main-header">
            <div class="nav-container">
                <a href="/index.html" class="nav-brand">Joe Sheldon</a>
                <button class="hamburger" id="hamburgerMenu" aria-label="Toggle Menu">
                    <span class="bar"></span>
                    <span class="bar"></span>
                    <span class="bar"></span>
                </button>
            </div>
            
            <nav class="fullscreen-menu" id="navMenu">
                <div class="menu-content-wrapper">
                    <ul class="menu-links">
                        <li><a href="/index.html">Home</a></li>
                        <li><a href="/stats.html">Market Insights</a></li>
                        <li><a href="/news/">Market News</a></li>
                        <li><a href="/searches.html">Curated Searches</a></li>
                        <li><a href="/sellers.html">Sell with Joe</a></li>
                        <li><a href="/movedna.html">MoveDNA Assessment</a></li>
                        <li><a href="/quizzes/index.html">Interactive Quizzes</a></li>
                        <li><a href="/calculators.html">Real Estate Calculators</a></li>
                        <li><a href="/events.html">Classes & Events</a></li>
                        <li><a href="/professionals.html">Preferred Professionals</a></li>
                    </ul>
                </div>
            </nav>
        </header>
        `;

        const hamburger = this.querySelector('#hamburgerMenu');
        const navMenu = this.querySelector('#navMenu');
        
        hamburger.addEventListener('click', () => {
            hamburger.classList.toggle('active');
            navMenu.classList.toggle('active');
        });
    }
}

class UniversalFooter extends HTMLElement {
    async connectedCallback() {
        this.innerHTML = `
        <footer>
            <div class="footer-content" style="max-width: 1000px; margin: 0 auto; width: 100%;">
                <img src="/assets/images/redfin.png" alt="Redfin Logo" class="footer-logo">
                <p class="office-address">3400 188th St SW, Ste 165<br>Lynnwood, WA 98037</p>
                <p style="margin-top: 1rem; font-size: 0.85rem; opacity: 0.7; display: flex; gap: 1.5rem; justify-content: center; flex-wrap: wrap;">
                    <a href="/hereforyou.html" style="color: var(--premier-beige); text-decoration: underline;">Housing Equity Commitment</a>
                    <a href="/calculators.html" style="color: var(--premier-beige); text-decoration: underline;">Real Estate Calculators</a>
                </p>
                
                <div id="dynamic-disclaimers-box" style="max-width: 750px; margin: 1.75rem auto 0 auto; padding-top: 1.25rem; border-top: 1px solid rgba(239, 236, 229, 0.15); font-size: 0.72rem; line-height: 1.5; text-align: justify; opacity: 0.5; color: var(--premier-beige); padding-left: 1rem; padding-right: 1rem; box-sizing: border-box;"></div>
            </div>
        </footer>
        `;

        const disclaimerBox = this.querySelector('#dynamic-disclaimers-box');
        const disclaimersUrl = 'https://docs.google.com/spreadsheets/d/e/2PACX-1vQyiu3qLYVO9khl6k5s_whzg_UZFzKu7-RHc5fa2tpe3aIlf4wm4IaqQeVd75enhpJvS_lxXgfQRfQ_/pub?gid=107250527&single=true&output=csv';

        let currentPageName = window.location.pathname.toLowerCase().trim();
        if (currentPageName === "/" || currentPageName === "") {
            currentPageName = "index.html";
        } else if (currentPageName.startsWith("/")) {
            currentPageName = currentPageName.substring(1);
        }

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
    }
}

class QuizEngine extends HTMLElement {
    constructor() {
        super();
        this.quizData = null;
        this.currentStep = -1;
        this.leadInfo = { firstName: '', lastName: '', email: '', phone: '' };
        this.answers = [];
    }

    async connectedCallback() {
        const quizIdAttr = this.getAttribute('quiz-id');
        if (!quizIdAttr) {
            this.innerHTML = `<div style="color:var(--card-accent-color); font-weight:bold; padding:1rem; text-align:center;">Engine Error: Attribute 'quiz-id' is required.</div>`;
            return;
        }
        
        this.innerHTML = `<div style="text-align:center; padding: 3rem; font-size:1.1rem; color:#666;">Hydrating dynamic strategy options...</div>`;
        
        try {
            const response = await fetch('/data/quizzes.json');
            const data = await response.json();
            this.quizData = data[quizIdAttr];
            
            if (!this.quizData) {
                this.innerHTML = `<div style="color:var(--card-accent-color); font-weight:bold; padding:1rem; text-align:center;">Engine Error: Quiz ID ${quizIdAttr} not found.</div>`;
                return;
            }

            if (!this.checkDateAvailability()) {
                this.innerHTML = `
                    <div class="profile-card quiz-container-card" style="max-width:600px; margin:2rem auto; padding:3rem 2.5rem; background:#fff; border-radius:12px; box-shadow:0 10px 30px rgba(0,0,0,0.08); text-align:center; border-top:6px solid #ccc;">
                        <div style="font-size:3rem; margin-bottom:1rem;">📅</div>
                        <h3 style="color:#333; margin:0 0 0.75rem 0;">Assessment Unavailable</h3>
                        <p style="color:#666; font-size:0.95rem; line-height:1.5; margin:0;">This strategy module is not available right now.</p>
                    </div>`;
                return;
            }

            this.renderOnboarding();
        } catch (err) {
            console.error("Quiz Initialization Interrupted:", err);
            this.innerHTML = `<div style="color:var(--card-accent-color); font-weight:bold; padding:1rem; text-align:center;">Failed to connect to template cache.</div>`;
        }
    }

    checkDateAvailability() {
        if (!this.quizData.startDate && !this.quizData.endDate) return true;
        const today = new Date();
        today.setHours(0,0,0,0);

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
        const reqStr = this.quizData.requiredFields || 'firstName,lastName,email';
        const reqFields = reqStr.split(',').map(f => f.trim().toLowerCase());
        
        const isFNReq = reqFields.includes('firstname') ? 'required' : '';
        const isLNReq = reqFields.includes('lastname') ? 'required' : '';
        const isEMReq = reqFields.includes('email') ? 'required' : '';
        const isPHReq = reqFields.includes('phone') ? 'required' : '';

        this.innerHTML = `
            <div class="profile-card quiz-container-card" style="max-width:600px; margin:2rem auto; padding:2.5rem; background:#fff; border-radius:12px; box-shadow:0 10px 30px rgba(0,0,0,0.08); border-top: 6px solid var(--card-accent-color);">
                <h2 style="text-align:center; color:var(--card-accent-color); margin-top:0; font-size:1.6rem; line-height:1.3;">${this.quizData.webTitle}</h2>
                <p style="text-align:center; color:#555; line-height:1.6; margin-bottom:2rem; font-size:0.98rem;">${this.quizData.introText}</p>
                
                <form id="quiz-lead-form" style="display:flex; flex-direction:column; gap:1.25rem;">
                    <div style="display:grid; grid-template-columns:1fr 1fr; gap:1rem;">
                        <div>
                            <label style="display:block; font-size:0.85rem; font-weight:700; margin-bottom:0.4rem; color:#333;">First Name ${isFNReq ? '*' : ''}</label>
                            <input type="text" id="quiz-firstName" ${isFNReq} style="width:100%; padding:0.75rem; border:1px solid #ccc; border-radius:6px; box-sizing:border-box; font-size:0.95rem;">
                        </div>
                        <div>
                            <label style="display:block; font-size:0.85rem; font-weight:700; margin-bottom:0.4rem; color:#333;">Last Name ${isLNReq ? '*' : ''}</label>
                            <input type="text" id="quiz-lastName" ${isLNReq} style="width:100%; padding:0.75rem; border:1px solid #ccc; border-radius:6px; box-sizing:border-box; font-size:0.95rem;">
                        </div>
                    </div>
                    <div>
                        <label style="display:block; font-size:0.85rem; font-weight:700; margin-bottom:0.4rem; color:#333;">Email Address ${isEMReq ? '*' : ''}</label>
                        <input type="email" id="quiz-email" ${isEMReq} style="width:100%; padding:0.75rem; border:1px solid #ccc; border-radius:6px; box-sizing:border-box; font-size:0.95rem;">
                    </div>
                    <div>
                        <label style="display:block; font-size:0.85rem; font-weight:700; margin-bottom:0.4rem; color:#333;">Phone Number ${isPHReq ? '*' : ''}</label>
                        <input type="tel" id="quiz-phone" ${isPHReq} style="width:100%; padding:0.75rem; border:1px solid #ccc; border-radius:6px; box-sizing:border-box; font-size:0.95rem;">
                    </div>
                    <button type="submit" class="btn btn-primary" style="margin-top:1rem; padding:0.9rem; font-size:1rem; font-weight:bold; letter-spacing:0.5px;">Start the Quiz</button>
                </form>
            </div>
        `;

        this.querySelector('#quiz-lead-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            this.leadInfo = {
                firstName: this.querySelector('#quiz-firstName').value.trim(),
                lastName: this.querySelector('#quiz-lastName').value.trim(),
                email: this.querySelector('#quiz-email').value.trim(),
                phone: this.querySelector('#quiz-phone').value.trim()
            };
            
            this.currentStep = 0;
            this.innerHTML = `<div style="text-align:center; padding:4rem; color:#666;">Initializing quiz engine module...</div>`;
            
            try {
                const modulePath = `/quizzes/engines/${this.quizData.scoringType}.js`;
                const engineModule = await import(modulePath);
                engineModule.initializeQuizTrack(this);
            } catch (err) {
                console.error("Critical: Failed to resolve scoring module file:", err);
                this.innerHTML = `<div style="color:var(--card-accent-color); font-weight:bold; padding:2rem; text-align:center;">Engine Error: Could not launch script logic file '/quizzes/engines/${this.quizData.scoringType}.js'.</div>`;
            }
        });
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
            const response = await fetch('/data/Stats_Reviews%20-%20Reviews.csv');
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
                    <div class="review-component-card" style="background: #ffffff; padding: 1.75rem; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.05); display: flex; flex-direction: column; border-top: 5px solid var(--card-accent-color);">
                        <div style="color: var(--card-accent-color); font-size: 1rem; font-weight: 800; margin-bottom: 0.75rem; letter-spacing: 0.5px;">5.0 <span style="font-size: 1.1rem; letter-spacing: 1px;">${stars}</span></div>
                        ${snippetMarkup}
                        <p style="margin: 0 0 1.25rem 0; font-size: 0.95rem; color: #222222; font-weight: 500; line-height: 1.6;">${rev.fullText}</p>
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

// Global Core Custom Elements Registries
customElements.define('universal-header', UniversalHeader);
customElements.define('universal-footer', UniversalFooter);
customElements.define('quiz-engine', QuizEngine);
customElements.define('local-reviews', LocalReviews);