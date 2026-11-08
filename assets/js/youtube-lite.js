class YouTubeLite extends HTMLElement {
    connectedCallback() {
        this.videoId = this.getAttribute('video-id');
        this.posterUrl = this.getAttribute('poster');
        this.label = this.getAttribute('label') || 'Play Video';

        const trigger = this.querySelector('.video-play-trigger');
        if (trigger) {
            trigger.addEventListener('click', (e) => {
                e.preventDefault();
                this.activate();
            }, { once: true });
        } else if (this.posterUrl) {
            this.innerHTML = `
                <button type="button" class="video-play-trigger" aria-label="${this.label}">
                    <img src="${this.posterUrl}" alt="${this.label}" class="video-poster-img" loading="lazy" width="860" height="484">
                    <span class="video-play-button" aria-hidden="true">
                        <svg viewBox="0 0 24 24" class="icon-play" fill="currentColor">
                            <polygon points="6 3 20 12 6 21 6 3"></polygon>
                        </svg>
                    </span>
                </button>
            `;
            this.querySelector('.video-play-trigger').addEventListener('click', (e) => {
                e.preventDefault();
                this.activate();
            }, { once: true });
        }
    }

    activate() {
        if (!this.videoId) return;
        const iframe = document.createElement('iframe');
        iframe.setAttribute('src', `https://www.youtube-nocookie.com/embed/${this.videoId}?autoplay=1&rel=0&playsinline=1`);
        iframe.setAttribute('title', this.label);
        iframe.setAttribute('frameborder', '0');
        iframe.setAttribute('allow', 'accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share');
        iframe.setAttribute('allowfullscreen', 'true');
        iframe.className = 'video-iframe';

        this.innerHTML = '';
        this.appendChild(iframe);
    }
}

if (!customElements.get('youtube-lite')) {
    customElements.define('youtube-lite', YouTubeLite);
}