// Main JavaScript for Purposefully Made KC

// Flash message auto-close
document.addEventListener('DOMContentLoaded', function() {
    const flashMessages = document.querySelectorAll('.flash-message');
    
    flashMessages.forEach(function(message) {
        // Auto close after 5 seconds
        setTimeout(function() {
            message.style.animation = 'slideUp 0.3s ease';
            setTimeout(function() {
                message.remove();
            }, 300);
        }, 5000);
        
        // Close button
        const closeBtn = message.querySelector('.flash-close');
        if (closeBtn) {
            closeBtn.addEventListener('click', function() {
                message.style.animation = 'slideUp 0.3s ease';
                setTimeout(function() {
                    message.remove();
                }, 300);
            });
        }
    });
});

// Mobile menu toggle
const mobileMenuToggle = document.getElementById('mobileMenuToggle');
if (mobileMenuToggle) {
    mobileMenuToggle.addEventListener('click', function() {
        const navLinks = document.querySelector('.nav-links');
        navLinks.classList.toggle('active');
    });
}

// Smooth scroll for anchor links
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function (e) {
        const href = this.getAttribute('href');
        if (href !== '#' && href !== '') {
            e.preventDefault();
            const target = document.querySelector(href);
            if (target) {
                target.scrollIntoView({
                    behavior: 'smooth',
                    block: 'start'
                });
            }
        }
    });
});

// Add slideUp animation
const style = document.createElement('style');
style.textContent = `
    @keyframes slideUp {
        from {
            opacity: 1;
            transform: translateY(0);
        }
        to {
            opacity: 0;
            transform: translateY(-20px);
        }
    }
`;
document.head.appendChild(style);

// Helper function for API calls
async function apiRequest(url, options = {}) {
    try {
        const response = await fetch(url, {
            headers: {
                'Content-Type': 'application/json',
                ...options.headers
            },
            ...options
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Request failed');
        }
        
        return await response.json();
    } catch (error) {
        console.error('API Error:', error);
        throw error;
    }
}

// Show flash message programmatically
function showFlash(message, category = 'info') {
    const flashContainer = document.querySelector('.flash-messages') || createFlashContainer();
    
    const flashDiv = document.createElement('div');
    flashDiv.className = `flash-message flash-${category}`;
    flashDiv.innerHTML = `
        <div class="container">
            <span>${message}</span>
            <button class="flash-close">&times;</button>
        </div>
    `;
    
    flashContainer.appendChild(flashDiv);
    
    // Auto close
    setTimeout(() => {
        flashDiv.style.animation = 'slideUp 0.3s ease';
        setTimeout(() => flashDiv.remove(), 300);
    }, 5000);
    
    // Close button
    flashDiv.querySelector('.flash-close').addEventListener('click', () => {
        flashDiv.style.animation = 'slideUp 0.3s ease';
        setTimeout(() => flashDiv.remove(), 300);
    });
}

function createFlashContainer() {
    const container = document.createElement('div');
    container.className = 'flash-messages';
    document.body.appendChild(container);
    return container;
}

// Export for use in other scripts (PMKC = Purposefully Made KC)
window.PMKC = {
    apiRequest,
    showFlash
};
