class LocalReviews extends HTMLElement {
    async connectedCallback() {
        const limit = parseInt(this.getAttribute('limit')) || 3;
        
        let pageName = window.location.pathname.split('/').pop().toLowerCase().trim();
        if (!pageName || pageName === "") pageName = "index.html";

        this.innerHTML = `<div class="reviews-loading text-body-secondary">Loading reviews...</div>`;

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
                        fullText: rev['full review'] || rev['Full Review'] || rev['fullText'] || ''
                    });
                }
            }

            if (validReviews.length === 0) {
                this.innerHTML = '';
                return;
            }

            // Random Fisher-Yates shuffle
            for (let i = validReviews.length - 1; i > 0; i--) {
                const j = Math.floor(Math.random() * (i + 1));
                [validReviews[i], validReviews[j]] = [validReviews[j], validReviews[i]];
            }

            const selectedReviews = validReviews.slice(0, limit);

            this.innerHTML = `
                <div class="reviews-stack">
                    ${selectedReviews.map(rev => `
                        <article class="review-item">
                            <div class="review-rating text-amber tabular-nums" aria-label="${rev.rating} out of 5 stars">
                                ${'★'.repeat(rev.rating)}${'☆'.repeat(5 - rev.rating)}
                            </div>
                            <blockquote class="review-quote text-body">"${rev.fullText}"</blockquote>
                            <cite class="review-author text-overline">— ${rev.reviewer}</cite>
                        </article>
                    `).join('')}
                </div>
            `;

        } catch (error) {
            console.error('Contextual reviews execution error:', error);
            this.innerHTML = '';
        }
    }
}

if (!customElements.get('local-reviews')) {
    customElements.define('local-reviews', LocalReviews);
}