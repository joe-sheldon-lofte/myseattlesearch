class QuizEngine extends HTMLElement {
    constructor() {
        super();
        this.quizData = null;
        this.currentStep = -1;
        this.leadInfo = { firstName: '', lastName: '', email: '', phone: '' };
        this.answers = [];
        this.currentSelection = null;
    }

    async connectedCallback() {
        const quizIdAttr = this.getAttribute('quiz-id');
        if (!quizIdAttr) {
            this.innerHTML = `<div class="surface-bento text-center"><p class="text-body">Engine Error: Attribute 'quiz-id' is required.</p></div>`;
            return;
        }
        
        try {
            const response = await fetch('/data/quizzes.json');
            const data = await response.json();
            this.quizData = data[quizIdAttr];
            
            if (!this.quizData) {
                this.innerHTML = `<div class="surface-bento text-center"><p class="text-body">Engine Error: Quiz ID ${quizIdAttr} not found.</p></div>`;
                return;
            }
            this.renderOnboarding();
        } catch (err) {
            console.error("Quiz Initialization Interrupted:", err);
            this.innerHTML = `<div class="surface-bento text-center"><p class="text-body">Failed to connect to local template cache.</p></div>`;
        }
    }

    renderOnboarding() {
        this.innerHTML = `
            <div class="surface-bento calc-strategy-card" style="max-width: 600px; margin: 0 auto;">
                <h2 class="text-widget-title text-center" style="font-size: 1.5rem;">${this.quizData.webTitle}</h2>
                <p class="text-body text-center" style="margin-bottom: 2rem;">${this.quizData.introText}</p>
                
                <form id="quiz-lead-form" style="display: flex; flex-direction: column; gap: 1.25rem;">
                    <div class="section-grid-static grid-cols-2">
                        <div class="calc-field-group">
                            <label class="calc-field-label">First Name *</label>
                            <input type="text" id="quiz-firstName" required style="width: 100%; padding: 0.75rem; border: 1px solid var(--color-surface-gray); border-radius: 8px;">
                        </div>
                        <div class="calc-field-group">
                            <label class="calc-field-label">Last Name *</label>
                            <input type="text" id="quiz-lastName" required style="width: 100%; padding: 0.75rem; border: 1px solid var(--color-surface-gray); border-radius: 8px;">
                        </div>
                    </div>
                    <div class="calc-field-group">
                        <label class="calc-field-label">Email Address *</label>
                        <input type="email" id="quiz-email" required style="width: 100%; padding: 0.75rem; border: 1px solid var(--color-surface-gray); border-radius: 8px;">
                    </div>
                    <div class="calc-field-group">
                        <label class="calc-field-label">Phone Number (Optional)</label>
                        <input type="tel" id="quiz-phone" style="width: 100%; padding: 0.75rem; border: 1px solid var(--color-surface-gray); border-radius: 8px;">
                    </div>
                    <button type="submit" class="btn btn-primary" style="margin-top: 1rem; width: 100%;">Start Assessment &rarr;</button>
                </form>
            </div>
        `;

        this.querySelector('#quiz-lead-form').addEventListener('submit', (e) => {
            e.preventDefault();
            this.leadInfo = {
                firstName: this.querySelector('#quiz-firstName').value.trim(),
                lastName: this.querySelector('#quiz-lastName').value.trim(),
                email: this.querySelector('#quiz-email').value.trim(),
                phone: this.querySelector('#quiz-phone').value.trim()
            };
            this.currentStep = 0;
            this.renderQuestion();
        });
    }

    renderQuestion() {
        if (this.currentStep >= this.quizData.questions.length) {
            this.processCalculationsAndSubmit();
            return;
        }

        if (this.quizData.scoringType === 'matrix_4quadrant') {
            this.renderMatrixTemplate();
        } else if (this.quizData.scoringType === 'score_tally') {
            this.renderTallyTemplate();
        }
    }

    renderMatrixTemplate() {
        const qObj = this.quizData.questions[this.currentStep];
        const pct = Math.round((this.currentStep / this.quizData.questions.length) * 100);
        this.currentSelection = this.answers[this.currentStep] || null;

        const btnsHtml = Array.from({length: 10}, (_, i) => i + 1).map(num => `
            <button type="button" class="btn ${this.currentSelection === num ? 'btn-primary' : 'btn-secondary'} q-btn" data-val="${num}" style="flex: 1; min-width: 35px; padding: 0.75rem 0;">${num}</button>
        `).join('');

        this.innerHTML = `
            <div class="surface-bento calc-strategy-card" style="max-width: 700px; margin: 0 auto;">
                <div style="width: 100%; background: var(--color-surface-gray); height: 6px; border-radius: 3px; margin-bottom: 2rem; overflow: hidden;">
                    <div style="width: ${pct}%; background: var(--color-text-primary, #111); height: 100%;"></div>
                </div>
                <div class="text-overline text-accent-alpine text-center">Statement ${this.currentStep + 1} of ${this.quizData.questions.length}</div>
                <h3 class="text-widget-title text-center" style="font-size: 1.35rem; margin-bottom: 2rem; line-height: 1.5;">"${qObj.text}"</h3>
                
                <div style="display: flex; gap: 0.5rem; justify-content: space-between; flex-wrap: wrap; margin-bottom: 0.5rem;">
                    ${btnsHtml}
                </div>
                <div style="display: flex; justify-content: space-between; width: 100%; margin-bottom: 2rem;">
                    <span class="text-overline text-accent-alpine">Completely Disagree</span>
                    <span class="text-overline text-accent-alpine">Completely Agree</span>
                </div>
                
                <div class="section-divider" style="margin: 1.5rem 0;"></div>
                <div style="display: flex; justify-content: space-between;">
                    <button type="button" id="q-back" class="btn btn-secondary" ${this.currentStep === 0 ? 'disabled' : ''}>&larr; Back</button>
                    <button type="button" id="q-next" class="btn btn-primary" ${this.currentSelection === null ? 'disabled' : ''}>Next &rarr;</button>
                </div>
            </div>`;

        this.bindNavEvents((btn) => this.currentSelection = parseInt(btn.getAttribute('data-val')));
    }

    renderTallyTemplate() {
        const qObj = this.quizData.questions[this.currentStep];
        const pct = Math.round((this.currentStep / this.quizData.questions.length) * 100);
        this.currentSelection = this.answers[this.currentStep] || null;

        const choices = qObj.bucket.split('|').map(c => c.trim());
        const btnsHtml = choices.map((choice, index) => {
            const pointsMatch = choice.match(/\[(\d+)\]/);
            const points = pointsMatch ? parseInt(pointsMatch[1]) : 0;
            const clearText = choice.replace(/\[\d+\]/, '').trim();
            const isActive = this.currentSelection && this.currentSelection.index === index;
            
            return `<button type="button" class="btn ${isActive ? 'btn-primary' : 'btn-secondary'} q-btn" data-index="${index}" data-points="${points}" data-text="${clearText}" style="text-align: left; padding: 1.25rem; width: 100%; white-space: normal; height: auto;">${clearText}</button>`;
        }).join('');

        this.innerHTML = `
            <div class="surface-bento calc-strategy-card" style="max-width: 650px; margin: 0 auto;">
                <div style="width: 100%; background: var(--color-surface-gray); height: 6px; border-radius: 3px; margin-bottom: 2rem; overflow: hidden;">
                    <div style="width: ${pct}%; background: var(--color-text-primary, #111); height: 100%;"></div>
                </div>
                <div class="text-overline text-accent-alpine text-center">Question ${this.currentStep + 1} of ${this.quizData.questions.length}</div>
                <h3 class="text-widget-title text-center" style="font-size: 1.35rem; margin-bottom: 2rem;">${qObj.text}</h3>
                
                <div style="display: flex; flex-direction: column; gap: 0.75rem; margin-bottom: 2rem;">
                    ${btnsHtml}
                </div>
                
                <div class="section-divider" style="margin: 1.5rem 0;"></div>
                <div style="display: flex; justify-content: space-between;">
                    <button type="button" id="q-back" class="btn btn-secondary" ${this.currentStep === 0 ? 'disabled' : ''}>&larr; Back</button>
                    <button type="button" id="q-next" class="btn btn-primary" ${this.currentSelection === null ? 'disabled' : ''}>Next &rarr;</button>
                </div>
            </div>`;

        this.bindNavEvents((btn) => {
            this.currentSelection = {
                index: parseInt(btn.getAttribute('data-index')),
                points: parseInt(btn.getAttribute('data-points')),
                text: btn.getAttribute('data-text')
            };
        });
    }

    bindNavEvents(selectionCallback) {
        this.querySelectorAll('.q-btn').forEach(b => b.addEventListener('click', () => {
            this.querySelectorAll('.q-btn').forEach(x => {
                x.classList.remove('btn-primary');
                x.classList.add('btn-secondary');
            });
            b.classList.remove('btn-secondary');
            b.classList.add('btn-primary');
            selectionCallback(b);
            this.querySelector('#q-next').removeAttribute('disabled');
        }));

        this.querySelector('#q-next').addEventListener('click', () => {
            this.answers[this.currentStep] = this.currentSelection;
            this.currentStep++;
            this.renderQuestion();
        });

        this.querySelector('#q-back').addEventListener('click', () => {
            this.currentStep--;
            this.renderQuestion();
        });
    }

    async processCalculationsAndSubmit() {
        this.innerHTML = `<div class="surface-bento text-center calc-strategy-card" style="max-width: 600px; margin: 0 auto;"><h3 class="text-widget-title">Securing Blueprint Configurations...</h3></div>`;
        
        let match;
        let matchedKey;

        // Algorithm 1: Matrix
        if (this.quizData.scoringType === 'matrix_4quadrant') {
            const tallies = { typeA: 0, typeB: 0, typeC: 0, typeD: 0, typeE: 0, typeF: 0 };
            this.quizData.questions.forEach((q, idx) => {
                const val = this.answers[idx] || 0;
                if (tallies[q.bucket] !== undefined) tallies[q.bucket] += val;
            });
            matchedKey = 'typeA';
            let maxVal = -1;
            for (const [k, v] of Object.entries(tallies)) {
                if (v > maxVal) { maxVal = v; matchedKey = k; }
            }
            match = this.quizData.routing.find(r => r.key === matchedKey) || this.quizData.routing[0];
        } 
        
        // Algorithm 2: Tally Bracket
        else if (this.quizData.scoringType === 'score_tally') {
            let grandTotal = 0;
            this.answers.forEach(ans => { grandTotal += (ans.points || 0); });
            match = this.quizData.routing[0];
            matchedKey = '0-0';
            for (const route of this.quizData.routing) {
                const ranges = route.key.split('-');
                if (grandTotal >= parseInt(ranges[0]) && grandTotal <= parseInt(ranges[1])) {
                    match = route;
                    matchedKey = route.key;
                    break;
                }
            }
        }

        const timestamp = new Date().toLocaleString("en-US", { timeZone: "America/Los_Angeles" });
        const combinedUserTags = this.quizData.userTags ? `${this.quizData.userTags}, ${matchedKey}` : matchedKey;
        const resultUrl = `https://myseattlesearch.com/realestate/quizzes/results/?quizId=${this.quizData.id}&result=${matchedKey}`;

        // Standardized 17-Column Inbound Ledger
        const rowData = [
            timestamp, "quiz", this.leadInfo.firstName || "", this.leadInfo.lastName || "", 
            this.leadInfo.email || "", this.leadInfo.phone || "", "", this.quizData.id || "", 
            match.heading || matchedKey, combinedUserTags, "", "", "", "", "", "", ""
        ];

        const payload = {
            quizId: this.quizData.id,
            sheetName: "Inbound",
            rowData: rowData,
            emailData: {
                to: this.leadInfo.email,
                subject: this.quizData.emailSubject || "Your Assessment Results",
                body: `Hi ${this.leadInfo.firstName},\n\nThank you for taking the ${this.quizData.name}!\n\nYour result is: ${match.heading}\n\nYou can view your full personalized playbook and results here:\n${resultUrl}\n\nTalk soon,\nJoe Sheldon`
            }
        };

        try {
            await fetch("https://myseattlesearch-quiz-gateway.joe-54b.workers.dev/", { 
                method: 'POST', 
                headers: { 'Content-Type': 'application/json' }, 
                body: JSON.stringify(payload) 
            });
        } catch (e) {
            console.error("Gateway Bypass Active", e);
        }

        setTimeout(() => {
            window.location.href = `/realestate/quizzes/results/?quizId=${this.quizData.id}&result=${matchedKey}`;
        }, 600);
    }
}
customElements.define('quiz-engine', QuizEngine);