// File: components.js

/* ==========================================================================
   MYSEATTLESEARCH - NATIVE WEB COMPONENTS BUNDLE
   Includes: <youtube-lite>, <quiz-engine>, <local-reviews>
   ========================================================================== */

/**
 * 1. HIGH-PERFORMANCE LIGHTWEIGHT YOUTUBE EMBED (<youtube-lite>)
 * Supports custom R2 poster images to bypass 3rd-party TTL restrictions.
 */
class YouTubeLite extends HTMLElement {
    connectedCallback() {
        const videoId = this.getAttribute('video-id');
        const customPoster = this.getAttribute('poster');
        const label = this.getAttribute('label') || 'Play Video';

        if (!videoId) return;

        // Use custom R2 poster if provided; fallback to YouTube WebP thumbnail
        const posterUrl = customPoster || `https://i.ytimg.com/vi_webp/${videoId}/hqdefault.webp`;

        this.style.position = 'relative';
        this.style.display = 'block';
        this.style.width = '100%';
        this.style.aspectRatio = '16 / 9';
        this.style.backgroundColor = 'var(--premier-charcoal, #1a1a1a)';
        this.style.backgroundImage = `url('${posterUrl}')`;
        this.style.backgroundSize = 'cover';
        this.style.backgroundPosition = 'center';
        this.style.cursor = 'pointer';
        this.style.borderRadius = '8px';
        this.style.overflow = 'hidden';

        // Play button overlay
        this.innerHTML = `
            <button aria-label="${label}" style="position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); width: 68px; height: 48px; background-color: var(--card-accent-color, #c82020); border: none; border-radius: 12px; cursor: pointer; display: flex; align-items: center; justify-content: center; transition: transform 0.2s cubic-bezier(0.4, 0, 0.2, 1), background-color 0.2s ease; box-shadow: 0 4px 12px rgba(0,0,0,0.3); z-index: 2;">
                <svg viewBox="0 0 24 24" width="24" height="24" fill="#ffffff" style="margin-left: 3px;"><path d="M8 5v14l11-7z"/></svg>
            </button>
            <div style="position: absolute; top:0; left:0; width:100%; height:100%; background: rgba(0,0,0,0.15); z-index: 1;"></div>
        `;

        this.addEventListener('click', () => {
            const iframe = document.createElement('iframe');
            iframe.setAttribute('src', `https://www.youtube-nocookie.com/embed/${videoId}?autoplay=1&rel=0&modestbranding=1`);
            iframe.setAttribute('title', label);
            iframe.setAttribute('frameborder', '0');
            iframe.setAttribute('allow', 'accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture');
            iframe.setAttribute('allowfullscreen', 'true');
            iframe.style.width = '100%';
            iframe.style.height = '100%';
            iframe.style.position = 'absolute';
            iframe.style.top = '0';
            iframe.style.left = '0';
            iframe.style.borderRadius = '8px';
            iframe.style.border = 'none';

            this.innerHTML = '';
            this.appendChild(iframe);
        }, { once: true });
    }
}

/**
 * 2. HEADLESS CMS QUIZ ENGINE (<quiz-engine>)
 */
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

/**
 * 3. TESTIMONIAL REVIEW ENGINE (<local-reviews>)
 */
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
 * Platform Share Utility Bridge
 * Routes share requests to native system sheet configurations across mobile devices.
 * Desktop environments automatically drop back to the clipboard engine.
 */
document.addEventListener("DOMContentLoaded", () => {
  document.body.addEventListener("click", async (event) => {
    const shareTarget = event.target.closest(".notebook-share-btn");
    if (!shareTarget) return;

    const targetUrl = shareTarget.getAttribute("data-url");
    const targetTitle = shareTarget.getAttribute("data-title");
    if (!targetUrl) return;

    if (navigator.share) {
      try {
        await navigator.share({
          title: targetTitle || "MySeattleSearch Update",
          text: `Check out this update: ${targetTitle}`,
          url: targetUrl
        });
      } catch (shareErr) {
        if (shareErr.name !== "AbortError") {
          executeClipboardFallback(shareTarget, targetUrl);
        }
      }
    } else {
      executeClipboardFallback(shareTarget, targetUrl);
    }
  });
});

function executeClipboardFallback(element, urlToCopy) {
  navigator.clipboard.writeText(urlToCopy).then(() => {
    const originalText = element.innerHTML;
    element.innerHTML = `✅ Link Copied!`;
    element.disabled = true;

    setTimeout(() => {
      element.innerHTML = originalText;
      element.disabled = false;
    }, 2000);
  }).catch(err => {
    console.error("Clipboard operation rejected: ", err);
  });
}

// Global Core Custom Elements Registries
if (!customElements.get('youtube-lite')) {
    customElements.define('youtube-lite', YouTubeLite);
}
if (!customElements.get('quiz-engine')) {
    customElements.define('quiz-engine', QuizEngine);
}
if (!customElements.get('local-reviews')) {
    customElements.define('local-reviews', LocalReviews);
}