/**
 * API Client for TWF Models Backend
 */

class APIClient {
    constructor(baseUrl) {
        this.baseUrl = baseUrl;
        this.modelsCache = null;
        this.modelsCacheTime = null;
    }

    /**
     * Get list of available models
     * Cached for 5 minutes to reduce API calls
     */
    async getModels() {
        // Check cache
        if (this.modelsCache && this.modelsCacheTime) {
            const age = Date.now() - this.modelsCacheTime;
            if (age < CONFIG.MODEL_CACHE_DURATION) {
                console.log('Using cached models');
                return this.modelsCache;
            }
        }
        
        try {
            console.log('Fetching models from API...');
            const response = await fetch(`${this.baseUrl}/api/models`);
            
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            
            const data = await response.json();
            
            // Cache the result
            this.modelsCache = data.models;
            this.modelsCacheTime = Date.now();
            
            console.log(`Loaded ${this.modelsCache.length} models:`, 
                        this.modelsCache.map(m => m.id).join(', '));
            
            return this.modelsCache;
            
        } catch (error) {
            console.error('Failed to fetch models:', error);
            
            // Return fallback (GFS only)
            const fallback = [
                {
                    id: 'GFS',
                    name: 'GFS',
                    full_name: 'Global Forecast System',
                    description: 'NOAA\'s global weather model',
                    excluded_variables: [],
                    color: '#1E90FF',
                    max_forecast_hour: 384,
                    forecast_increment: 6,
                    run_hours: [0, 6, 12, 18]
                }
            ];
            
            this.modelsCache = fallback;
            this.modelsCacheTime = Date.now();
            
            return fallback;
        }
    }

    /**
     * Get info about a specific model
     */
    async getModelInfo(modelId) {
        try {
            const response = await fetch(`${this.baseUrl}/api/models/${modelId}`);
            
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            
            return await response.json();
            
        } catch (error) {
            console.error(`Failed to fetch model ${modelId}:`, error);
            return null;
        }
    }

    /**
     * Fetch available maps from the API
     */
    async getMaps(filters = {}) {
        try {
            const params = new URLSearchParams();
            
            if (filters.model) params.append('model', filters.model);
            if (filters.variable) params.append('variable', filters.variable);
            if (filters.forecast_hour !== undefined) params.append('forecast_hour', filters.forecast_hour);
            if (filters.run_time) params.append('run_time', filters.run_time);
            
            const url = `${this.baseUrl}/api/maps${params.toString() ? '?' + params.toString() : ''}`;
            const response = await fetch(url);
            
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            
            const data = await response.json();
            return data.maps || [];
        } catch (error) {
            console.error('Failed to fetch maps:', error);
            throw error;
        }
    }

    /**
     * Fetch available GFS runs
     */
    async getRuns(model = 'GFS') {
        try {
            const url = `${this.baseUrl}/api/runs?model=${model}`;
            const response = await fetch(url);
            
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            
            const data = await response.json();
            return data.runs || [];
        } catch (error) {
            console.error('Failed to fetch runs:', error);
            throw error;
        }
    }

    /**
     * Get the full image URL for a map
     */
    getImageUrl(imageUrl) {
        return `${this.baseUrl}${imageUrl}`;
    }

    /**
     * Check API health
     */
    async checkHealth() {
        try {
            const response = await fetch(`${this.baseUrl}/health`);
            return response.ok;
        } catch (error) {
            return false;
        }
    }

    /**
     * Clear model cache (call when switching models or refreshing)
     */
    clearModelCache() {
        this.modelsCache = null;
        this.modelsCacheTime = null;
    }
}
