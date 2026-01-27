/**
 * TWF Models Map Viewer
 * Enhanced with dropdown selectors, animation slider, and image preloading
 */

class MapViewer {
    constructor() {
        this.apiClient = new APIClient(CONFIG.API_BASE_URL);
        this.currentVariable = 'temp';
        this.currentForecastHour = 0;
        this.currentMap = null;
        this.isLoading = false;
        this.isAnimating = false;
        this.animationSpeed = 2; // frames per second
        this.animationInterval = null;
        this.imageCache = new Map(); // Cache for preloaded images
        this.availableVariables = new Set();
        this.availableForecastHours = [];
    }

    /**
     * Initialize the map viewer
     */
    async init() {
        await this.fetchAvailableOptions();
        this.populateVariableDropdown();
        this.populateForecastDropdown();
        this.setupEventListeners();
        await this.loadMap();
        this.preloadImages();
        
        // Auto-refresh every minute to check for new maps
        setInterval(() => this.loadMap(), CONFIG.REFRESH_INTERVAL);
        
        // Refresh available options every 5 minutes
        setInterval(() => {
            this.fetchAvailableOptions();
            this.populateVariableDropdown();
            this.populateForecastDropdown();
        }, 300000); // 5 minutes
    }

    /**
     * Fetch available variables and forecast hours from API
     */
    async fetchAvailableOptions() {
        try {
            const maps = await this.apiClient.getMaps();
            
            console.log('Fetched maps from API:', maps.length);
            
            // Extract unique variables and forecast hours from API response
            const variablesFromAPI = new Set();
            const forecastHoursSet = new Set();
            
            maps.forEach(map => {
                variablesFromAPI.add(map.variable);
                forecastHoursSet.add(map.forecast_hour);
            });
            
            // If API returned data, use it
            if (variablesFromAPI.size > 0) {
                this.availableVariables = variablesFromAPI;
                this.availableForecastHours = Array.from(forecastHoursSet).sort((a, b) => a - b);
                console.log('Using API data:', Array.from(this.availableVariables), this.availableForecastHours);
            } else {
                // No maps from API, use config fallback
                console.log('No maps from API, using config fallback');
                this.availableVariables = new Set(Object.keys(CONFIG.VARIABLES));
                this.availableForecastHours = CONFIG.FORECAST_HOURS;
            }
            
            // If current selections are no longer available, reset to defaults
            if (!this.availableVariables.has(this.currentVariable)) {
                this.currentVariable = this.availableVariables.has('temp') ? 'temp' : Array.from(this.availableVariables)[0];
            }
            
            if (!this.availableForecastHours.includes(this.currentForecastHour)) {
                this.currentForecastHour = this.availableForecastHours[0] || 0;
            }
        } catch (error) {
            console.error('Failed to fetch available options:', error);
            // Fallback to config values
            this.availableVariables = new Set(Object.keys(CONFIG.VARIABLES));
            this.availableForecastHours = CONFIG.FORECAST_HOURS;
            console.log('Using config fallback due to error:', Array.from(this.availableVariables), this.availableForecastHours);
        }
    }

    /**
     * Populate variable dropdown
     */
    populateVariableDropdown() {
        const select = document.getElementById('variable-select');
        if (!select) {
            console.error('Variable select element not found!');
            return;
        }
        
        console.log('Populating variables:', Array.from(this.availableVariables));
        
        // Clear existing options
        select.innerHTML = '';
        
        // Add available variables
        const variables = Array.from(this.availableVariables).sort((a, b) => {
            const labelA = CONFIG.VARIABLES[a]?.label || a;
            const labelB = CONFIG.VARIABLES[b]?.label || b;
            return labelA.localeCompare(labelB);
        });
        
        variables.forEach(variable => {
            const option = document.createElement('option');
            option.value = variable;
            option.textContent = CONFIG.VARIABLES[variable]?.label || this.formatVariableName(variable);
            
            if (variable === this.currentVariable) {
                option.selected = true;
            }
            
            select.appendChild(option);
        });
        
        console.log('Variable dropdown populated with', variables.length, 'options');
    }

    /**
     * Populate forecast hour dropdown
     */
    populateForecastDropdown() {
        const select = document.getElementById('forecast-select');
        if (!select) {
            console.error('Forecast select element not found!');
            return;
        }
        
        console.log('Populating forecast hours:', this.availableForecastHours);
        
        // Clear existing options
        select.innerHTML = '';
        
        // Add available forecast hours
        this.availableForecastHours.forEach(hour => {
            const option = document.createElement('option');
            option.value = hour;
            option.textContent = hour === 0 ? 'Now (Analysis)' : `+${hour}h`;
            
            if (hour === this.currentForecastHour) {
                option.selected = true;
            }
            
            select.appendChild(option);
        });
        
        console.log('Forecast dropdown populated with', this.availableForecastHours.length, 'options');
        
        // Update slider
        this.updateTimeSlider();
    }

    /**
     * Update time slider range and labels
     */
    updateTimeSlider() {
        const slider = document.getElementById('time-slider');
        const maxLabel = document.getElementById('slider-max-label');
        
        if (!slider || this.availableForecastHours.length === 0) return;
        
        slider.min = 0;
        slider.max = this.availableForecastHours.length - 1;
        slider.value = this.availableForecastHours.indexOf(this.currentForecastHour);
        
        // Update max label
        const maxHour = this.availableForecastHours[this.availableForecastHours.length - 1];
        if (maxLabel) {
            maxLabel.textContent = `+${maxHour}h`;
        }
        
        this.updateSliderLabel();
    }

    /**
     * Update slider current label
     */
    updateSliderLabel() {
        const label = document.getElementById('slider-current-label');
        if (!label) return;
        
        const hour = this.currentForecastHour;
        label.textContent = hour === 0 ? 'Now' : `+${hour}h`;
    }

    /**
     * Format variable name for display
     */
    formatVariableName(variable) {
        return variable
            .split('_')
            .map(word => word.charAt(0).toUpperCase() + word.slice(1))
            .join(' ');
    }

    /**
     * Setup event listeners for UI controls
     */
    setupEventListeners() {
        // Variable selector
        const variableSelect = document.getElementById('variable-select');
        if (variableSelect) {
            variableSelect.addEventListener('change', (e) => {
                this.selectVariable(e.target.value);
            });
        }

        // Forecast hour selector
        const forecastSelect = document.getElementById('forecast-select');
        if (forecastSelect) {
            forecastSelect.addEventListener('change', (e) => {
                this.selectForecastHour(parseInt(e.target.value));
            });
        }

        // Time slider
        const timeSlider = document.getElementById('time-slider');
        if (timeSlider) {
            timeSlider.addEventListener('input', (e) => {
                const index = parseInt(e.target.value);
                const hour = this.availableForecastHours[index];
                this.selectForecastHour(hour, false); // Don't update slider to avoid recursion
                this.updateSliderLabel();
            });
        }

        // Animation controls
        const playBtn = document.getElementById('play-btn');
        const pauseBtn = document.getElementById('pause-btn');
        
        if (playBtn) {
            playBtn.addEventListener('click', () => this.startAnimation());
        }
        
        if (pauseBtn) {
            pauseBtn.addEventListener('click', () => this.stopAnimation());
        }

        // Speed slider
        const speedSlider = document.getElementById('speed-slider');
        const speedValue = document.getElementById('speed-value');
        
        if (speedSlider) {
            speedSlider.addEventListener('input', (e) => {
                this.animationSpeed = parseFloat(e.target.value);
                if (speedValue) {
                    speedValue.textContent = this.animationSpeed.toFixed(1);
                }
                
                // If animating, restart with new speed
                if (this.isAnimating) {
                    this.stopAnimation();
                    this.startAnimation();
                }
            });
        }
    }

    /**
     * Select a variable
     */
    selectVariable(variable) {
        if (this.currentVariable === variable) return;
        
        this.currentVariable = variable;
        
        // Update dropdown
        const select = document.getElementById('variable-select');
        if (select) {
            select.value = variable;
        }
        
        // Stop animation if running
        this.stopAnimation();
        
        // Clear cache and load new map
        this.imageCache.clear();
        this.loadMap();
        this.preloadImages();
    }

    /**
     * Select a forecast hour
     */
    selectForecastHour(hour, updateSlider = true) {
        if (this.currentForecastHour === hour) return;
        
        this.currentForecastHour = hour;
        
        // Update dropdown
        const select = document.getElementById('forecast-select');
        if (select) {
            select.value = hour;
        }
        
        // Update slider if requested
        if (updateSlider) {
            const slider = document.getElementById('time-slider');
            if (slider) {
                slider.value = this.availableForecastHours.indexOf(hour);
                this.updateSliderLabel();
            }
        }
        
        // Load new map
        this.loadMap();
    }

    /**
     * Start animation
     */
    startAnimation() {
        if (this.isAnimating || this.availableForecastHours.length <= 1) return;
        
        this.isAnimating = true;
        
        // Update button visibility
        const playBtn = document.getElementById('play-btn');
        const pauseBtn = document.getElementById('pause-btn');
        if (playBtn) playBtn.style.display = 'none';
        if (pauseBtn) pauseBtn.style.display = 'flex';
        
        // Start animation loop
        const intervalMs = 1000 / this.animationSpeed;
        this.animationInterval = setInterval(() => {
            this.advanceFrame();
        }, intervalMs);
    }

    /**
     * Stop animation
     */
    stopAnimation() {
        if (!this.isAnimating) return;
        
        this.isAnimating = false;
        
        // Clear interval
        if (this.animationInterval) {
            clearInterval(this.animationInterval);
            this.animationInterval = null;
        }
        
        // Update button visibility
        const playBtn = document.getElementById('play-btn');
        const pauseBtn = document.getElementById('pause-btn');
        if (playBtn) playBtn.style.display = 'flex';
        if (pauseBtn) pauseBtn.style.display = 'none';
    }

    /**
     * Advance to next frame in animation
     */
    advanceFrame() {
        const currentIndex = this.availableForecastHours.indexOf(this.currentForecastHour);
        const nextIndex = (currentIndex + 1) % this.availableForecastHours.length;
        const nextHour = this.availableForecastHours[nextIndex];
        
        this.selectForecastHour(nextHour);
    }

    /**
     * Preload images for smooth animation
     */
    async preloadImages() {
        // Preload images for current variable and all forecast hours
        for (const hour of this.availableForecastHours) {
            if (!this.imageCache.has(`${this.currentVariable}_${hour}`)) {
                this.preloadImage(this.currentVariable, hour);
            }
        }
    }

    /**
     * Preload a single image
     */
    async preloadImage(variable, forecastHour) {
        try {
            const maps = await this.apiClient.getMaps({
                variable: variable,
                forecast_hour: forecastHour
            });
            
            if (maps.length > 0) {
                const imageUrl = this.apiClient.getImageUrl(maps[0].image_url);
                const cacheKey = `${variable}_${forecastHour}`;
                
                // Create and load image
                const img = new Image();
                img.src = imageUrl;
                
                // Store in cache when loaded
                img.onload = () => {
                    this.imageCache.set(cacheKey, imageUrl);
                };
            }
        } catch (error) {
            console.error(`Failed to preload image for ${variable} at +${forecastHour}h:`, error);
        }
    }

    /**
     * Load and display the current map
     */
    async loadMap() {
        if (this.isLoading) return;
        
        this.isLoading = true;
        this.showLoading(true);
        this.hideError();
        
        try {
            // Check cache first
            const cacheKey = `${this.currentVariable}_${this.currentForecastHour}`;
            let imageUrl;
            
            if (this.imageCache.has(cacheKey)) {
                imageUrl = this.imageCache.get(cacheKey);
            } else {
                // Fetch from API
                const maps = await this.apiClient.getMaps({
                    variable: this.currentVariable,
                    forecast_hour: this.currentForecastHour
                });
                
                if (maps.length === 0) {
                    throw new Error('No maps available for the selected options');
                }
                
                this.currentMap = maps[0];
                imageUrl = this.apiClient.getImageUrl(this.currentMap.image_url);
                
                // Add to cache
                this.imageCache.set(cacheKey, imageUrl);
            }
            
            // Update map image
            const mapImage = document.getElementById('map-image');
            if (mapImage) {
                mapImage.src = imageUrl;
                mapImage.alt = `${this.currentVariable} forecast at +${this.currentForecastHour}h`;
            }
            
            // Update metadata
            this.updateMetadata();
            
        } catch (error) {
            console.error('Failed to load map:', error);
            this.showError(error.message || 'Failed to load map. Please try again.');
        } finally {
            this.isLoading = false;
            this.showLoading(false);
        }
    }

    /**
     * Update footer metadata
     */
    updateMetadata() {
        const variableSpan = document.getElementById('metadata-variable');
        const forecastTimeSpan = document.getElementById('metadata-forecast-time');
        const validTimeSpan = document.getElementById('metadata-valid-time');
        
        if (variableSpan) {
            const variableLabel = CONFIG.VARIABLES[this.currentVariable]?.label || this.formatVariableName(this.currentVariable);
            variableSpan.textContent = variableLabel;
        }
        
        if (forecastTimeSpan) {
            const forecastLabel = this.currentForecastHour === 0 ? 'Now (Analysis)' : `+${this.currentForecastHour}h Forecast`;
            forecastTimeSpan.textContent = forecastLabel;
        }
        
        if (validTimeSpan && this.currentMap) {
            try {
                const runTime = this.parseRunTime(this.currentMap.run_time);
                const validTime = new Date(runTime.getTime() + this.currentForecastHour * 3600000);
                const formattedTime = this.formatDateTime(validTime);
                validTimeSpan.textContent = `Valid: ${formattedTime}`;
            } catch (error) {
                validTimeSpan.textContent = 'Valid: --';
            }
        }
    }

    /**
     * Parse run time from filename format (YYYYMMDD_HH)
     */
    parseRunTime(runTimeStr) {
        const parts = runTimeStr.split('_');
        const dateStr = parts[0]; // YYYYMMDD
        const hourStr = parts[1]; // HH
        
        const year = parseInt(dateStr.substring(0, 4));
        const month = parseInt(dateStr.substring(4, 6)) - 1; // 0-indexed
        const day = parseInt(dateStr.substring(6, 8));
        const hour = parseInt(hourStr);
        
        return new Date(Date.UTC(year, month, day, hour));
    }

    /**
     * Format date/time for display in user's local timezone
     */
    formatDateTime(date) {
        const options = {
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
            timeZoneName: 'short'
        };
        return date.toLocaleString('en-US', options);
    }

    /**
     * Show/hide loading indicator
     */
    showLoading(show) {
        const loadingIndicator = document.getElementById('loading-indicator');
        if (loadingIndicator) {
            if (show) {
                loadingIndicator.classList.add('active');
            } else {
                loadingIndicator.classList.remove('active');
            }
        }
    }

    /**
     * Show error message
     */
    showError(message) {
        const errorMessage = document.getElementById('error-message');
        if (errorMessage) {
            errorMessage.textContent = message;
            errorMessage.classList.add('active');
            
            // Auto-hide after 5 seconds
            setTimeout(() => this.hideError(), 5000);
        }
    }

    /**
     * Hide error message
     */
    hideError() {
        const errorMessage = document.getElementById('error-message');
        if (errorMessage) {
            errorMessage.classList.remove('active');
        }
    }
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    const viewer = new MapViewer();
    viewer.init();
});
