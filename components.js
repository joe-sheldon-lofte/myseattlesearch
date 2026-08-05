/* ==========================================================================
   MYSEATTLESEARCH - NATIVE WEB COMPONENTS BUNDLE
   Includes: <youtube-lite>, <quiz-engine>, <local-reviews>, <live-banner>, <cms-publisher>
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

// File: worker.js

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const pathname = url.pathname.toLowerCase();

    // 1. Establish robust CORS response headers
    const corsHeaders = {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
      "Access-Control-Max-Age": "86400",
    };

    // 2. Intercept browser safety preflight checks (OPTIONS)
    if (request.method === "OPTIONS") {
      return new Response(null, { headers: corsHeaders });
    }

    // ====================================================================
    // ROUTE 1: PROTECTED CMS PUBLISHER SUITE (/publisher)
    // ====================================================================
    if (pathname.startsWith("/publisher")) {
      // A. GET ROUTE: Fetch author session and 10 recent posts via Apps Script
      if (request.method === "GET") {
        const authKey = url.searchParams.get("AUTHKEY") || url.searchParams.get("AuthKey") || url.searchParams.get("auth_key") || "";
        if (!authKey) {
          return new Response(JSON.stringify({ status: "error", message: "Missing AuthKey parameter." }), {
            status: 400,
            headers: { ...corsHeaders, "Content-Type": "application/json" }
          });
        }

        const appsScriptUrl = env.APPS_SCRIPT_URL || "https://script.google.com/macros/s/AKfycby1g96t4ibQzFPaTqkHYtZFgWAaZLNso9YhF2Usw5VGV3Qmzwcr45mnY75nT9fYhxkG/exec";
        const res = await fetch(`${appsScriptUrl}?AUTHKEY=${encodeURIComponent(authKey)}`);
        const data = await res.json();
        
        return new Response(JSON.stringify(data), {
          status: res.status,
          headers: { ...corsHeaders, "Content-Type": "application/json" }
        });
      }

      // B. POST ROUTE: Authenticate AuthKey, upload R2 WebP images, commit .md to GitHub, and rebuild
      if (request.method === "POST") {
        try {
          const formData = await request.formData();
          const authKey = formData.get("AUTHKEY") || formData.get("AuthKey") || formData.get("auth_key") || "";

          if (!authKey) {
            return new Response(JSON.stringify({ status: "error", message: "Unauthorized: Missing AuthKey." }), {
              status: 403,
              headers: { ...corsHeaders, "Content-Type": "application/json" }
            });
          }

          // SERVER-SIDE AUTHKEY VERIFICATION WITH APPS SCRIPT
          const appsScriptUrl = env.APPS_SCRIPT_URL || "https://script.google.com/macros/s/AKfycby1g96t4ibQzFPaTqkHYtZFgWAaZLNso9YhF2Usw5VGV3Qmzwcr45mnY75nT9fYhxkG/exec";
          const verifyRes = await fetch(`${appsScriptUrl}?AUTHKEY=${encodeURIComponent(authKey)}`);
          const verifyData = await verifyRes.json();

          if (!verifyRes.ok || verifyData.status !== "success") {
            return new Response(JSON.stringify({ status: "error", message: "Unauthorized: Invalid AuthKey." }), {
              status: 403,
              headers: { ...corsHeaders, "Content-Type": "application/json" }
            });
          }

          const teamId = verifyData.teamId;
          const postType = (formData.get("type") || "post").toLowerCase();
          const title = formData.get("title") || "Untitled";
          const headline = formData.get("headline") || "";
          const subhead = formData.get("subhead") || "";
          const tags = formData.get("tags") || "";
          const content = formData.get("content") || "";
          const url1Label = formData.get("url_1_label") || "";
          const url1 = formData.get("url_1") || "";
          const url2Label = formData.get("url_2_label") || "";
          const url2 = formData.get("url_2") || "";
          const editingSlug = formData.get("editingSlug") || "";

          const todayStr = new Date().toISOString().split("T")[0];
          const rawSlug = editingSlug || `${todayStr}-${slugify(title)}`;
          const postSlug = rawSlug.replace(/^(\d{4}-\d{2}-\d{2}-)+/, `${todayStr}-`);

          // OPTIMIZE & UPLOAD IMAGES DIRECTLY TO CLOUDFLARE R2
          const imageUrls = [];
          for (let i = 1; i <= 5; i++) {
            const file = formData.get(`image_${i}`);
            if (file && file instanceof File && file.size > 0) {
              const r2Key = `cms/${postSlug}-img-${i}.webp`;
              await env.MYSEATTLESEARCH_R2.put(r2Key, file.stream(), {
                httpMetadata: { contentType: "image/webp" }
              });
              imageUrls.push(`https://assets.myseattlesearch.com/${r2Key}`);
            } else {
              imageUrls.push("");
            }
          }

          // CONSTRUCT NUNJUCKS FRONT-MATTER & MARKDOWN PAYLOAD
          const tagsFormatted = tags.split(",").map(t => `"${t.trim()}"`).filter(t => t !== '""').join(", ");
          const markdownContent = `---
layout: post.njk
title: "${title.replace(/"/g, '\\"')}"
headline: "${headline.replace(/"/g, '\\"')}"
subhead: "${subhead.replace(/"/g, '\\"')}"
date: ${todayStr}
author: "${teamId}"
tags: [${tagsFormatted}]
type: "${postType}"
url_1_label: "${url1Label}"
url_1: "${url1}"
url_2_label: "${url2Label}"
url_2: "${url2}"
image_1: "${imageUrls[0]}"
image_2: "${imageUrls[1]}"
image_3: "${imageUrls[2]}"
image_4: "${imageUrls[3]}"
image_5: "${imageUrls[4]}"
---
${content}`;

          // COMMIT FILE DIRECTLY TO GITHUB REPOSITORY
          const repoPath = `posts/${postSlug}.md`;
          const ghRepo = env.GH_REPO || "joe-sheldon-lofte/myseattlesearch";
          const ghApiUrl = `https://api.github.com/repos/${ghRepo}/contents/${repoPath}`;

          let sha = "";
          const existingFileRes = await fetch(ghApiUrl, {
            headers: {
              "Authorization": `Bearer ${env.GH_PAT}`,
              "User-Agent": "Cloudflare-Worker-CMS",
              "Accept": "application/vnd.github.v3+json"
            }
          });
          if (existingFileRes.ok) {
            const existingFileData = await existingFileRes.json();
            sha = existingFileData.sha;
          }

          const commitPayload = {
            message: `CMS Publisher: ${editingSlug ? 'Update' : 'Create'} ${postSlug}.md`,
            content: btoa(unescape(encodeURIComponent(markdownContent))),
            branch: "main"
          };
          if (sha) commitPayload.sha = sha;

          const commitRes = await fetch(ghApiUrl, {
            method: "PUT",
            headers: {
              "Authorization": `Bearer ${env.GH_PAT}`,
              "User-Agent": "Cloudflare-Worker-CMS",
              "Content-Type": "application/json",
              "Accept": "application/vnd.github.v3+json"
            },
            body: JSON.stringify(commitPayload)
          });

          if (!commitRes.ok) {
            const commitErr = await commitRes.text();
            throw new Error(`GitHub Commit Error: ${commitErr}`);
          }

          // TRIGGER ELEVENTY BUILD DISPATCH EVENT
          const dispatchUrl = `https://api.github.com/repos/${ghRepo}/actions/workflows/deploy-site.yml/dispatches`;
          await fetch(dispatchUrl, {
            method: "POST",
            headers: {
              "Authorization": `Bearer ${env.GH_PAT}`,
              "User-Agent": "Cloudflare-Worker-CMS",
              "Content-Type": "application/json",
              "Accept": "application/vnd.github.v3+json"
            },
            body: JSON.stringify({ ref: "main" })
          });

          return new Response(JSON.stringify({
            status: "success",
            message: "Post published and site build dispatched.",
            slug: postSlug
          }), {
            status: 200,
            headers: { ...corsHeaders, "Content-Type": "application/json" }
          });

        } catch (err) {
          return new Response(JSON.stringify({ status: "error", message: err.message }), {
            status: 500,
            headers: { ...corsHeaders, "Content-Type": "application/json" }
          });
        }
      }
    }

    // ====================================================================
    // ROUTE 2: EXISTING PUBLIC QUIZZES & EVENTS GOOGLE SHEETS INGESTION
    // ====================================================================
    if (request.method !== "POST") {
      return new Response(JSON.stringify({ error: "Method not allowed. Use POST." }), {
        status: 405,
        headers: { ...corsHeaders, "Content-Type": "application/json" }
      });
    }

    try {
      // Extract the clean submission payload sent from your website frontend
      const payload = await request.json();
      const { quizId, sheetName: customSheetName, rowData } = payload;

      // Validate that we have row data AND at least one valid routing parameter
      if (!rowData || (!quizId && !customSheetName)) {
        return new Response(JSON.stringify({ error: "Missing required parameters (rowData and either quizId or sheetName) in payload." }), {
          status: 400,
          headers: { ...corsHeaders, "Content-Type": "application/json" }
        });
      }

      // MULTI-WORKBOOK ROUTING MATRIX
      const QUIZZES_SPREADSHEET_ID = "1L_kxk9RuutO29uDwjI1VLdxK3eLeHhmXCoxjSGIGohc";
      const WEBSITE_DATA_SPREADSHEET_ID = "1WpMB4uciEaNOl6P4g7TnBJozmuT-8QUtSdWuxms4qL0";

      let targetSpreadsheetId;
      let targetSheetName;

      // Route based on incoming payload configuration
      if (customSheetName) {
        // Event Registrations or Custom Tab Route -> Website Data Workbook
        targetSpreadsheetId = WEBSITE_DATA_SPREADSHEET_ID;
        targetSheetName = customSheetName;
      } else {
        // Standard Quiz Route -> Quizzes Workbook
        targetSpreadsheetId = QUIZZES_SPREADSHEET_ID;
        targetSheetName = `Results_${quizId}`;
      }

      // Retrieve encrypted environment variables from Cloudflare dashboard vault
      const clientEmail = env.GOOGLE_CLIENT_EMAIL;
      const privateKeyRaw = env.GOOGLE_PRIVATE_KEY;

      if (!clientEmail || !privateKeyRaw) {
        return new Response(JSON.stringify({ error: "System Error: Google API secrets missing from Worker vault." }), {
          status: 500,
          headers: { ...corsHeaders, "Content-Type": "application/json" }
        });
      }

      // Request a secure authorization token using Web Crypto functions
      const accessToken = await getGoogleOAuthToken(clientEmail, privateKeyRaw);

      // Handshake directly with Google Sheets API v4 to safely append the fresh row data
      const appendUrl = `https://sheets.googleapis.com/v4/spreadsheets/${targetSpreadsheetId}/values/${encodeURIComponent(targetSheetName)}!A:A:append?valueInputOption=USER_ENTERED`;
      
      const sheetsResponse = await fetch(appendUrl, {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${accessToken}`,
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          values: [rowData]
        })
      });

      const sheetsResult = await sheetsResponse.json();
      if (!sheetsResponse.ok) {
        return new Response(JSON.stringify({ error: "Google Sheets API write failed", details: sheetsResult }), {
          status: sheetsResponse.status,
          headers: { ...corsHeaders, "Content-Type": "application/json" }
        });
      }

      return new Response(JSON.stringify({ success: true, message: `Lead written securely to ${targetSheetName} ledger.` }), {
        status: 200,
        headers: { ...corsHeaders, "Content-Type": "application/json" }
      });

    } catch (err) {
      return new Response(JSON.stringify({ error: "Internal Gateway Fault", message: err.message }), {
        status: 500,
        headers: { ...corsHeaders, "Content-Type": "application/json" }
      });
    }
  }
};

// ====================================================================
// CRYPTOGRAPHIC WEB CRYPTO SERVICE HELPERS (STANDALONE SIGN-ENGINE)
// ====================================================================

function slugify(text) {
  return String(text || "")
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9\s-]/g, "")
    .replace(/[\s-]+/g, "-")
    .replace(/^-|-$/g, "");
}

function base64url(source) {
  const base64 = btoa(typeof source === "string" ? source : String.fromCharCode(...new Uint8Array(source)));
  return base64.replace(/=/g, "").replace(/\+/g, "-").replace(/\//g, "_");
}

async function getGoogleOAuthToken(clientEmail, privateKeyRaw) {
  const now = Math.floor(Date.now() / 1000);
  const expiry = now + 3600;

  const header = JSON.stringify({ alg: "RS256", typ: "JWT" });
  const claimSet = JSON.stringify({
    iss: clientEmail,
    scope: "https://www.googleapis.com/auth/spreadsheets",
    aud: "https://oauth2.googleapis.com/token",
    exp: expiry,
    iat: now
  });

  const encodedHeader = base64url(header);
  const encodedClaimSet = base64url(claimSet);
  const signatureInput = `${encodedHeader}.${encodedClaimSet}`;

  let cleanKey = privateKeyRaw.trim();
  if ((cleanKey.startsWith('"') && cleanKey.endsWith('"')) || (cleanKey.startsWith("'") && cleanKey.endsWith("'"))) {
    cleanKey = cleanKey.slice(1, -1);
  }

  const pemContents = cleanKey
    .replace(/-----BEGIN [A-Z ]+-----/g, "")
    .replace(/-----END [A-Z ]+-----/g, "")
    .replace(/\\n/g, "")
    .replace(/[\r\n\s"']/g, "");

  const binaryDerString = atob(pemContents);
  const binaryDer = new Uint8Array(binaryDerString.length);
  for (let i = 0; i < binaryDerString.length; i++) {
    binaryDer[i] = binaryDerString.charCodeAt(i);
  }

  const cryptoKey = await crypto.subtle.importKey(
    "pkcs8",
    binaryDer.buffer,
    { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
    false,
    ["sign"]
  );

  const signature = await crypto.subtle.sign(
    "RSASSA-PKCS1-v1_5",
    cryptoKey,
    new TextEncoder().encode(signatureInput)
  );

  const jwt = `${signatureInput}.${base64url(signature)}`;

  const tokenResponse = await fetch("https://oauth2.googleapis.com/token", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: `grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer&assertion=${jwt}`
  });

  const tokenData = await tokenResponse.json();
  if (!tokenResponse.ok) {
    throw new Error(`OAuth token claim rejected: ${tokenData.error_description || tokenData.error}`);
  }

  return tokenData.access_token;
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