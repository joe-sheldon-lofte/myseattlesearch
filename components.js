// Global Hamburger Menu Controller for Statically Included Header (header.njk)
document.addEventListener("DOMContentLoaded", function() {
    const hamburger = document.querySelector('#hamburgerMenu');
    const navMenu = document.querySelector('#navMenu');
    if (hamburger && navMenu) {
        hamburger.addEventListener('click', () => {
            hamburger.classList.toggle('active');
            navMenu.classList.toggle('active');
        });
    }
});

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
            this.innerHTML = `<div style="color: var(--card-accent-color); font-weight:bold; padding:1rem; text-align:center;">Engine Error: Attribute 'quiz-id' is required.</div>`;
            return;
        }
        
        this.innerHTML = `<div style="text-align:center; padding: 3rem; font-size:1.1rem; color: var(--premier-charcoal); opacity: 0.8;">Hydrating dynamic strategy options...</div>`;
        
        try {
            const response = await fetch('/data/quizzes.json');
            const data = await response.json();
            this.quizData = data[quizIdAttr];
            
            if (!this.quizData) {
                this.innerHTML = `<div style="color: var(--card-accent-color); font-weight:bold; padding:1rem; text-align:center;">Engine Error: Quiz ID ${quizIdAttr} not found.</div>`;
                return;
            }

            if (!this.checkDateAvailability()) {
                this.innerHTML = `
                    <div class="profile-card quiz-container-card" style="max-width:600px; margin:2rem auto; padding:3rem 2.5rem; background: white; border-radius:12px; box-shadow:0 10px 30px rgba(0,0,0,0.08); text-align:center; border-top:6px solid var(--premier-beige);">
                        <div style="font-size:3rem; margin-bottom:1rem;">📅</div>
                        <h3 style="color: var(--premier-charcoal); margin:0 0 0.75rem 0;">Assessment Unavailable</h3>
                        <p style="color: var(--premier-charcoal); opacity: 0.8; font-size:0.95rem; line-height:1.5; margin:0;">This strategy module is not available right now.</p>
                    </div>`;
                return;
            }

            this.renderOnboarding();
        } catch (err) {
            console.error("Quiz Initialization Interrupted:", err);
            this.innerHTML = `<div style="color: var(--card-accent-color); font-weight:bold; padding:1rem; text-align:center;">Failed to connect to template cache.</div>`;
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
            <div class="profile-card quiz-container-card" style="max-width:600px; margin:2rem auto; padding:2.5rem; background: white; border-radius:12px; box-shadow:0 10px 30px rgba(0,0,0,0.08); border-top: 6px solid var(--card-accent-color);">
                <h2 style="text-align:center; color: var(--card-accent-color); margin-top:0; font-size:1.6rem; line-height:1.3;">${this.quizData.webTitle}</h2>
                <p style="text-align:center; color: var(--premier-charcoal); opacity: 0.8; line-height:1.6; margin-bottom:2rem; font-size:0.98rem;">${this.quizData.introText}</p>
                
                <form id="quiz-lead-form" style="display:flex; flex-direction:column; gap:1.25rem;">
                    <div style="display:grid; grid-template-columns:1fr 1fr; gap:1rem;">
                        <div>
                            <label style="display:block; font-size:0.85rem; font-weight:700; margin-bottom:0.4rem; color: var(--premier-charcoal);">First Name ${isFNReq ? '*' : ''}</label>
                            <input type="text" id="quiz-firstName" ${isFNReq} style="width:100%; padding:0.75rem; border:1px solid var(--premier-beige); border-radius:6px; box-sizing:border-box; font-size:0.95rem;">
                        </div>
                        <div>
                            <label style="display:block; font-size:0.85rem; font-weight:700; margin-bottom:0.4rem; color: var(--premier-charcoal);">Last Name ${isLNReq ? '*' : ''}</label>
                            <input type="text" id="quiz-lastName" ${isLNReq} style="width:100%; padding:0.75rem; border:1px solid var(--premier-beige); border-radius:6px; box-sizing:border-box; font-size:0.95rem;">
                        </div>
                    </div>
                    <div>
                        <label style="display:block; font-size:0.85rem; font-weight:700; margin-bottom:0.4rem; color: var(--premier-charcoal);">Email Address ${isEMReq ? '*' : ''}</label>
                        <input type="email" id="quiz-email" ${isEMReq} style="width:100%; padding:0.75rem; border:1px solid var(--premier-beige); border-radius:6px; box-sizing:border-box; font-size:0.95rem;">
                    </div>
                    <div>
                        <label style="display:block; font-size:0.85rem; font-weight:700; margin-bottom:0.4rem; color: var(--premier-charcoal);">Phone Number ${isPHReq ? '*' : ''}</label>
                        <input type="tel" id="quiz-phone" ${isPHReq} style="width:100%; padding:0.75rem; border:1px solid var(--premier-beige); border-radius:6px; box-sizing:border-box; font-size:0.95rem;">
                    </div>
                    <button type="submit" class="btn btn-primary" style="margin-top:1rem; padding:0.9rem; font-size:1rem; font-weight:bold; letter-spacing:0.5px; background-color: var(--card-accent-color); border-color: var(--card-accent-color); color: white;">Start the Quiz</button>
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
            this.innerHTML = `<div style="text-align:center; padding:4rem; color: var(--premier-charcoal); opacity: 0.8;">Initializing quiz engine module...</div>`;
            
            try {
                const modulePath = `/quizzes/engines/${this.quizData.scoringType}.js`;
                const engineModule = await import(modulePath);
                engineModule.initializeQuizTrack(this);
            } catch (err) {
                console.error("Critical: Failed to resolve scoring module file:", err);
                this.innerHTML = `<div style="color: var(--card-accent-color); font-weight:bold; padding:2rem; text-align:center;">Engine Error: Could not launch script logic file '/quizzes/engines/${this.quizData.scoringType}.js'.</div>`;
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
            const response = await fetch('/data/reviews.json');
            if (!response.ok) throw new Error('Reviews payload retrieval failed');
            const reviews = await response.json();

            const validReviews = [];
            for (const rev of reviews) {
                const pageMarker = (rev[pageName] || '').trim().toLowerCase();
                if (pageMarker === 'x') {
                    const ratingValue = parseInt(rev['star rating'] || rev['rating']) || 5;
                    validReviews.push({
                        reviewer: rev['reviewer'] || 'Verified Client',
                        rating: ratingValue,
                        snippet: rev['snippet'] ? rev['snippet'].trim() : '',
                        fullText: rev['full review'] || rev['fullText'] || ''
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
                    ? `<h4 style="margin: 0 0 0.75rem 0; font-size: 1.05rem; font-style: italic; color: var(--premier-charcoal); line-height: 1.4;">"${rev.snippet}"</h4>`
                    : '';

                return `
                    <div class="review-component-card" style="background: white; padding: 1.75rem; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.05); display: flex; flex-direction: column; border-top: 5px solid var(--card-accent-color);">
                        <div style="color: var(--card-accent-color); font-size: 1rem; font-weight: 800; margin-bottom: 0.75rem; letter-spacing: 0.5px;">5.0 <span style="font-size: 1.1rem; letter-spacing: 1px;">${stars}</span></div>
                        ${snippetMarkup}
                        <p style="margin: 0 0 1.25rem 0; font-size: 0.95rem; color: var(--premier-charcoal); font-weight: 500; line-height: 1.6;">${rev.fullText}</p>
                        <div style="font-size: 0.8rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; color: var(--premier-charcoal); opacity: 0.7;">— ${rev.reviewer}</div>
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
 * Editorial Menu Share Utility
 * Spawns a clean, contextual social routing popover dropdown panel.
 * Gracefully cleans up click states automatically upon outside focus loss.
 */
document.addEventListener("DOMContentLoaded", () => {
  // Global click capturing filter pass
  document.body.addEventListener("click", (event) => {
    const btn = event.target.closest(".notebook-share-btn");
    
    // Clear active menus if clicking away entirely
    if (!btn) {
      document.querySelectorAll(".editorial-share-popover").forEach(el => el.remove());
      return;
    }

    event.stopPropagation();
    const existingMenu = btn.parentNode.querySelector(".editorial-share-popover");
    
    // Close existing dropdown instances
    if (existingMenu) {
      existingMenu.remove();
      return;
    }
    
    document.querySelectorAll(".editorial-share-popover").forEach(el => el.remove());

    const url = btn.getAttribute("data-url");
    const title = btn.getAttribute("data-title") || "Notebook Update";
    if (!url) return;

    // Build flat, clean, hex-free markup overlay elements
    const popover = document.createElement("div");
    popover.className = "editorial-share-popover";
    popover.style.cssText = `
      position: absolute; bottom: 100%; right: 0; margin-bottom: 6px;
      background-color: white; border: 1px solid var(--card-accent-color);
      border-radius: 4px; box-shadow: 0 4px 12px rgba(0,0,0,0.1);
      display: flex; flex-direction: column; width: 140px; z-index: 999; overflow: hidden;
    `;

    const itemStyle = `
      background: none; border: none; padding: 0.5rem 0.75rem; text-align: left;
      font-size: 0.75rem; font-weight: 600; color: var(--premier-charcoal);
      cursor: pointer; text-decoration: none; display: block; transition: background 0.15s;
    `;

    // Action A: Direct Copy Link Controller
    const copyAction = document.createElement("button");
    copyAction.style.cssText = itemStyle;
    copyAction.innerHTML = "📋 Copy Link";
    copyAction.addEventListener("click", () => {
      navigator.clipboard.writeText(url).then(() => {
        const prevText = copyAction.innerHTML;
        copyAction.innerHTML = "✅ Copied!";
        setTimeout(() => popover.remove(), 1200);
      });
    });

    // Action B: Facebook community routing bridge
    const fbAction = document.createElement("a");
    fbAction.style.cssText = itemStyle;
    fbAction.target = "_blank";
    fbAction.rel = "noopener noreferrer";
    fbAction.innerHTML = "👥 Facebook";
    fbAction.href = `https://www.facebook.com/sharer/sharer.php?u=${encodeURIComponent(url)}`;
    fbAction.addEventListener("click", () => setTimeout(() => popover.remove(), 500));

    // Action C: Email to family utility line
    const emailAction = document.createElement("a");
    emailAction.style.cssText = itemStyle;
    emailAction.innerHTML = "✉️ Email Link";
    emailAction.href = `mailto:?subject=${encodeURIComponent(title)}&body=Check this local update out: ${encodeURIComponent(url)}`;
    emailAction.addEventListener("click", () => setTimeout(() => popover.remove(), 500));

    // Append child loops into node canvas
    popover.appendChild(copyAction);
    popover.appendChild(fbAction);
    popover.appendChild(emailAction);
    
    // Lock position context layer relative to button element parent
    if (btn.parentNode) {
      btn.parentNode.style.position = "relative";
      btn.parentNode.appendChild(popover);
    }
  });
});

// Global Core Custom Elements Registries
customElements.define('quiz-engine', QuizEngine);
customElements.define('local-reviews', LocalReviews);