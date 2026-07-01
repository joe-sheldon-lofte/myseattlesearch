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
                        <li><a href="stats.html">Local & Market Insights</a></li>
                        <li><a href="news.html">Local & Market News</a></li>
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

        // Extract clean lowercase page identity context (e.g., 'sellers.html')
        let currentPageName = window.location.pathname.split('/').pop().toLowerCase().trim();
        if (!currentPageName || currentPageName === "") currentPageName = "index.html";

        try {
            const response = await fetch(disclaimersUrl);
            if (!response.ok) throw new Error('Data endpoint unreachable');
            const csvText = await response.text();

            // Native high-density cell splitter to safely manage quote blocks and inner commas
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

            // Run structural match queries across cells
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

            // Assemble sequentially below the commitment threshold link
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
                        <p style="margin: 0 0 1.25rem 0; font-size: 0.95rem; color: #222222; line-weight: 500; line-height: 1.6; flex-grow: 1;">${rev.fullText}</p>
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

customElements.define('universal-header', UniversalHeader);
customElements.define('universal-footer', UniversalFooter);
customElements.define('local-reviews', LocalReviews);