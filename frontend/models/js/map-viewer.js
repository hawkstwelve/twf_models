/**
 * TWF Models Map Viewer
 * Enhanced with dropdown selectors, animation slider, image preloading, and multi-model support
 */

class MapViewer {
    constructor() {
        this.apiClient = new APIClient(CONFIG.API_BASE_URL);
        
        // Current selections
        this.currentModel = CONFIG.DEFAULT_MODEL;
        this.currentVariable = CONFIG.DEFAULT_VARIABLE;
        this.currentForecastHour = CONFIG.DEFAULT_FORECAST_HOUR;
        this.currentRun = null;
        this.currentMap = null;
        
        // Available options (from API)
        this.availableModels = [];  // Loaded from API
        this.availableVariables = new Set();
        this.availableForecastHours = [];
        this.availableRuns = [];
        
        // State
        this.isLoading = false;
        this.isAnimating = false;
        this.animationSpeed = CONFIG.ANIMATION_SPEED; // frames per second
        this.animationInterval = null;
        this.imageCache = new Map(); // Cache for preloaded images
    }

    /**
     * Get minimum forecast hour for current variable
     */
    getMinForecastHourForVariable(variable) {
        if (!CONFIG.VARIABLE_MIN_FORECAST_HOUR) return 0;
        return CONFIG.VARIABLE_MIN_FORECAST_HOUR[variable] ?? 0;
    }

    /**
     * Get forecast hours filtered for current variable
     */
    getActiveForecastHours() {
        const minHour = this.getMinForecastHourForVariable(this.currentVariable);
        return this.availableForecastHours.filter(hour => hour >= minHour);
    }

    /**
     * Initialize the map viewer
     */
    async init() {
        console.log('Initializing Map Viewer...');
        
        // 1. Fetch available models first
        await this.fetchModels();

        // 2. Fetch available runs for default model
        await this.fetchRuns();
        
        // 3. Fetch available options for default model
        await this.fetchAvailableOptions();
        
        // 4. Populate UI dropdowns
        this.populateModelDropdown();
        this.populateRunDropdown();
        this.populateVariableDropdown();
        this.populateForecastDropdown();
        
        // 5. Setup event listeners
        this.setupEventListeners();
        
        // 6. Initialize mobile UI
        this.initializeMobileUI();
        
        // 7. Sync mobile control offsets
        this.syncMobileOffsets();
        
        // 8. Load initial map
        await this.loadMap();
        
        // 9. Preload next images
        this.preloadImages();
        
        // 10. Start auto-refresh
        setInterval(() => {
            if (!this.isAnimating) {
                this.loadMap();
            }
        }, CONFIG.REFRESH_INTERVAL);
        
        // 11. Refresh available options every 5 minutes
        setInterval(async () => {
            await this.fetchRuns();
            await this.fetchAvailableOptions();
            this.populateRunDropdown();
            this.populateVariableDropdown();
            this.populateForecastDropdown();
        }, 300000); // 5 minutes
        
        // 12. Sync mobile offsets on window resize
        window.addEventListener('resize', () => this.syncMobileOffsets());
        
        console.log('Map Viewer initialized');
    }

    /**
     * Fetch available models from API
     */
    async fetchModels() {
        try {
            console.log('Fetching models...');
            this.availableModels = await this.apiClient.getModels();
            
            console.log(`Loaded ${this.availableModels.length} models:`,
                       this.availableModels.map(m => m.id).join(', '));
            
            // Validate current model is available
            const modelIds = this.availableModels.map(m => m.id);
            if (!modelIds.includes(this.currentModel)) {
                console.warn(`Default model ${this.currentModel} not available, switching to ${modelIds[0]}`);
                this.currentModel = modelIds[0] || 'GFS';
            }
            
        } catch (error) {
            console.error('Failed to fetch models:', error);
            
            // Use fallback
            this.availableModels = [{
                id: 'GFS',
                name: 'GFS',
                full_name: 'Global Forecast System',
                excluded_variables: [],
                color: '#1E90FF'
            }];
        }
    }

    /**
     * Get current model config
     */
    getCurrentModelConfig() {
        return this.availableModels.find(m => m.id === this.currentModel);
    }

    /**
     * Get variables supported by current model
     */
    getAvailableVariablesForModel() {
        const modelConfig = this.getCurrentModelConfig();
        if (!modelConfig) {
            return Object.keys(CONFIG.VARIABLES);
        }
        
        const excludedVars = modelConfig.excluded_variables || [];
        return Object.keys(CONFIG.VARIABLES).filter(v => !excludedVars.includes(v));
    }

    /**
     * Populate model dropdown
     */
    populateModelDropdown() {
        const select = document.getElementById('model-select');
        if (!select) {
            console.warn('Model select element not found');
            return;
        }
        
        select.innerHTML = '';
        
        this.availableModels.forEach(model => {
            const option = document.createElement('option');
            option.value = model.id;
            option.textContent = model.name;
            
            // Apply model color if available
            if (model.color) {
                option.style.color = model.color;
            }
            
            if (model.id === this.currentModel) {
                option.selected = true;
            }
            
            select.appendChild(option);
        });
        
        // Update model badge
        this.updateModelBadge();
        
        console.log(`Populated model dropdown with ${this.availableModels.length} models`);
    }

    /**
     * Update model badge display
     */
    updateModelBadge() {
        const badge = document.getElementById('current-model-badge');
        if (!badge) return;
        
        const modelConfig = this.getCurrentModelConfig();
        if (modelConfig) {
            badge.textContent = modelConfig.name;
            if (modelConfig.color) {
                badge.style.backgroundColor = modelConfig.color;
            }
        }
    }

    /**
     * Fetch available variables and forecast hours from API
     */
    async fetchAvailableOptions() {
        try {
            console.log(`Fetching available options for ${this.currentModel}...`);
            
            const maps = await this.apiClient.getMaps({ 
                model: this.currentModel,
                run_time: this.currentRun || undefined,
                limit: 1000  // Get all available
            });
            
            console.log(`Fetched ${maps.length} maps for ${this.currentModel}`);
            
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
            } else {
                // No maps from API, use model config + fallback
                console.log('No maps from API, using model config fallback');
                this.availableVariables = new Set(this.getAvailableVariablesForModel());
                
                const modelConfig = this.getCurrentModelConfig();
                const maxHour = modelConfig?.max_forecast_hour || 72;
                const increment = modelConfig?.forecast_increment || 6;
                
                this.availableForecastHours = [];
                for (let h = 0; h <= maxHour && h <= 72; h += increment) {
                    this.availableForecastHours.push(h);
                }
            }
            
            // Validate current selections
            if (!this.availableVariables.has(this.currentVariable)) {
                const vars = Array.from(this.availableVariables);
                this.currentVariable = vars[0] || 'temp';
                console.log(`Switched variable to ${this.currentVariable}`);
            }
            
            const activeHours = this.getActiveForecastHours();
            if (!activeHours.includes(this.currentForecastHour)) {
                this.currentForecastHour = activeHours[0] ?? 0;
                console.log(`Switched forecast hour to ${this.currentForecastHour}`);
            }
            
        } catch (error) {
            console.error('Failed to fetch available options:', error);
            // Fallback to config values
            this.availableVariables = new Set(this.getAvailableVariablesForModel());
            this.availableForecastHours = CONFIG.FORECAST_HOURS.slice(0, 13);

            const activeHours = this.getActiveForecastHours();
            if (!activeHours.includes(this.currentForecastHour)) {
                this.currentForecastHour = activeHours[0] ?? 0;
                console.log(`Switched forecast hour to ${this.currentForecastHour}`);
            }
        }
    }

    /**
     * Fetch available runs for current model
     */
    async fetchRuns() {
        try {
            console.log(`Fetching runs for ${this.currentModel}...`);
            this.availableRuns = await this.apiClient.getRuns(this.currentModel);

            if (this.availableRuns.length === 0) {
                this.currentRun = null;
                return;
            }

            const runTimes = new Set(this.availableRuns.map(run => run.run_time));
            if (!this.currentRun || !runTimes.has(this.currentRun)) {
                const latestRun = this.availableRuns.find(run => run.is_latest) || this.availableRuns[0];
                this.currentRun = latestRun.run_time;
            }
        } catch (error) {
            console.error('Failed to fetch runs:', error);
            this.availableRuns = [];
            this.currentRun = null;
        }
    }

    /**
     * Populate variable dropdown (filtered by current model)
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
        
        // Get variables supported by current model
        const supportedVars = this.getAvailableVariablesForModel();
        
        // Filter to only variables with available data
        const baseOrder = Array.isArray(CONFIG.VARIABLE_ORDER) && CONFIG.VARIABLE_ORDER.length
            ? CONFIG.VARIABLE_ORDER
            : Object.keys(CONFIG.VARIABLES);

        const order = [...baseOrder, ...Array.from(this.availableVariables)];

        const variables = order
            .filter((v, index, self) => self.indexOf(v) === index)
            .filter(v => this.availableVariables.has(v))
            .filter(v => supportedVars.includes(v));
        
        // Fallback to all supported variables if no data yet
        if (variables.length === 0) {
            order.filter(v => supportedVars.includes(v)).forEach(v => variables.push(v));
        }
        
        variables.forEach(variable => {
            const option = document.createElement('option');
            option.value = variable;
            
            const varConfig = CONFIG.VARIABLES[variable];
            const label = varConfig?.label || this.formatVariableName(variable);
            const icon = varConfig?.icon || '';
            
            option.textContent = icon ? `${icon} ${label}` : label;
            
            if (variable === this.currentVariable) {
                option.selected = true;
            }
            
            select.appendChild(option);
        });
        
        // If current variable not supported by model, switch to first available
        if (!supportedVars.includes(this.currentVariable) && variables.length > 0) {
            console.log(`Variable ${this.currentVariable} not supported by ${this.currentModel}, switching to ${variables[0]}`);
            this.currentVariable = variables[0];
            select.value = this.currentVariable;
        }
        
        console.log('Variable dropdown populated with', variables.length, 'options');
    }

    /**
     * Populate run dropdown
     */
    populateRunDropdown() {
        const select = document.getElementById('run-select');
        if (!select) {
            console.warn('Run select element not found');
            return;
        }

        select.innerHTML = '';

        if (this.availableRuns.length === 0) {
            const option = document.createElement('option');
            option.value = '';
            option.textContent = 'Latest Run (Auto)';
            option.selected = true;
            select.appendChild(option);
            return;
        }

        this.availableRuns.forEach((run, index) => {
            const option = document.createElement('option');
            option.value = run.run_time;

            let label = run.run_time_formatted || run.hour || run.run_time;
            if (run.is_latest) {
                label += ' (Latest)';
            }

            option.textContent = label;

            if (run.run_time === this.currentRun || (!this.currentRun && index === 0)) {
                option.selected = true;
            }

            select.appendChild(option);
        });

        console.log('Run dropdown populated with', this.availableRuns.length, 'options');
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
        
        const activeHours = this.getActiveForecastHours();

        console.log('Populating forecast hours:', activeHours);
        
        // Clear existing options
        select.innerHTML = '';
        
        // Add available forecast hours
        activeHours.forEach(hour => {
            const option = document.createElement('option');
            option.value = hour;
            option.textContent = hour === 0 ? 'Now (Analysis)' : `+${hour}h`;
            
            if (hour === this.currentForecastHour) {
                option.selected = true;
            }
            
            select.appendChild(option);
        });
        
        console.log('Forecast dropdown populated with', activeHours.length, 'options');
        
        // Update slider
        this.updateTimeSlider();
    }

    /**
     * Update time slider range and labels
     */
    updateTimeSlider() {
        const slider = document.getElementById('time-slider');
        const maxLabel = document.getElementById('slider-max-label');
        
        const activeHours = this.getActiveForecastHours();
        if (!slider || activeHours.length === 0) return;
        
        slider.min = 0;
        slider.max = activeHours.length - 1;
        slider.value = activeHours.indexOf(this.currentForecastHour);
        
        // Update max label
        const maxHour = activeHours[activeHours.length - 1];
        if (maxLabel) {
            maxLabel.textContent = `+${maxHour}h`;
        }
        
        this.updateSliderLabel();
        
        // Update mobile slider too
        this.updateMobileTimeSlider();
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
        // Model selector
        const modelSelect = document.getElementById('model-select');
        if (modelSelect) {
            modelSelect.addEventListener('change', (e) => {
                this.selectModel(e.target.value);
            });
        }

        // Run selector
        const runSelect = document.getElementById('run-select');
        if (runSelect) {
            runSelect.addEventListener('change', (e) => {
                const value = e.target.value || null;
                this.selectRun(value);
            });
        }

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
                const activeHours = this.getActiveForecastHours();
                const hour = activeHours[index];
                if (hour === undefined) return;
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

        // Mobile-specific controls
        this.setupMobileControls();
    }

    /**
     * Setup mobile-specific controls
     */
    setupMobileControls() {
        // Mobile pill buttons
        const pillButtons = document.querySelectorAll('.pill-btn');
        pillButtons.forEach(btn => {
            btn.addEventListener('click', (e) => {
                const control = e.currentTarget.dataset.control;
                this.openMobileModal(control);
            });
        });

        // Modal close button
        const modalCloseBtn = document.getElementById('modal-close-btn');
        const modalOverlay = document.getElementById('modal-overlay');
        
        if (modalCloseBtn) {
            modalCloseBtn.addEventListener('click', () => this.closeMobileModal());
        }
        
        if (modalOverlay) {
            modalOverlay.addEventListener('click', (e) => {
                if (e.target === modalOverlay) {
                    this.closeMobileModal();
                }
            });
        }

        // Mobile time slider
        const mobileSlider = document.getElementById('mobile-time-slider');
        if (mobileSlider) {
            mobileSlider.addEventListener('input', (e) => {
                const index = parseInt(e.target.value);
                const activeHours = this.getActiveForecastHours();
                const hour = activeHours[index];
                if (hour === undefined) return;
                this.selectForecastHour(hour, false);
                this.updateMobileSliderLabel();
            });
        }

        // Mobile play/pause buttons
        const mobilePlayBtn = document.getElementById('mobile-play-btn');
        const mobilePauseBtn = document.getElementById('mobile-pause-btn');
        
        if (mobilePlayBtn) {
            mobilePlayBtn.addEventListener('click', () => this.startAnimation());
        }
        
        if (mobilePauseBtn) {
            mobilePauseBtn.addEventListener('click', () => this.stopAnimation());
        }

        // Map info overlay toggle
        const infoToggleBtn = document.getElementById('info-toggle-btn');
        const infoContent = document.getElementById('info-content');
        
        if (infoToggleBtn && infoContent) {
            infoToggleBtn.addEventListener('click', () => {
                infoContent.classList.toggle('expanded');
            });
        }
    }

    /**
     * Open mobile modal for control selection
     */
    openMobileModal(controlType) {
        const modal = document.getElementById('modal-overlay');
        const modalTitle = document.getElementById('modal-title');
        const modalContent = document.getElementById('modal-content');
        
        if (!modal || !modalTitle || !modalContent) return;

        // Clear content
        modalContent.innerHTML = '';

        // Set title and populate options based on control type
        switch (controlType) {
            case 'model':
                modalTitle.textContent = 'Select Model';
                this.availableModels.forEach(model => {
                    const option = document.createElement('button');
                    option.className = 'modal-option';
                    option.textContent = model.name;
                    if (model.id === this.currentModel) {
                        option.classList.add('selected');
                    }
                    option.addEventListener('click', () => {
                        this.selectModel(model.id);
                        this.updateMobilePillValue('model', model.name);
                        this.closeMobileModal();
                    });
                    modalContent.appendChild(option);
                });
                break;

            case 'run':
                modalTitle.textContent = 'Select Run Time';
                this.availableRuns.forEach(run => {
                    const option = document.createElement('button');
                    option.className = 'modal-option';
                    const runLabel = this.formatRunTime(run.run_time);
                    option.textContent = runLabel + (run.is_latest ? ' (Latest)' : '');
                    if (run.run_time === this.currentRun) {
                        option.classList.add('selected');
                    }
                    option.addEventListener('click', () => {
                        this.selectRun(run.run_time);
                        this.updateMobilePillValue('run', runLabel);
                        this.closeMobileModal();
                    });
                    modalContent.appendChild(option);
                });
                break;

            case 'variable':
                modalTitle.textContent = 'Select Variable';
                const variables = Array.from(this.availableVariables);
                variables.forEach(variable => {
                    const option = document.createElement('button');
                    option.className = 'modal-option';
                    const varConfig = CONFIG.VARIABLES[variable];
                    const displayName = varConfig?.label || this.formatVariableName(variable);
                    option.textContent = displayName;
                    if (variable === this.currentVariable) {
                        option.classList.add('selected');
                    }
                    option.addEventListener('click', () => {
                        this.selectVariable(variable);
                        this.updateMobilePillValue('variable', displayName);
                        this.closeMobileModal();
                    });
                    modalContent.appendChild(option);
                });
                break;
        }

        // Show modal
        modal.classList.add('active');
    }

    /**
     * Close mobile modal
     */
    closeMobileModal() {
        const modal = document.getElementById('modal-overlay');
        if (modal) {
            modal.classList.remove('active');
        }
    }

    /**
     * Update mobile pill button value
     */
    updateMobilePillValue(controlType, value) {
        const pillValue = document.getElementById(`pill-${controlType}-value`);
        if (pillValue) {
            // Truncate long values
            const maxLength = 15;
            const displayValue = value && value.length > maxLength ? value.substring(0, maxLength) + '...' : value;
            pillValue.textContent = displayValue || 'N/A';
        }
    }

    /**
     * Update mobile time slider
     */
    updateMobileTimeSlider() {
        const slider = document.getElementById('mobile-time-slider');
        const maxLabel = document.getElementById('mobile-slider-max');
        
        const activeHours = this.getActiveForecastHours();
        if (!slider || activeHours.length === 0) return;
        
        slider.min = 0;
        slider.max = activeHours.length - 1;
        slider.value = activeHours.indexOf(this.currentForecastHour);
        
        // Update max label
        const maxHour = activeHours[activeHours.length - 1];
        if (maxLabel) {
            maxLabel.textContent = `+${maxHour}h`;
        }
        
        this.updateMobileSliderLabel();
    }

    /**
     * Update mobile slider current label
     */
    updateMobileSliderLabel() {
        const label = document.getElementById('mobile-slider-current');
        if (!label) return;
        
        const hour = this.currentForecastHour;
        label.textContent = hour === 0 ? 'Now' : `+${hour}h`;
    }

    /**
     * Format run time for display
     */
    formatRunTime(runTime) {
        // Extract hour from run_time (e.g., "2026-01-29T12:00:00Z" -> "12Z")
        const match = runTime.match(/T(\d{2}):/);
        return match ? `${match[1]}Z` : runTime;
    }

    /**
     * Initialize mobile UI with current values
     */
    initializeMobileUI() {
        // Initialize mobile pill values
        const modelConfig = this.getCurrentModelConfig();
        if (modelConfig) {
            this.updateMobilePillValue('model', modelConfig.name);
        }
        
        // Initialize run value
        if (this.currentRun) {
            const runLabel = this.formatRunTime(this.currentRun);
            this.updateMobilePillValue('run', runLabel);
        }
        
        // Initialize variable value - use CONFIG.VARIABLES for display name
        const varConfig = CONFIG.VARIABLES[this.currentVariable];
        if (varConfig && varConfig.label) {
            this.updateMobilePillValue('variable', varConfig.label);
        } else {
            // Fallback to formatted variable name
            const displayName = this.formatVariableName(this.currentVariable);
            this.updateMobilePillValue('variable', displayName);
        }
        
        // Initialize mobile slider
        this.updateMobileTimeSlider();
    }

    /**
     * Sync mobile control offsets dynamically based on bottom panel height
     */
    syncMobileOffsets() {
        const panel = document.getElementById('bottom-control-panel');
        const pill = document.getElementById('mobile-controls-bar');
        if (!panel || !pill) return;
        
        // Set pill bar bottom to bottom panel height + safe area
        pill.style.bottom = `calc(${panel.offsetHeight}px + env(safe-area-inset-bottom))`;
    }

    /**
     * Select a model
     */
    async selectModel(modelId) {
        if (this.currentModel === modelId) return;
        
        console.log(`Model changed: ${this.currentModel} → ${modelId}`);
        
        // Stop any animation
        this.stopAnimation();
        
        // Clear image cache
        this.imageCache.clear();
        
        // Update current model
        this.currentModel = modelId;
        
        // Update dropdown
        const select = document.getElementById('model-select');
        if (select) {
            select.value = modelId;
        }
        
        // Update model badge
        this.updateModelBadge();
        
        // Show loading state
        this.showLoading();
        
        try {
            // Fetch new data for this model
            await this.fetchRuns();
            await this.fetchAvailableOptions();
            
            // Update dropdowns
            this.populateRunDropdown();
            // Update dropdowns (variables may differ between models)
            this.populateVariableDropdown();
            this.populateForecastDropdown();
            
            // Update mobile pills with new model data
            const modelConfig = this.getCurrentModelConfig();
            if (modelConfig) {
                this.updateMobilePillValue('model', modelConfig.name);
            }
            
            // Update run pill with the current run time
            if (this.currentRun) {
                const runLabel = this.formatRunTime(this.currentRun);
                this.updateMobilePillValue('run', runLabel);
            }
            
            // Load map for new model
            await this.loadMap();
            
            // Preload images
            this.preloadImages();
            
        } catch (error) {
            console.error('Error switching models:', error);
            this.showError(`Failed to switch to ${modelId}`);
        } finally {
            this.hideLoading();
        }
    }

    /**
     * Select a run time
     */
    async selectRun(runTime) {
        if (this.currentRun === runTime) return;

        console.log(`Run changed: ${this.currentRun} → ${runTime}`);

        // Stop any animation
        this.stopAnimation();

        // Clear image cache
        this.imageCache.clear();

        // Update current run
        this.currentRun = runTime;

        // Update dropdown
        const select = document.getElementById('run-select');
        if (select) {
            select.value = runTime || '';
        }

        // Show loading state
        this.showLoading();

        try {
            await this.fetchAvailableOptions();

            // Update dropdowns
            this.populateVariableDropdown();
            this.populateForecastDropdown();

            // Load map for selected run
            await this.loadMap();

            // Preload images
            this.preloadImages();
        } catch (error) {
            console.error('Error switching runs:', error);
            this.showError('Failed to switch run time');
        } finally {
            this.hideLoading();
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
        
        // Update forecast options for variable
        this.populateForecastDropdown();

        const activeHours = this.getActiveForecastHours();
        if (!activeHours.includes(this.currentForecastHour)) {
            this.currentForecastHour = activeHours[0] ?? 0;
            const forecastSelect = document.getElementById('forecast-select');
            if (forecastSelect) {
                forecastSelect.value = this.currentForecastHour;
            }
            this.updateTimeSlider();
        }

        // Clear cache and load new map
        this.imageCache.clear();
        this.loadMap();
        this.preloadImages();
    }

    /**
     * Select a forecast hour
     */
    selectForecastHour(hour, updateSlider = true) {
        const minHour = this.getMinForecastHourForVariable(this.currentVariable);
        if (hour < minHour) {
            hour = this.getActiveForecastHours()[0] ?? minHour;
        }
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
            const activeHours = this.getActiveForecastHours();
            if (slider) {
                slider.value = activeHours.indexOf(hour);
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
        if (this.isAnimating || this.getActiveForecastHours().length <= 1) return;
        
        this.isAnimating = true;
        
        // Update desktop button visibility
        const playBtn = document.getElementById('play-btn');
        const pauseBtn = document.getElementById('pause-btn');
        if (playBtn) playBtn.style.display = 'none';
        if (pauseBtn) pauseBtn.style.display = 'flex';
        
        // Update mobile button visibility
        const mobilePlayBtn = document.getElementById('mobile-play-btn');
        const mobilePauseBtn = document.getElementById('mobile-pause-btn');
        if (mobilePlayBtn) mobilePlayBtn.style.display = 'none';
        if (mobilePauseBtn) mobilePauseBtn.style.display = 'flex';
        
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
        
        // Update desktop button visibility
        const playBtn = document.getElementById('play-btn');
        const pauseBtn = document.getElementById('pause-btn');
        if (playBtn) playBtn.style.display = 'flex';
        if (pauseBtn) pauseBtn.style.display = 'none';
        
        // Update mobile button visibility
        const mobilePlayBtn = document.getElementById('mobile-play-btn');
        const mobilePauseBtn = document.getElementById('mobile-pause-btn');
        if (mobilePlayBtn) mobilePlayBtn.style.display = 'flex';
        if (mobilePauseBtn) mobilePauseBtn.style.display = 'none';
    }

    /**
     * Advance to next frame in animation
     */
    advanceFrame() {
        const activeHours = this.getActiveForecastHours();
        const currentIndex = activeHours.indexOf(this.currentForecastHour);
        const nextIndex = (currentIndex + 1) % activeHours.length;
        const nextHour = activeHours[nextIndex];
        
        this.selectForecastHour(nextHour);
    }

    /**
     * Preload images for smooth animation
     */
    async preloadImages() {
        // Preload images for current model, variable and all forecast hours
        for (const hour of this.getActiveForecastHours()) {
            const cacheKey = `${this.currentModel}_${this.currentRun || 'latest'}_${this.currentVariable}_${hour}`;
            if (!this.imageCache.has(cacheKey)) {
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
                model: this.currentModel,
                variable: variable,
                forecast_hour: forecastHour,
                run_time: this.currentRun || undefined
            });
            
            if (maps.length > 0) {
                const imageUrl = this.apiClient.getImageUrl(maps[0].image_url);
                const cacheKey = `${this.currentModel}_${this.currentRun || 'latest'}_${variable}_${forecastHour}`;
                
                // Create and load image
                const img = new Image();
                img.src = imageUrl;
                
                // Store in cache when loaded
                img.onload = () => {
                    this.imageCache.set(cacheKey, imageUrl);
                };
            }
        } catch (error) {
            console.error(`Failed to preload image for ${this.currentModel} ${variable} at +${forecastHour}h:`, error);
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
            const cacheKey = `${this.currentModel}_${this.currentRun || 'latest'}_${this.currentVariable}_${this.currentForecastHour}`;
            let imageUrl;
            
            if (this.imageCache.has(cacheKey)) {
                imageUrl = this.imageCache.get(cacheKey);
            } else {
                // Fetch from API
                const maps = await this.apiClient.getMaps({
                    model: this.currentModel,
                    variable: this.currentVariable,
                    forecast_hour: this.currentForecastHour,
                    run_time: this.currentRun || undefined
                });
                
                if (maps.length === 0) {
                    const modelConfig = this.getCurrentModelConfig();
                    throw new Error(
                        `No ${modelConfig?.name || this.currentModel} maps available for ` +
                        `${this.currentVariable} at +${this.currentForecastHour}h`
                    );
                }
                
                this.currentMap = maps[0];
                imageUrl = this.apiClient.getImageUrl(this.currentMap.image_url);
                
                // Add to cache
                this.imageCache.set(cacheKey, imageUrl);
            }
            
            // Update map image
            const mapImage = document.getElementById('map-image');
            if (mapImage) {
                // Update aspect ratio dynamically when image loads
                mapImage.addEventListener('load', () => {
                    const ar = mapImage.naturalWidth / mapImage.naturalHeight;
                    document.documentElement.style.setProperty('--map-aspect', `${ar}`);
                }, { once: true });
                
                mapImage.src = imageUrl;
                mapImage.alt = `${this.currentModel} ${this.currentVariable} forecast at +${this.currentForecastHour}h`;
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
        // Desktop footer metadata
        const desktopModelSpan = document.getElementById('footer-metadata-model');
        const desktopRunSpan = document.getElementById('footer-metadata-run');
        const variableSpan = document.getElementById('footer-metadata-variable');
        const validTimeSpan = document.getElementById('footer-metadata-valid-time');
        
        // Mobile overlay metadata (old - may still be used)
        const mobileVariableSpan = document.getElementById('metadata-variable');
        const mobileForecastTimeSpan = document.getElementById('metadata-forecast-time');
        const mobileValidTimeSpan = document.getElementById('metadata-valid-time');
        
        // Mobile info bar (new)
        const mobileInfoModel = document.getElementById('mobile-info-model');
        const mobileInfoRun = document.getElementById('mobile-info-run');
        const mobileInfoVariable = document.getElementById('mobile-info-variable');
        const mobileInfoValidTime = document.getElementById('mobile-info-valid-time');
        
        const variableLabel = CONFIG.VARIABLES[this.currentVariable]?.label || this.formatVariableName(this.currentVariable);
        const forecastLabel = this.currentForecastHour === 0 ? 'Now (Analysis)' : `+${this.currentForecastHour}h Forecast`;
        
        // Get model config
        const modelConfig = this.getCurrentModelConfig();
        
        // Update desktop footer with model name
        if (desktopModelSpan && modelConfig) {
            desktopModelSpan.textContent = modelConfig.name;
        }
        
        // Update desktop footer with run time
        if (desktopRunSpan && this.currentRun) {
            const date = new Date(this.currentRun);
            const day = String(date.getUTCDate()).padStart(2, '0');
            const month = String(date.getUTCMonth() + 1).padStart(2, '0');
            const hour = String(date.getUTCHours()).padStart(2, '0');
            desktopRunSpan.textContent = `Initialized: ${hour}Z ${month}/${day}`;
        }
        
        // Update desktop footer with variable
        if (variableSpan) variableSpan.textContent = variableLabel;
        
        // Update old mobile overlay (if still present)
        if (mobileVariableSpan) mobileVariableSpan.textContent = variableLabel;
        if (mobileForecastTimeSpan) mobileForecastTimeSpan.textContent = forecastLabel;
        
        // Update new mobile info bar
        if (mobileInfoModel && modelConfig) {
            mobileInfoModel.textContent = modelConfig.name;
        }
        if (mobileInfoRun && this.currentRun) {
            // Format as "Initialized: HHZ MM/DD"
            const date = new Date(this.currentRun);
            const day = String(date.getUTCDate()).padStart(2, '0');
            const month = String(date.getUTCMonth() + 1).padStart(2, '0');
            const hour = String(date.getUTCHours()).padStart(2, '0');
            mobileInfoRun.textContent = `Initialized: ${hour}Z ${month}/${day}`;
        }
        if (mobileInfoVariable) {
            mobileInfoVariable.textContent = variableLabel;
        }
        
        if (this.currentMap) {
            try {
                const runTime = this.parseRunTime(this.currentMap.run_time);
                const validTime = new Date(runTime.getTime() + this.currentForecastHour * 3600000);
                const formattedTime = this.formatDateTime(validTime);
                const validText = `Valid: ${formattedTime}`;
                
                if (validTimeSpan) validTimeSpan.textContent = validText;
                if (mobileValidTimeSpan) mobileValidTimeSpan.textContent = validText;
                if (mobileInfoValidTime) mobileInfoValidTime.textContent = validText;
            } catch (error) {
                if (validTimeSpan) validTimeSpan.textContent = 'Valid: --';
                if (mobileValidTimeSpan) mobileValidTimeSpan.textContent = 'Valid: --';
                if (mobileInfoValidTime) mobileInfoValidTime.textContent = 'Valid: --';
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
