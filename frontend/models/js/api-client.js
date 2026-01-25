/**
 * API Client for TWF Models Backend
 */

class APIClient {
    constructor(baseUrl) {
        this.baseUrl = baseUrl;
    }

    /**
     * Fetch available maps from the API
     */
    async getMaps(filters = {}) {
        try {
            const params = new URLSearchParams();
            
            if (filters.variable) params.append('variable', filters.variable);
            if (filters.forecast_hour !== undefined) params.append('forecast_hour', filters.forecast_hour);
            if (filters.model) params.append('model', filters.model);
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
    async getRuns() {
        try {
            const url = `${this.baseUrl}/api/runs`;
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
}
