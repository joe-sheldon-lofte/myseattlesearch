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
                        <li><a href="/news.html">Market News</a></li>
                        <li><a href="/searches.html">Curated Searches</a></li>
                        <li><a href="/sellers.html">Sell with Joe</a></li>
                        <li><a href="/movedna.html">MoveDNA Assessment</a></li>
                        <li><a href="/quizzes/index.html">Interactive Quizzes</a></li>
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
    connectedCallback() {
        this.innerHTML = `
        <footer>
            <div class="footer-content" style="max-width: 1000px; margin: 0 auto; width: 100%;">
                <img src="/assets/images/redfin.png" alt="Redfin Logo" class="footer-logo">
                <p class="office-address">3400 188th St SW, Ste 165<br>Lynnwood, WA 98037</p>
                <p style="margin-top: 1rem; font-size: 0.85rem; opacity: 0.7; display: flex; gap: 1.5rem; justify-content: center; flex-wrap: wrap;">
                    <a href="/hereforyou.html" style="color: var(--premier-beige); text-decoration: underline;">Housing Equity Commitment</a>
                    <a href="/calculators.html" style="color: var(--premier-beige); text-decoration: underline; font-weight: bold;">Real Estate Calculators</a>
                </p>
            </div>
        </footer>
        `;
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
            this.innerHTML = `<div style="color:var(--redfin-red); font-weight:bold; padding:1rem; text-align:center;">Engine Error: Attribute 'quiz-id' is required.</div>`;
            return;
        }
        
        this.innerHTML = `<div style="text-align:center; padding: 3rem; font-size:1.1rem; color:#666;">Hydrating dynamic strategy options...</div>`;
        
        try {
            const response = await fetch('/data/quizzes.json');
            const data = await response.json();
            this.quizData = data[quizIdAttr];
            
            if (!this.quizData) {
                this.innerHTML = `<div style="color:var(--redfin-red); font-weight:bold; padding:1rem; text-align:center;">Engine Error: Quiz ID ${quizIdAttr} not found.</div>`;
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
            this.innerHTML = `<div style="color:var(--redfin-red); font-weight:bold; padding:1rem; text-align:center;">Failed to connect to template cache.</div>`;
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
            <div class="profile-card quiz-container-card" style="max-width:600px; margin:2rem auto; padding:2.5rem; background:#fff; border-radius:12px; box-shadow:0 10px 30px rgba(0,0,0,0.08); border-top: 6px solid var(--redfin-red);">
                <h2 style="text-align:center; color:var(--redfin-red); margin-top:0; font-size:1.6rem; line-height:1.3;">${this.quizData.webTitle}</h2>
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
            
            // 🌟 LAZY-LOAD EXECUTION INTERACTION LAYER BASED ON SCORING TYPE COLUMN VALUE
            try {
                const modulePath = `/quizzes/engines/${this.quizData.scoringType}.js`;
                const engineModule = await import(modulePath);
                
                // Hand operational execution over to the specialized code module script file
                engineModule.initializeQuizTrack(this);
            } catch (err) {
                console.error("Critical: Failed to resolve scoring module file:", err);
                this.innerHTML = `<div style="color:var(--redfin-red); font-weight:bold; padding:2rem; text-align:center;">Engine Error: Could not launch script logic file '/quizzes/engines/${this.quizData.scoringType}.js'.</div>`;
            }
        });
    }
}

customElements.define('universal-header', UniversalHeader);
customElements.define('universal-footer', UniversalFooter);
customElements.define('quiz-engine', QuizEngine);