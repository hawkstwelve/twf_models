/**
 * TWF Models Map Viewer
 */

class MapViewer {
    constructor() {
        this.apiClient = new APIClient(CONFIG.API_BASE_URL);
        this.currentVariable = 'temp';
        this.currentForecastHour = 0;
        this.currentMap = null;
        this.isLoading = false;
    }

    /**
     * Initialize the map viewer
     */
    async init() {
        this.generateForecastHourButtons();
        this.setupEventListeners();
        await this.loadMap();
        
        // Auto-refresh every minute to check for new maps
        setInterval(() => this.loadMap(), CONFIG.REFRESH_INTERVAL);
    }

    /**
     * Generate forecast hour buttons dynamically from config
     */
    generateForecastHourButtons() {
        const container = document.getElementById('forecast-hour-buttons');
        if (!container) return;
        
        // Clear existing buttons
        container.innerHTML = '';
        
        // Generate button for each forecast hour
        CONFIG.FORECAST_HOURS.forEach((hour, index) => {
            const button = document.createElement('button');
            button.className = 'btn hour-btn';
            button.dataset.hour = hour;
            
            // First button is active by default
            if (index === 0) {
                button.classList.add('active');
            }
            
            // Format label
            if (hour === 0) {
                button.textContent = 'Now';
            } else {
                button.textContent = `+${hour}h`;
            }
            
            container.appendChild(button);
        });
    }

    /**
     * Setup event listeners for UI controls
     */
    setupEventListeners() {
        // Variable selector
        document.querySelectorAll('.variable-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const variable = e.target.dataset.variable;
                this.selectVariable(variable);
            });
        });

        // Forecast hour buttons (use event delegation since buttons are dynamic)
        const forecastContainer = document.getElementById('forecast-hour-buttons');
        if (forecastContainer) {
            forecastContainer.addEventListener('click', (e) => {
                if (e.target.classList.contains('hour-btn')) {
                    const hour = parseInt(e.target.dataset.hour);
                    this.selectForecastHour(hour);
                }
            });
        }
    }

    /**
     * Select a variable
     */
    selectVariable(variable) {
        this.currentVariable = variable;
        
        // Update button states
        document.querySelectorAll('.variable-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.variable === variable);
        });
        
        // Load new map
        this.loadMap();
    }

    /**
     * Select a forecast hour
     */
    selectForecastHour(hour) {
        this.currentForecastHour = hour;
        
        // Update button states
        document.querySelectorAll('.hour-btn').forEach(btn => {
            btn.classList.toggle('active', parseInt(btn.dataset.hour) === hour);
        });
        
        // Load new map
        this.loadMap();
    }

    /**
     * Load and display the current map
     */
    async loadMap() {
        if (this.isLoading) return;
        
        this.isLoading = true;
        this.showLoading();
        
        try {
            // Fetch maps for current selection
            const maps = await this.apiClient.getMaps({
                variable: this.currentVariable,
                forecast_hour: this.currentForecastHour,
                model: 'GFS'
            });
            
            if (maps.length > 0) {
                // Use the most recent map (they should all be from latest run)
                const latestMap = maps[0];
                this.currentMap = latestMap;
                this.displayMap(latestMap);
                this.hideError();
            } else {
                this.showError('No maps available yet. Waiting for next generation...');
            }
        } catch (error) {
            console.error('Error loading map:', error);
            this.showError('Failed to load map. Please check your connection.');
        } finally {
            this.isLoading = false;
            this.hideLoading();
        }
    }

    /**
     * Display a map
     */
    displayMap(map) {
        const mapImg = document.getElementById('map-image');
        const mapTitle = document.getElementById('map-title');
        const mapMeta = document.getElementById('map-metadata');
        const mapContainer = document.querySelector('.map-container');
        
        // Set image source
        const imageUrl = this.apiClient.getImageUrl(map.image_url);
        mapImg.src = imageUrl;
        
        // Get variable info with fallback for unknown variables
        const varInfo = CONFIG.VARIABLES[map.variable] || {
            label: map.variable.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase()),
            units: '',
            description: map.variable
        };
        
        mapImg.alt = `${varInfo.label} - Forecast Hour ${map.forecast_hour}`;
        
        // Update title
        mapTitle.textContent = `${varInfo.label} - ${this.formatForecastHour(map.forecast_hour)}`;
        
        // Update metadata
        const runTime = this.formatRunTime(map.run_time);
        const validTime = this.calculateValidTime(map.run_time, map.forecast_hour);
        
        mapMeta.innerHTML = `
            <div class="meta-item">
                <span class="meta-label">Model Run:</span>
                <span class="meta-value">${runTime}</span>
            </div>
            <div class="meta-item">
                <span class="meta-label">Valid Time:</span>
                <span class="meta-value">${validTime}</span>
            </div>
            <div class="meta-item">
                <span class="meta-label">Region:</span>
                <span class="meta-value">${CONFIG.REGION}</span>
            </div>
        `;
        
        // Show the map container
        mapContainer.style.display = 'block';
    }

    /**
     * Format forecast hour for display
     */
    formatForecastHour(hour) {
        if (hour === 0) return 'Now (Analysis)';
        return `+${hour} hours`;
    }

    /**
     * Format run time for display
     */
    formatRunTime(runTimeStr) {
        // runTimeStr format: "YYYYMMDD_HH"
        const [date, hour] = runTimeStr.split('_');
        const year = date.substring(0, 4);
        const month = date.substring(4, 6);
        const day = date.substring(6, 8);
        
        const dateObj = new Date(`${year}-${month}-${day}T${hour}:00:00Z`);
        
        return dateObj.toLocaleString('en-US', {
            month: 'short',
            day: 'numeric',
            hour: 'numeric',
            minute: '2-digit',
            timeZoneName: 'short'
        });
    }

    /**
     * Calculate valid time from run time and forecast hour
     */
    calculateValidTime(runTimeStr, forecastHour) {
        const [date, hour] = runTimeStr.split('_');
        const year = date.substring(0, 4);
        const month = date.substring(4, 6);
        const day = date.substring(6, 8);
        
        const runDate = new Date(`${year}-${month}-${day}T${hour}:00:00Z`);
        const validDate = new Date(runDate.getTime() + forecastHour * 60 * 60 * 1000);
        
        return validDate.toLocaleString('en-US', {
            month: 'short',
            day: 'numeric',
            hour: 'numeric',
            minute: '2-digit',
            timeZoneName: 'short'
        });
    }

    /**
     * Show loading indicator
     */
    showLoading() {
        const loader = document.getElementById('loading-indicator');
        if (loader) loader.style.display = 'flex';
    }

    /**
     * Hide loading indicator
     */
    hideLoading() {
        const loader = document.getElementById('loading-indicator');
        if (loader) loader.style.display = 'none';
    }

    /**
     * Show error message
     */
    showError(message) {
        const errorDiv = document.getElementById('error-message');
        if (errorDiv) {
            errorDiv.textContent = message;
            errorDiv.style.display = 'block';
        }
        
        // Hide map container
        document.querySelector('.map-container').style.display = 'none';
    }

    /**
     * Hide error message
     */
    hideError() {
        const errorDiv = document.getElementById('error-message');
        if (errorDiv) {
            errorDiv.style.display = 'none';
        }
    }
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    const viewer = new MapViewer();
    viewer.init();
});
