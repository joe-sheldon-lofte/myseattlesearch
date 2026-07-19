class QuizEngine extends HTMLElement {
  constructor() {
    super();
    this.quizId = null;
    this.quizConfig = null;
    this.currentQuestionIndex = 0;
    this.userScores = {};
    this.userData = { firstName: "", lastName: "", email: "" };
  }

  async connectedCallback() {
    this.quizId = this.getAttribute("quiz-id");
    if (!this.quizId) {
      this.renderError("Missing target Quiz Identification attribute reference.");
      return;
    }

    this.style.display = "block";
    this.style.maxWidth = "650px";
    this.style.margin = "2rem auto";
    this.style.padding = "0 1.5rem";
    this.style.boxSizing = "border-box";

    await this.fetchQuizConfiguration();
  }

  async fetchQuizConfiguration() {
    try {
      this.innerHTML = `<p style="text-align:center; color: var(--premier-charcoal); opacity:0.7; font-weight:bold;">Pulling latest strategy parameters...</p>`;
      const response = await fetch("/data/quizzes.json");
      if (!response.ok) throw new Error("Could not load internal static data payload asset.");
      const db = await response.json();
      
      this.quizConfig = db[this.quizId];
      if (!this.quizConfig) {
        this.renderError("Requested assessment sequence is currently inactive or missing.");
        return;
      }

      this.initializeScoringMatrix();
      this.renderCurrentState();
    } catch (err) {
      this.renderError(`Configuration load exception: ${err.message}`);
    }
  }

  initializeScoringMatrix() {
    if (this.quizConfig.questions) {
      this.quizConfig.questions.forEach(q => {
        if (q.bucket && !this.userScores[q.bucket]) {
          this.userScores[q.bucket] = 0;
        }
      });
    }
  }

  renderCurrentState() {
    if (this.currentQuestionIndex < this.quizConfig.questions.length) {
      this.renderQuestionCard();
    } else {
      this.renderLeadGenerationForm();
    }
  }

  renderQuestionCard() {
    const question = this.quizConfig.questions[this.currentQuestionIndex];
    const totalQuestions = this.quizConfig.questions.length;
    const progressPercent = Math.round((this.currentQuestionIndex / totalQuestions) * 100);

    this.innerHTML = `
      <div style="background: white; border: 1px solid var(--premier-beige); border-top: 6px solid var(--card-accent-color); border-radius: 12px; padding: 2.5rem; box-shadow: 0 4px 15px rgba(0,0,0,0.03);">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1.5rem;">
          <span style="font-size: 0.8rem; font-weight: 800; color: var(--card-accent-color); text-transform: uppercase; letter-spacing: 1px;">Question ${this.currentQuestionIndex + 1} of ${totalQuestions}</span>
          <span style="font-size: 0.85rem; color: var(--premier-charcoal); opacity: 0.6; font-weight: bold;">${progressPercent}% Complete</span>
        </div>
        
        <div style="width: 100%; height: 6px; background: var(--dynamic-bg-highlight); border-radius: 3px; margin-bottom: 2rem; overflow: hidden;">
          <div style="width: ${progressPercent}%; height: 100%; background: var(--card-accent-color); transition: width 0.3s ease;"></div>
        </div>

        <h2 style="font-size: 1.45rem; line-height: 1.45; font-weight: 700; color: var(--premier-charcoal); margin: 0 0 2.5rem 0;">${question.text}</h2>
        
        <div style="display: flex; flex-direction: column; gap: 1rem;">
          <button id="btn-agree" class="btn btn-primary" style="padding: 1.15rem; font-weight: bold; font-size: 1.05rem; background-color: var(--card-accent-color); border-color: var(--card-accent-color); color: white; border-radius: 6px; cursor: pointer; text-align: center;">Yes, That Matches Me Perfectly</button>
          <button id="btn-disagree" class="btn btn-secondary" style="padding: 1.15rem; font-weight: bold; font-size: 1.05rem; background-color: var(--premier-charcoal); border-color: var(--premier-charcoal); color: white; border-radius: 6px; cursor: pointer; text-align: center;">No, That Doesn't Sound Like Me</button>
        </div>
      </div>
    `;

    this.querySelector("#btn-agree").addEventListener("click", () => this.handleAnswerSelection(true, question.bucket));
    this.querySelector("#btn-disagree").addEventListener("click", () => this.handleAnswerSelection(false, question.bucket));
  }

  handleAnswerSelection(isAffirmative, bucket) {
    if (isAffirmative && bucket) {
      this.userScores[bucket] = (this.userScores[bucket] || 0) + 1;
    }
    this.currentQuestionIndex++;
    this.renderCurrentState();
  }

  renderLeadGenerationForm() {
    const required = this.quizConfig.requiredFields || "firstName,email";
    const showLastName = required.includes("lastName");

    this.innerHTML = `
      <div style="background: white; border: 1px solid var(--premier-beige); border-top: 6px solid var(--card-accent-color); border-radius: 12px; padding: 2.5rem; box-shadow: 0 4px 15px rgba(0,0,0,0.03);">
        <h2 style="font-size: 1.6rem; font-weight: 800; color: var(--premier-charcoal); margin: 0 0 0.5rem 0;">Assessment Complete!</h2>
        <p style="color: var(--premier-charcoal); opacity: 0.8; font-size: 1rem; line-height: 1.5; margin: 0 0 2rem 0;">Enter your information below to calculate your dominant profile archetype and unlock your personalized home strategy playbook mapping indicators.</p>
        
        <form id="lead-form" style="display: flex; flex-direction: column; gap: 1.25rem;">
          <div style="display: flex; flex-direction: column; gap: 0.4rem;">
            <label style="font-size: 0.85rem; font-weight: bold; color: var(--premier-charcoal);">First Name</label>
            <input type="text" id="input-fname" required style="padding: 0.85rem; border: 1px solid var(--premier-beige); border-radius: 4px; font-size: 1rem; font-family: inherit; width: 100%; box-sizing: border-box;">
          </div>

          ${showLastName ? `
          <div style="display: flex; flex-direction: column; gap: 0.4rem;">
            <label style="font-size: 0.85rem; font-weight: bold; color: var(--premier-charcoal);">Last Name</label>
            <input type="text" id="input-lname" required style="padding: 0.85rem; border: 1px solid var(--premier-beige); border-radius: 4px; font-size: 1rem; font-family: inherit; width: 100%; box-sizing: border-box;">
          </div>
          ` : ''}

          <div style="display: flex; flex-direction: column; gap: 0.4rem;">
            <label style="font-size: 0.85rem; font-weight: bold; color: var(--premier-charcoal);">Email Address</label>
            <input type="email" id="input-email" required style="padding: 0.85rem; border: 1px solid var(--premier-beige); border-radius: 4px; font-size: 1rem; font-family: inherit; width: 100%; box-sizing: border-box;">
          </div>

          <button type="submit" id="submit-lead" class="btn btn-primary" style="padding: 1.15rem; font-weight: bold; font-size: 1.1rem; background-color: var(--card-accent-color); border-color: var(--card-accent-color); color: white; border-radius: 6px; cursor: pointer; border: none; margin-top: 1rem; width: 100%; box-sizing: border-box;">Unlock My Real Estate Strategy &rarr;</button>
        </form>
      </div>
    `;

    this.querySelector("#lead-form").addEventListener("submit", (e) => this.handleLeadSubmission(e, showLastName));
  }

  async handleLeadSubmission(e, containsLastName) {
    e.preventDefault();
    
    const submitBtn = this.querySelector("#submit-lead");
    submitBtn.disabled = true;
    submitBtn.textContent = "Processing Secure Calculation Engine...";

    this.userData.firstName = this.querySelector("#input-fname").value.trim();
    this.userData.lastName = containsLastName ? this.querySelector("#input-lname").value.trim() : "";
    this.userData.email = this.querySelector("#input-email").value.trim();

    let dominantBucket = "typeA";
    let maximumScore = -1;

    for (const [bucket, score] of Object.entries(this.userScores)) {
      if (score > maximumScore) {
        maximumScore = score;
        dominantBucket = bucket;
      }
    }

    // Your completely buttoned-up live Cloudflare edge endpoint address
    const workerGatewayUrl = "https://myseattlesearch-quiz-gateway.joe-54b.workers.dev/"; 

    const timestamp = new Date().toLocaleString("en-US", { timeZone: "America/Los_Angeles" });
    const formattedRow = [
      timestamp,
      this.quizConfig.id,
      this.quizConfig.name,
      this.userData.firstName,
      this.userData.lastName,
      this.userData.email,
      dominantBucket,
      JSON.stringify(this.userScores)
    ];

    try {
      const response = await fetch(workerGatewayUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          quizId: this.quizConfig.id, // Only send the plain numerical quiz id to the cloud
          rowData: formattedRow
        })
      });

      if (!response.ok) throw new Error("Server edge connection rejected parameters.");
      this.executeUIRedirection(dominantBucket);

    } catch (err) {
      console.error("🔒 Gateway Bypass Active: Safe network protection fallback routing enabled.", err);
      this.executeUIRedirection(dominantBucket);
    }
  }

  executeUIRedirection(resultKey) {
    const fullName = `${this.userData.firstName} ${this.userData.lastName}`.trim();
    window.location.href = `/quizzes/results/?quizId=${this.quizId}&result=${resultKey}&name=${encodeURIComponent(fullName)}`;
  }

  renderError(msg) {
    this.innerHTML = `
      <div style="background: var(--dynamic-bg-highlight); border: 1px solid var(--premier-beige); border-top: 5px solid var(--card-accent-color); border-radius: 8px; padding: 2rem; text-align: center;">
        <p style="color: var(--card-accent-color); font-weight: bold; margin: 0;">📘 Coach's Playbook Note: ${msg}</p>
        <a href="/quizzes/" style="display: inline-block; margin-top: 1rem; color: var(--premier-charcoal); font-weight: bold; text-decoration: none; font-size: 0.9rem;">&larr; Return to Catalog Hub</a>
      </div>
    `;
  }
}

customElements.define("quiz-engine", QuizEngine);