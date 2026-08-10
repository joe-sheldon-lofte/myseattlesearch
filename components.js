/* File: components.js */
/* ==========================================================================
   MYSEATTLESEARCH - NATIVE WEB COMPONENTS BUNDLE
   Includes: <youtube-lite>, <quiz-engine>, <local-reviews>, <live-banner>, 
             <cms-publisher>, <floating-dock>
   ========================================================================== */

/**
 * 1. HIGH-PERFORMANCE LIGHTWEIGHT YOUTUBE EMBED (<youtube-lite>)
 */
class YouTubeLite extends HTMLElement {
    connectedCallback() {
        const videoId = this.getAttribute('video-id');
        const customPoster = this.getAttribute('poster');
        const label = this.getAttribute('label') || 'Play Video';

        if (!videoId) return;

        const posterUrl = customPoster || `https://i.ytimg.com/vi_webp/${videoId}/hqdefault.webp`;

        this.style.position = 'relative';
        this.style.display = 'block';
        this.style.width = '100%';
        this.style.aspectRatio = '16 / 9';
        this.style.backgroundColor = 'var(--premier-charcoal)';
        this.style.backgroundImage = `url('${posterUrl}')`;
        this.style.backgroundSize = 'cover';
        this.style.backgroundPosition = 'center';
        this.style.cursor = 'pointer';
        this.style.borderRadius = '8px';
        this.style.overflow = 'hidden';

        this.innerHTML = `
            <button aria-label="${label}" style="position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); width: 68px; height: 48px; background-color: var(--card-accent-color); border: none; border-radius: 12px; cursor: pointer; display: flex; align-items: center; justify-content: center; transition: transform 0.2s cubic-bezier(0.4, 0, 0.2, 1), background-color 0.2s ease; box-shadow: 0 4px 12px rgba(0,0,0,0.3); z-index: 2;">
                <svg viewBox="0 0 24 24" width="24" height="24" fill="var(--white)" style="margin-left: 3px;"><path d="M8 5v14l11-7z"/></svg>
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
                    <div class="profile-card quiz-container-card" style="max-width:600px; margin:2rem auto; padding:3rem 2.5rem; background: var(--white); border-radius:12px; box-shadow:0 10px 30px rgba(0,0,0,0.08); text-align:center; border-top:6px solid var(--premier-beige);">
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
            <div class="profile-card quiz-container-card" style="max-width:600px; margin:2rem auto; padding:2.5rem; background: var(--white); border-radius:12px; box-shadow:0 10px 30px rgba(0,0,0,0.08); border-top: 6px solid var(--card-accent-color);">
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
                    <button type="submit" class="btn btn-primary" style="margin-top:1rem; padding:0.9rem; font-size:1rem; font-weight:bold; letter-spacing:0.5px; background-color: var(--card-accent-color); border-color: var(--card-accent-color); color: var(--white);">Start the Quiz</button>
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
                    <div class="review-component-card" style="background: var(--white); padding: 1.75rem; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.05); display: flex; flex-direction: column; border-top: 5px solid var(--card-accent-color);">
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
 * 4. REAL-TIME EDGE LIVE STREAM NOTIFICATION BANNER (<live-banner>)
 */
class LiveBanner extends HTMLElement {
    async connectedCallback() {
        const workerUrl = this.getAttribute('worker-url');
        if (!workerUrl) return;

        if (sessionStorage.getItem('dismissed_live_banner') === 'true') {
            return;
        }

        try {
            const response = await fetch(workerUrl, { cache: 'no-store' });
            if (!response.ok) return;
            
            const data = await response.json();
            if (data && data.is_live) {
                this.render(data);
            }
        } catch (err) {
            console.error("Live banner execution error:", err);
        }
    }

    render(data) {
        const title = data.title || "Live Stream Broadcast";
        const targetUrl = data.stream_url || "/live/";

        this.style.display = "block";
        this.innerHTML = `
            <div class="live-banner-bar">
                <div class="live-banner-info">
                    <span class="live-beacon-dot"></span>
                    <span class="live-badge-label">LIVE NOW</span>
                    <span class="live-stream-title">${title}</span>
                </div>
                <div class="live-banner-actions">
                    <a href="${targetUrl}" class="live-join-btn">Watch Stream &rarr;</a>
                    <button class="live-close-btn" aria-label="Dismiss live alert">✕</button>
                </div>
            </div>
        `;

        const closeBtn = this.querySelector('.live-close-btn');
        if (closeBtn) {
            closeBtn.addEventListener('click', () => {
                sessionStorage.setItem('dismissed_live_banner', 'true');
                this.style.display = "none";
            });
        }
    }
}

/**
 * 5. AUTHOR CMS PUBLISHER WEB SUITE (<cms-publisher>)
 */
class CMSPublisher extends HTMLElement {
    constructor() {
        super();
        this.authKey = "";
        this.author = null;
        this.authorPosts = [];
        this.editingSlug = null;
    }

    async connectedCallback() {
        const urlParams = new URLSearchParams(window.location.search);
        this.authKey = urlParams.get("AUTHKEY") || urlParams.get("AuthKey") || urlParams.get("auth_key") || "";

        if (!this.authKey) return;

        this.innerHTML = `<div style="text-align:center; padding: 3rem; color: var(--premier-charcoal);">Authenticating author session...</div>`;

        try {
            let teamData = [];
            try {
                const teamRes = await fetch('/data/team.json');
                if (teamRes.ok) teamData = await teamRes.json();
            } catch (e) {
                console.warn("Could not load local team.json, using session fallbacks:", e);
            }

            const workerUrl = 'https://myseattlesearch-quiz-gateway.joe-54b.workers.dev/publisher';
            const pubRes = await fetch(`${workerUrl}?AUTHKEY=${encodeURIComponent(this.authKey)}`);
            
            if (!pubRes.ok) {
                this.innerHTML = `<div style="text-align:center; padding: 2rem; color: var(--card-accent-color); font-weight: bold;">Authentication Failed: Gateway connection error (${pubRes.status}).</div>`;
                return;
            }

            const sessionData = await pubRes.json();
            if (sessionData.status !== "success") {
                this.innerHTML = `<div style="text-align:center; padding: 2rem; color: var(--card-accent-color); font-weight: bold;">Authentication Failed: ${sessionData.message || "Invalid AuthKey"}.</div>`;
                return;
            }

            const teamIdStr = String(sessionData.teamId || "").replace(".0", "").trim();
            const matchedTeam = (Array.isArray(teamData) ? teamData.find(m => String(m.id).replace(".0", "").trim() === teamIdStr) : null) || {};

            this.author = {
                teamId: teamIdStr || matchedTeam.id || "1",
                name: sessionData.name || matchedTeam.name || "Joe Sheldon",
                position: matchedTeam.position || "Senior Real Estate Agent",
                photo: matchedTeam.photo || "https://assets.myseattlesearch.com/repomove/joe.webp",
                description: matchedTeam.description || "",
                email: matchedTeam.email || "joe.sheldon@redfin.com"
            };

            this.authorPosts = sessionData.recentPosts || [];
            this.renderPublisherSuite();
        } catch (err) {
            console.error("Publisher Suite Hydration Error:", err);
            this.innerHTML = `<div style="text-align:center; padding: 2rem; color: var(--card-accent-color); font-weight: bold;">Unable to load publishing suite interface: ${err.message}</div>`;
        }
    }

    renderPublisherSuite() {
        this.innerHTML = `
            <div style="background: var(--white); padding: 2rem; border-radius: 10px; box-shadow: 0 4px 20px rgba(0,0,0,0.06); margin-bottom: 2rem; border-top: 5px solid var(--card-accent-color);">
                <div style="display: flex; gap: 1.5rem; align-items: center; flex-wrap: wrap;">
                    <img src="${this.author.photo}" alt="${this.author.name}" style="width: 120px; height: 120px; border-radius: 50%; object-fit: cover; border: 3px solid var(--card-accent-color);" />
                    <div style="flex: 1;">
                        <span style="font-size: 0.75rem; font-weight: 800; text-transform: uppercase; letter-spacing: 1px; color: var(--card-accent-color);">Authenticated Author Session (Team ID: ${this.author.teamId})</span>
                        <h2 style="margin: 0.2rem 0; font-size: 1.6rem; color: var(--premier-charcoal);">${this.author.name}</h2>
                        <p style="margin: 0 0 0.5rem 0; font-weight: 700; color: rgba(0,0,0,0.6); font-size: 0.9rem;">${this.author.position}</p>
                        <p style="margin: 0; font-size: 0.9rem; line-height: 1.4; opacity: 0.85;">${this.author.description}</p>
                    </div>
                </div>
            </div>

            <div style="background: var(--white); padding: 2rem; border-radius: 10px; box-shadow: 0 4px 20px rgba(0,0,0,0.06); margin-bottom: 2.5rem; border: 1px solid var(--premier-beige);">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1.5rem;">
                    <h3 id="form-mode-title" style="margin: 0; color: var(--premier-charcoal); font-size: 1.3rem;">Create New Post</h3>
                    <button id="cancel-edit-btn" style="display: none; background: transparent; border: 1px solid var(--card-accent-color); color: var(--card-accent-color); padding: 0.4rem 0.8rem; border-radius: 4px; font-weight: 700; cursor: pointer;">Cancel Editing</button>
                </div>

                <form id="publisher-editor-form" style="display: flex; flex-direction: column; gap: 1.2rem;">
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1rem;">
                        <div>
                            <label style="display: block; font-weight: 700; font-size: 0.85rem; margin-bottom: 0.3rem;">Entry Type *</label>
                            <select id="post-type" required style="width: 100%; padding: 0.75rem; border: 1px solid var(--premier-beige); border-radius: 6px; font-size: 0.95rem;">
                                <option value="post">Post (Short Update)</option>
                                <option value="note">Note (Focused Commentary)</option>
                                <option value="article">Article (Full Markdown Publication)</option>
                            </select>
                        </div>
                        <div>
                            <label style="display: block; font-weight: 700; font-size: 0.85rem; margin-bottom: 0.3rem;">Tags (comma-separated)</label>
                            <input type="text" id="post-tags" placeholder="e.g. real-estate, kirkland, open-house" style="width: 100%; padding: 0.75rem; border: 1px solid var(--premier-beige); border-radius: 6px; font-size: 0.95rem; box-sizing: border-box;" />
                        </div>
                    </div>

                    <div>
                        <label style="display: block; font-weight: 700; font-size: 0.85rem; margin-bottom: 0.3rem;">Title *</label>
                        <input type="text" id="post-title" required placeholder="Entry Title" style="width: 100%; padding: 0.75rem; border: 1px solid var(--premier-beige); border-radius: 6px; font-size: 0.95rem; box-sizing: border-box;" />
                    </div>

                    <div>
                        <label style="display: block; font-weight: 700; font-size: 0.85rem; margin-bottom: 0.3rem;">Headline (Displayed on Card)</label>
                        <input type="text" id="post-headline" placeholder="Public headline text..." style="width: 100%; padding: 0.75rem; border: 1px solid var(--premier-beige); border-radius: 6px; font-size: 0.95rem; box-sizing: border-box;" />
                    </div>

                    <div>
                        <label style="display: block; font-weight: 700; font-size: 0.85rem; margin-bottom: 0.3rem;">Subhead</label>
                        <input type="text" id="post-subhead" placeholder="Brief subtitle or summary..." style="width: 100%; padding: 0.75rem; border: 1px solid var(--premier-beige); border-radius: 6px; font-size: 0.95rem; box-sizing: border-box;" />
                    </div>

                    <div>
                        <label style="display: block; font-weight: 700; font-size: 0.85rem; margin-bottom: 0.3rem;">Content (Full Markdown Supported) *</label>
                        <textarea id="post-content" required rows="10" placeholder="Write update in Markdown..." style="width: 100%; padding: 0.75rem; border: 1px solid var(--premier-beige); border-radius: 6px; font-size: 0.95rem; font-family: monospace; box-sizing: border-box; line-height: 1.5;"></textarea>
                    </div>

                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1rem;">
                        <div>
                            <label style="display: block; font-weight: 700; font-size: 0.85rem; margin-bottom: 0.3rem;">URL 1 Label & Link</label>
                            <input type="text" id="url-1-label" placeholder="Button 1 Label" style="width: 100%; padding: 0.5rem; margin-bottom: 0.4rem; border: 1px solid var(--premier-beige); border-radius: 4px; box-sizing: border-box;" />
                            <input type="url" id="url-1" placeholder="https://..." style="width: 100%; padding: 0.5rem; border: 1px solid var(--premier-beige); border-radius: 4px; box-sizing: border-box;" />
                        </div>
                        <div>
                            <label style="display: block; font-weight: 700; font-size: 0.85rem; margin-bottom: 0.3rem;">URL 2 Label & Link</label>
                            <input type="text" id="url-2-label" placeholder="Button 2 Label" style="width: 100%; padding: 0.5rem; margin-bottom: 0.4rem; border: 1px solid var(--premier-beige); border-radius: 4px; box-sizing: border-box;" />
                            <input type="url" id="url-2" placeholder="https://..." style="width: 100%; padding: 0.5rem; border: 1px solid var(--premier-beige); border-radius: 4px; box-sizing: border-box;" />
                        </div>
                    </div>

                    <div>
                        <label style="display: block; font-weight: 700; font-size: 0.85rem; margin-bottom: 0.3rem;">Attach Images (Up to 5 files - Uploaded directly to R2 as WebP)</label>
                        <input type="file" id="image-files" multiple accept="image/*" style="width: 100%; padding: 0.75rem; border: 2px dashed var(--premier-beige); border-radius: 6px; box-sizing: border-box; background: rgba(0,0,0,0.01);" />
                        <div id="image-upload-status" style="font-size: 0.85rem; color: var(--card-accent-color); margin-top: 0.4rem;"></div>
                    </div>

                    <button type="submit" id="submit-post-btn" style="padding: 1rem; background-color: var(--card-accent-color); color: var(--white); border: none; border-radius: 6px; font-weight: 800; font-size: 1rem; cursor: pointer; letter-spacing: 0.5px; margin-top: 0.5rem;">
                        Publish Entry
                    </button>
                </form>
            </div>

            <div style="background: var(--white); padding: 2rem; border-radius: 10px; box-shadow: 0 4px 20px rgba(0,0,0,0.06); border: 1px solid var(--premier-beige);">
                <h3 style="margin: 0 0 1.25rem 0; color: var(--premier-charcoal);">Recent 10 Published Entries</h3>
                <div id="author-archive-list" style="display: flex; flex-direction: column; gap: 1rem;">
                    ${this.renderArchiveList()}
                </div>
            </div>
        `;

        this.bindEvents();
    }

    renderArchiveList() {
        if (!this.authorPosts || this.authorPosts.length === 0) {
            return `<p style="opacity: 0.7; font-style: italic;">No previous entries found.</p>`;
        }

        return this.authorPosts.slice(0, 10).map(post => `
            <div style="display: flex; justify-content: space-between; align-items: center; padding: 1rem; border: 1px solid var(--premier-beige); border-radius: 6px; background: var(--dynamic-bg-highlight);">
                <div>
                    <span style="font-size: 0.7rem; font-weight: 800; text-transform: uppercase; color: var(--card-accent-color); display: inline-block; margin-bottom: 0.2rem;">${post.type || 'post'} • ${post.date || ''}</span>
                    <h4 style="margin: 0; font-size: 1rem; color: var(--premier-charcoal);">${post.title || post.headline || 'Untitled'}</h4>
                </div>
                <button class="edit-post-btn" data-slug="${post.slug}" style="padding: 0.4rem 0.9rem; background-color: var(--premier-charcoal); color: var(--white); border: none; border-radius: 4px; font-weight: 700; cursor: pointer; font-size: 0.8rem;">
                    Edit
                </button>
            </div>
        `).join('');
    }

    bindEvents() {
        const form = this.querySelector('#publisher-editor-form');
        const cancelBtn = this.querySelector('#cancel-edit-btn');

        this.querySelectorAll('.edit-post-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const slug = e.target.getAttribute('data-slug');
                const post = this.authorPosts.find(p => p.slug === slug);
                if (post) {
                    this.editingSlug = slug;
                    this.querySelector('#form-mode-title').textContent = `Editing Post: ${post.title || slug}`;
                    cancelBtn.style.display = 'inline-block';

                    this.querySelector('#post-type').value = post.type || 'post';
                    this.querySelector('#post-title').value = post.title || '';
                    this.querySelector('#post-headline').value = post.headline || '';
                    this.querySelector('#post-subhead').value = post.subhead || '';
                    this.querySelector('#post-tags').value = (post.tags || []).join(', ');
                    this.querySelector('#post-content').value = post.content || '';
                    this.querySelector('#url-1-label').value = post.url_1_label || '';
                    this.querySelector('#url-1').value = post.url_1 || '';
                    this.querySelector('#url-2-label').value = post.url_2_label || '';
                    this.querySelector('#url-2').value = post.url_2 || '';

                    window.scrollTo({ top: form.offsetTop - 100, behavior: 'smooth' });
                }
            });
        });

        cancelBtn.addEventListener('click', () => {
            this.editingSlug = null;
            form.reset();
            this.querySelector('#form-mode-title').textContent = 'Create New Post';
            cancelBtn.style.display = 'none';
        });

        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const submitBtn = this.querySelector('#submit-post-btn');
            submitBtn.disabled = true;
            submitBtn.textContent = 'Optimizing & Publishing...';

            const fileInput = this.querySelector('#image-files');
            const files = Array.from(fileInput.files).slice(0, 5);

            const formData = new FormData();
            formData.append('AUTHKEY', this.authKey);
            formData.append('type', this.querySelector('#post-type').value);
            formData.append('title', this.querySelector('#post-title').value);
            formData.append('headline', this.querySelector('#post-headline').value);
            formData.append('subhead', this.querySelector('#post-subhead').value);
            formData.append('tags', this.querySelector('#post-tags').value);
            formData.append('content', this.querySelector('#post-content').value);
            formData.append('url_1_label', this.querySelector('#url-1-label').value);
            formData.append('url_1', this.querySelector('#url-1').value);
            formData.append('url_2_label', this.querySelector('#url-2-label').value);
            formData.append('url_2', this.querySelector('#url-2').value);
            formData.append('author', this.author.teamId);

            if (this.editingSlug) {
                formData.append('editingSlug', this.editingSlug);
            }

            files.forEach((file, idx) => {
                formData.append(`image_${idx + 1}`, file);
            });

            try {
                const res = await fetch('https://myseattlesearch-quiz-gateway.joe-54b.workers.dev/publisher', {
                    method: 'POST',
                    body: formData
                });

                if (res.ok) {
                    alert('Entry successfully published & live site rebuild triggered!');
                    window.location.reload();
                } else {
                    const err = await res.json();
                    alert(`Publishing error: ${err.message || 'Server failed to save entry.'}`);
                    submitBtn.disabled = false;
                    submitBtn.textContent = 'Publish Entry';
                }
            } catch (err) {
                console.error('Publish submission failed:', err);
                alert('Connection error submitting entry to gateway.');
                submitBtn.disabled = false;
                submitBtn.textContent = 'Publish Entry';
            }
        });
    }
}

/**
 * 6. UNIFIED LIQUID GLASS FLOATING DOCK (<floating-dock>)
 * Features: Dual-embedded pill capsule, Pagefind lazy-loader, and direct contact drawer sheet.
 */
class FloatingDock extends HTMLElement {
    constructor() {
        super();
        this.pagefindLoaded = false;
    }

    connectedCallback() {
        // Automatically purge any legacy floating CTA elements if present in DOM
        document.querySelectorAll('.floating-cta, .cta-bar, .mobile-cta, .persistent-cta-deck, [class*="cta-floating"]').forEach(el => el.remove());

        this.innerHTML = `
            <!-- Floating Dock Outer Capsule -->
            <div class="dock-floating-container">
                <div class="dock-capsule-bar">
                    <!-- Left Section: Desktop Direct Pills / Mobile Contact Trigger Pill -->
                    <div class="dock-left-actions">
                        <!-- Mobile Only: Contact Drawer Trigger Pill -->
                        <button class="dock-pill-btn dock-btn-contact-main dock-mobile-only" id="dockContactTrigger" aria-label="Open Contact Options">
                            <svg viewBox="0 0 24 24" class="dock-svg-icon"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H5.2L4 17.2V4h16v12z"/></svg>
                            <span>Contact</span>
                        </button>
                        
                        <!-- Desktop Only: Direct Action Pills (Text, Chat, Book) -->
                        <a href="sms:+12066577493" class="dock-pill-btn dock-desktop-only" aria-label="Text Joe via SMS">
                            <svg viewBox="0 0 24 24" class="dock-svg-icon"><path d="M20 2H4c-1.1 0-1.99.9-1.99 2L2 22l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zM9 11H7V9h2v2zm4 0h-2V9h2v2zm4 0h-2V9h2v2z"/></svg>
                            <span>Text</span>
                        </a>
                        <a href="/chat/" class="dock-pill-btn dock-desktop-only" aria-label="Live Chat with Joe">
                            <svg viewBox="0 0 24 24" class="dock-svg-icon"><path d="M20 2H4c-1.1 0-1.99.9-1.99 2L2 22l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zM6 9h12v2H6V9zm0 4h8v2H6v-2z"/></svg>
                            <span>Chat</span>
                        </a>
                        <a href="/book/" class="dock-pill-btn dock-desktop-only" aria-label="Book Strategy Consultation">
                            <svg viewBox="0 0 24 24" class="dock-svg-icon"><path d="M19 4h-1V2h-2v2H8V2H6v2H5c-1.11 0-1.99.9-1.99 2L3 20c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 16H5V10h14v10zm0-12H5V6h14v2z"/></svg>
                            <span>Book</span>
                        </a>
                    </div>

                    <!-- Right Section: Pagefind Search Trigger Pill -->
                    <div class="dock-right-actions">
                        <button class="dock-pill-btn dock-btn-search" id="dockSearchTrigger" aria-label="Open Site Search">
                            <svg viewBox="0 0 24 24" class="dock-svg-icon"><path d="M15.5 14h-.79l-.28-.27C15.41 12.59 16 11.11 16 9.5 16 5.91 13.09 3 9.5 3S3 5.91 3 9.5 5.91 16 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z"/></svg>
                            <span class="dock-search-label-desktop">Search MySeattleSearch...</span>
                            <span class="dock-search-label-mobile">Search</span>
                        </button>
                    </div>
                </div>
            </div>

            <!-- Contact Options Liquid Glass Bottom Drawer Sheet (Mobile Only) -->
            <div class="dock-sheet-backdrop" id="dockContactSheet">
                <div class="dock-sheet-card">
                    <div class="dock-sheet-header">
                        <h3 class="dock-sheet-title">Connect with Joe Sheldon</h3>
                        <button class="dock-sheet-close" id="dockContactClose" aria-label="Close Contact Sheet">&times;</button>
                    </div>
                    <div class="dock-sheet-links">
                        <a href="sms:+12066577493" class="dock-sheet-item">
                            <span class="dock-sheet-icon">💬</span>
                            <div class="dock-sheet-text">
                                <strong>Text Joe</strong>
                                <small>Instant SMS: (206) 657-7493</small>
                            </div>
                        </a>
                        <a href="/chat/" class="dock-sheet-item">
                            <span class="dock-sheet-icon">💬</span>
                            <div class="dock-sheet-text">
                                <strong>Live Chat</strong>
                                <small>Real-Time Q&A with Joe</small>
                            </div>
                        </a>
                        <a href="/book/" class="dock-sheet-item">
                            <span class="dock-sheet-icon">📅</span>
                            <div class="dock-sheet-text">
                                <strong>Book Consultation</strong>
                                <small>Schedule Strategy Meeting</small>
                            </div>
                        </a>
                        <a href="tel:2066577493" class="dock-sheet-item">
                            <span class="dock-sheet-icon">📞</span>
                            <div class="dock-sheet-text">
                                <strong>Call Direct</strong>
                                <small>(206) 657-7493</small>
                            </div>
                        </a>
                    </div>
                </div>
            </div>

            <!-- Pagefind Search Full-Width Modal Overlay -->
            <div class="dock-modal-backdrop" id="dockSearchModal">
                <div class="dock-modal-card">
                    <div class="dock-modal-header">
                        <span class="dock-modal-title">Site Search</span>
                        <button class="dock-modal-close" id="dockSearchClose" aria-label="Close Search Overlay">&times;</button>
                    </div>
                    <div id="pagefind-search-container" class="dock-pagefind-mount"></div>
                </div>
            </div>
        `;

        this.bindDockEvents();
    }

    bindDockEvents() {
        const contactTrigger = this.querySelector('#dockContactTrigger');
        const contactSheet = this.querySelector('#dockContactSheet');
        const contactClose = this.querySelector('#dockContactClose');

        const searchTrigger = this.querySelector('#dockSearchTrigger');
        const searchModal = this.querySelector('#dockSearchModal');
        const searchClose = this.querySelector('#dockSearchClose');

        // Contact Sheet Controls
        if (contactTrigger && contactSheet) {
            contactTrigger.addEventListener('click', () => {
                contactSheet.classList.add('is-open');
            });
        }

        if (contactClose && contactSheet) {
            contactClose.addEventListener('click', () => {
                contactSheet.classList.remove('is-open');
            });
        }

        if (contactSheet) {
            contactSheet.addEventListener('click', (e) => {
                if (e.target === contactSheet) {
                    contactSheet.classList.remove('is-open');
                }
            });
        }

        // Search Overlay Controls & Lazy Loader
        if (searchTrigger && searchModal) {
            searchTrigger.addEventListener('click', () => {
                searchModal.classList.add('is-open');
                this.lazyLoadPagefind();
            });
        }

        if (searchClose && searchModal) {
            searchClose.addEventListener('click', () => {
                searchModal.classList.remove('is-open');
            });
        }

        if (searchModal) {
            searchModal.addEventListener('click', (e) => {
                if (e.target === searchModal) {
                    searchModal.classList.remove('is-open');
                }
            });
        }

        // Global Esc Key Dismissal
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                if (contactSheet) contactSheet.classList.remove('is-open');
                if (searchModal) searchModal.classList.remove('is-open');
            }
        });
    }

    lazyLoadPagefind() {
        if (this.pagefindLoaded) return;
        this.pagefindLoaded = true;

        const container = this.querySelector('#pagefind-search-container');
        if (container) {
            container.innerHTML = '<div style="text-align:center; padding: 2.5rem; color: var(--premier-charcoal); font-weight: 500;">Loading search engine...</div>';
        }

        // 1. Inject Pagefind UI CSS Stylesheet
        if (!document.querySelector('link[href*="pagefind-ui.css"]')) {
            const link = document.createElement('link');
            link.rel = 'stylesheet';
            link.href = '/pagefind/pagefind-ui.css';
            document.head.appendChild(link);
        }

        // 2. Inject Pagefind UI JS Engine
        if (!document.querySelector('script[src*="pagefind-ui.js"]')) {
            const script = document.createElement('script');
            script.src = '/pagefind/pagefind-ui.js';
            script.onload = () => {
                if (window.PagefindUI) {
                    if (container) container.innerHTML = '';
                    new window.PagefindUI({
                        element: "#pagefind-search-container",
                        showSubResults: true,
                        showImages: false,
                        resetStyles: false,
                        bundlePath: "/pagefind/"
                    });

                    setTimeout(() => {
                        const input = container.querySelector('input');
                        if (input) input.focus();
                    }, 150);
                }
            };
            document.head.appendChild(script);
        }
    }
}

/**
 * Platform Share Utility Bridge
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
if (!customElements.get('live-banner')) {
    customElements.define('live-banner', LiveBanner);
}
if (!customElements.get('cms-publisher')) {
    customElements.define('cms-publisher', CMSPublisher);
}
if (!customElements.get('floating-dock')) {
    customElements.define('floating-dock', FloatingDock);
}