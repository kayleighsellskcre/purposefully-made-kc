// Product Customizer JavaScript

class ProductCustomizer {
    constructor(config) {
        this.productId = config.productId;
        this.basePrice = config.basePrice;
        this.printAreaConfig = config.printAreaConfig || {};
        
        this.selectedColor = null;
        this.selectedSize = null;
        this.selectedPlacement = null;
        this.uploadedDesignId = null;
        this.quantity = 1;
        this.currentView = 'front';
        
        this.initializeElements();
        this.attachEventListeners();
    }
    
    initializeElements() {
        this.colorGrid = document.getElementById('colorGrid');
        this.sizeGrid = document.getElementById('sizeGrid');
        this.placementGrid = document.getElementById('placementGrid');
        this.uploadArea = document.getElementById('uploadArea');
        this.designFile = document.getElementById('designFile');
        this.designPreview = document.getElementById('designPreview');
        this.designLayer = document.getElementById('designLayer');
        this.quantityInput = document.getElementById('quantity');
        this.addToCartBtn = document.getElementById('addToCart');
        this.placementSection = document.getElementById('placementSection');
    }
    
    attachEventListeners() {
        // Color selection
        this.colorGrid.addEventListener('click', (e) => {
            const colorOption = e.target.closest('.color-option');
            if (colorOption) {
                this.selectColor(colorOption.dataset.color);
            }
        });
        
        // Size selection
        this.sizeGrid.addEventListener('click', (e) => {
            const sizeOption = e.target.closest('.size-option');
            if (sizeOption) {
                this.selectSize(sizeOption.dataset.size);
            }
        });
        
        // Placement selection
        this.placementGrid.addEventListener('click', (e) => {
            const placementOption = e.target.closest('.placement-option');
            if (placementOption) {
                this.selectPlacement(placementOption.dataset.placement);
            }
        });
        
        // File upload
        this.uploadArea.addEventListener('click', () => {
            this.designFile.click();
        });
        
        this.designFile.addEventListener('change', (e) => {
            if (e.target.files.length > 0) {
                this.uploadDesign(e.target.files[0]);
            }
        });
        
        // Drag and drop
        this.uploadArea.addEventListener('dragover', (e) => {
            e.preventDefault();
            this.uploadArea.classList.add('dragover');
        });
        
        this.uploadArea.addEventListener('dragleave', () => {
            this.uploadArea.classList.remove('dragover');
        });
        
        this.uploadArea.addEventListener('drop', (e) => {
            e.preventDefault();
            this.uploadArea.classList.remove('dragover');
            if (e.dataTransfer.files.length > 0) {
                this.uploadDesign(e.dataTransfer.files[0]);
            }
        });
        
        // Quantity
        this.quantityInput.addEventListener('input', () => {
            this.quantity = parseInt(this.quantityInput.value) || 1;
            this.updatePrice();
        });
        
        // Add to cart
        this.addToCartBtn.addEventListener('click', () => {
            this.addToCart();
        });
        
        // View toggle
        document.getElementById('viewFront').addEventListener('click', () => {
            this.switchView('front');
        });
        
        document.getElementById('viewBack').addEventListener('click', () => {
            this.switchView('back');
        });
        
        // Remove design
        const removeDesignBtn = document.getElementById('removeDesign');
        if (removeDesignBtn) {
            removeDesignBtn.addEventListener('click', () => {
                this.removeDesign();
            });
        }
    }
    
    selectColor(color) {
        this.selectedColor = color;
        
        // Update UI
        document.querySelectorAll('.color-option').forEach(opt => {
            opt.classList.remove('selected');
        });
        document.querySelector(`[data-color="${color}"]`).classList.add('selected');
        
        // Update mockup (if mockup images available)
        this.updateMockup();
    }
    
    selectSize(size) {
        this.selectedSize = size;
        
        // Update UI
        document.querySelectorAll('.size-option').forEach(opt => {
            opt.classList.remove('selected');
        });
        document.querySelector(`[data-size="${size}"]`).classList.add('selected');
    }
    
    selectPlacement(placement) {
        this.selectedPlacement = placement;
        
        // Update UI
        document.querySelectorAll('.placement-option').forEach(opt => {
            opt.classList.remove('selected');
        });
        document.querySelector(`[data-placement="${placement}"]`).classList.add('selected');
        
        // Update design position
        this.updateDesignPosition();
    }
    
    async uploadDesign(file) {
        // Show loading
        this.uploadArea.innerHTML = '<p>Uploading...</p>';
        
        const formData = new FormData();
        formData.append('file', file);
        
        try {
            const response = await fetch('/api/upload-design', {
                method: 'POST',
                body: formData
            });
            
            const data = await response.json();
            
            if (data.success) {
                this.uploadedDesignId = data.design.id;
                
                // Show preview
                const previewImg = document.getElementById('designPreviewImage');
                previewImg.src = `/static/${data.design.file_path}`;
                this.designPreview.classList.add('active');
                
                // Show design on mockup
                const designImg = document.getElementById('designImage');
                designImg.src = `/static/${data.design.file_path}`;
                this.designLayer.style.display = 'block';
                
                // Show placement section
                this.placementSection.style.display = 'block';
                
                // Show warnings if any
                if (data.warnings && data.warnings.length > 0) {
                    this.showWarnings(data.warnings);
                }
                
                // Reset upload area
                this.uploadArea.innerHTML = `
                    <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin: 0 auto 1rem;">
                        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                        <polyline points="17 8 12 3 7 8"></polyline>
                        <line x1="12" y1="3" x2="12" y2="15"></line>
                    </svg>
                    <p><strong>Click to upload</strong> or drag and drop</p>
                    <p class="text-muted">PNG, JPG, SVG or PDF (Max 16MB)</p>
                `;
                
                PMKC.showFlash('Design uploaded successfully!', 'success');
            } else {
                throw new Error(data.error || 'Upload failed');
            }
        } catch (error) {
            PMKC.showFlash(error.message, 'error');
            // Reset upload area
            this.uploadArea.innerHTML = `
                <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin: 0 auto 1rem;">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                    <polyline points="17 8 12 3 7 8"></polyline>
                    <line x1="12" y1="3" x2="12" y2="15"></line>
                </svg>
                <p><strong>Click to upload</strong> or drag and drop</p>
                <p class="text-muted">PNG, JPG, SVG or PDF (Max 16MB)</p>
            `;
        }
    }
    
    removeDesign() {
        this.uploadedDesignId = null;
        this.selectedPlacement = null;
        this.designPreview.classList.remove('active');
        this.designLayer.style.display = 'none';
        this.placementSection.style.display = 'none';
        document.getElementById('designWarnings').innerHTML = '';
    }
    
    showWarnings(warnings) {
        const warningsContainer = document.getElementById('designWarnings');
        warningsContainer.innerHTML = warnings.map(warning => `
            <div class="warning-item">${warning}</div>
        `).join('');
    }
    
    updateMockup() {
        // Update mockup image based on color and view
        // This would load different mockup images for different colors
        // For MVP, we can use a placeholder or single mockup
    }
    
    updateDesignPosition() {
        // Update design position based on placement
        const positions = {
            'center_chest': { top: '30%', left: '50%', width: '40%', transform: 'translate(-50%, -50%)' },
            'left_chest': { top: '25%', left: '25%', width: '20%', transform: 'translate(-50%, -50%)' },
            'full_front': { top: '50%', left: '50%', width: '70%', transform: 'translate(-50%, -50%)' },
            'full_back': { top: '50%', left: '50%', width: '70%', transform: 'translate(-50%, -50%)' }
        };
        
        const position = positions[this.selectedPlacement] || positions['center_chest'];
        Object.assign(this.designLayer.style, position);
    }
    
    switchView(view) {
        this.currentView = view;
        // Update mockup image for front/back view
        // For MVP, just highlight the active button
        document.querySelectorAll('.preview-controls button').forEach(btn => {
            btn.classList.remove('active');
        });
        document.getElementById(view === 'front' ? 'viewFront' : 'viewBack').classList.add('active');
    }
    
    updatePrice() {
        const total = this.basePrice * this.quantity;
        document.getElementById('quantityDisplay').textContent = this.quantity;
        document.getElementById('totalPrice').textContent = `$${total.toFixed(2)}`;
    }
    
    async addToCart() {
        // Validate
        if (!this.selectedColor) {
            PMKC.showFlash('Please select a color', 'error');
            return;
        }
        
        if (!this.selectedSize) {
            PMKC.showFlash('Please select a size', 'error');
            return;
        }
        
        if (!this.uploadedDesignId) {
            PMKC.showFlash('Please upload a design', 'error');
            return;
        }
        
        if (!this.selectedPlacement) {
            PMKC.showFlash('Please select a placement', 'error');
            return;
        }
        
        // Add to cart
        try {
            const response = await fetch('/cart/add', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    product_id: this.productId,
                    size: this.selectedSize,
                    color: this.selectedColor,
                    quantity: this.quantity,
                    design_id: this.uploadedDesignId,
                    placement: this.selectedPlacement,
                    print_specs: {
                        // These would be calculated from the actual position
                        width: 12,
                        height: 12,
                        x: 0.5,
                        y: 0.3
                    }
                })
            });
            
            const data = await response.json();
            
            if (data.success) {
                PMKC.showFlash('Added to cart!', 'success');
                
                // Update cart count
                const cartCount = document.querySelector('.cart-count');
                if (cartCount) {
                    cartCount.textContent = data.cart_count;
                } else if (data.cart_count > 0) {
                    // Create cart count badge
                    const badge = document.createElement('span');
                    badge.className = 'cart-count';
                    badge.textContent = data.cart_count;
                    document.querySelector('.cart-link').appendChild(badge);
                }
                
                // Redirect to cart after a short delay
                setTimeout(() => {
                    window.location.href = '/cart';
                }, 1500);
            } else {
                throw new Error(data.error || 'Failed to add to cart');
            }
        } catch (error) {
            PMKC.showFlash(error.message, 'error');
        }
    }
}
