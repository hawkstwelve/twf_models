# Invision Community Integration Guide

## Overview

This document covers integrating the TWF Weather Models with Invision Community v4 (current) and v5 (upcoming upgrade).

## Invision Community v4 Integration

### Option 1: Custom Page (Recommended)

Invision Community v4 supports custom pages that can be added to the navigation.

1. **Create a Custom Page**:
   - Admin CP → Pages → Pages → Create New
   - Set URL as `/models`
   - Add to navigation menu

2. **Embed the Maps**:
   - Use HTML block or custom template
   - Embed via iframe or direct JavaScript integration

### Option 2: Widget/Block

Create a widget that can be placed on any page:

1. **Create HTML Widget**:
   - Admin CP → Pages → Widgets → Create New
   - Use HTML/JavaScript to fetch and display maps
   - Can be placed in sidebar or main content area

### Option 3: Direct Link in Navigation

Add a navigation item that links directly to your API:

1. **Add Navigation Item**:
   - Admin CP → Customization → Navigation
   - Add new item pointing to your API endpoint
   - Opens in new tab/window

## Invision Community v5 Integration

Invision Community v5 has enhanced capabilities:

### Custom Applications

v5 supports custom applications that can be more deeply integrated:

1. **Create Custom Application**:
   - More native integration
   - Can use Invision's authentication
   - Better performance

### REST API Integration

v5 has improved REST API support:

1. **Use Invision's API**:
   - Authenticate users via Invision's OAuth
   - Share session data
   - Better security

## Implementation Approaches

### Approach 1: Iframe Embed (Simplest)

**Pros:**
- Easiest to implement
- Isolated from forum code
- Easy to update

**Cons:**
- May have styling issues
- Less integrated feel
- Potential iframe security restrictions

**Implementation:**
```html
<iframe 
    src="https://your-api-domain.com/models" 
    width="100%" 
    height="800px"
    frameborder="0"
    style="border: none;">
</iframe>
```

### Approach 2: JavaScript Integration (Recommended)

**Pros:**
- Better integration
- Can match forum styling
- More flexible

**Cons:**
- Requires CORS configuration
- More complex implementation

**Implementation:**
```html
<div id="twf-models-container"></div>
<script>
    const API_BASE = 'https://your-api-domain.com/api';
    
    async function loadMaps() {
        const response = await fetch(`${API_BASE}/maps`);
        const data = await response.json();
        
        const container = document.getElementById('twf-models-container');
        // Render maps...
    }
    
    loadMaps();
</script>
```

### Approach 3: Server-Side Integration

**Pros:**
- Best performance
- Can use Invision's caching
- Full control

**Cons:**
- Requires PHP knowledge
- More complex setup
- Tighter coupling

**Implementation:**
- Create custom PHP page in Invision
- Use cURL to fetch map data
- Render server-side

## CORS Configuration

For JavaScript integration, ensure CORS is properly configured:

```python
# In backend/app/main.py
cors_origins = [
    "https://theweatherforums.com",
    "https://www.theweatherforums.com",
    # Add any other domains
]
```

## Authentication (Optional)

If you want to restrict access to forum members:

### Option 1: IP Whitelist
- Only allow requests from your forum's IP
- Simple but less flexible

### Option 2: API Key
- Generate API keys for forum
- Pass key in requests
- More secure

### Option 3: Invision OAuth (v5)
- Use Invision's OAuth system
- Most secure
- Requires v5 upgrade

## Styling Integration

### Match Forum Theme

1. **Get Forum Colors**:
   - Check Invision theme CSS
   - Extract color scheme
   - Apply to map gallery

2. **Responsive Design**:
   - Ensure maps work on mobile
   - Test with forum's responsive breakpoints

3. **Font Matching**:
   - Use same font family as forum
   - Match font sizes

## Recommended Implementation Plan

### Phase 1: Coming Soon Page (v4) - Current
1. Create custom page at `/models`
2. Display "coming soon" message
3. Use provided HTML template (see `frontend/coming-soon.html`)
4. Keep page hidden or visible with coming soon message

### Phase 2: Basic Integration (v4)
1. Replace coming soon with iframe embed
2. Test with small user group
3. Verify maps load correctly

### Phase 3: Enhanced Integration (v4)
1. Switch to JavaScript integration
2. Match forum styling
3. Add filtering/search
4. Full public release

### Phase 4: Native Integration (v5)
1. Upgrade to v5
2. Create custom application
3. Full native integration
4. Enhanced features

## Testing Checklist

- [ ] Maps load correctly in Invision page
- [ ] Styling matches forum theme
- [ ] Mobile responsive
- [ ] CORS working properly
- [ ] Performance acceptable
- [ ] Error handling works
- [ ] Navigation link works
- [ ] Works for logged-in and guest users (if applicable)

## Support Resources

- [Invision Community Documentation](https://invisioncommunity.com/4docs/)
- [Invision Community v5 Preview](https://invisioncommunity.com/news/product-updates/)
- [Custom Pages Guide](https://invisioncommunity.com/4docs/administration/pages/)

## Notes

- Keep integration simple initially
- Can enhance after v5 upgrade
- Test thoroughly before public release
- Consider user feedback for improvements
