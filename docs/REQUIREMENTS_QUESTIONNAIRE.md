# Requirements Questionnaire

Use this questionnaire to clarify your specific needs and preferences for the TWF Weather Models project.

## Technical Preferences

### 1. Programming & Framework
- [ ] **Python version preference?** (I've set up Python 3.10+, but do you have a preference?)
- [ ] **API framework preference?** (I used FastAPI - are you comfortable with it, or prefer Flask/Django?)
- [ ] **Database needed?** (Currently using filesystem - do you want a database for metadata, user preferences, etc.?)
- [ ] **Containerization?** (Docker/Docker Compose for easier deployment?)

### 2. Deployment & Infrastructure
- [ ] **Digital Ocean droplet size?** (Start with $12/month or go bigger?)
- [ ] **Storage preference?** (Local filesystem vs DO Spaces vs AWS S3?)
- [ ] **Domain setup?** (Subdomain like `models.theweatherforums.com` or path like `theweatherforums.com/models`?)
- [ ] **SSL/HTTPS?** (Let's Encrypt free cert, or do you have existing cert?)
- [ ] **CDN?** (Cloudflare free tier, or existing CDN?)

## Weather Data & Models

### 3. Data Sources Priority
- [ ] **Which models first?** (GFS only to start, or also Graphcast?)
- [ ] **GFS resolution?** (0.25° high-res, 0.5° medium, or 1° low-res for faster processing?)
- [ ] **GFS source preference?** (AWS S3 - free/no limits, or NOMADS - direct but rate-limited?)
- [ ] **Graphcast access?** (Do you have API access, or need to set up local model?)

### 4. Variables & Forecasts
- [ ] **Which variables are most important?** (Priority order)
  - Temperature (2m)
  - Precipitation
  - Wind speed/direction
  - Pressure
  - Humidity
  - Cloud cover
  - Other: _______________
- [ ] **Which forecast hours?** (0, 6, 12, 24, 48, 72, 96, 120 hours - all or subset?)
- [ ] **How many forecast hours to generate?** (All, or just key ones like 0, 24, 48, 72?)

### 5. Map Regions
- [ ] **Primary region focus?** (US only, North America, Global, or specific regions?)
- [ ] **Multiple regions needed?** (US, Europe, Asia-Pacific, etc.?)
- [ ] **Custom boundaries?** (Specific states, counties, or areas?)

## Map Design & Visualization

### 6. Map Appearance
- [ ] **Map style preference?** (Professional/clean, colorful, minimalist?)
- [ ] **Color schemes?** (Standard weather colors, custom palettes?)
- [ ] **Map size/resolution?** (1920x1080 default - need different sizes?)
- [ ] **Map projections?** (Lambert Conformal for US, Mercator, Plate Carree, or multiple options?)
- [ ] **Overlays needed?** (State borders, county lines, cities, topography?)

### 7. Map Features
- [ ] **Contour lines?** (Yes/No, and how many levels?)
- [ ] **Wind barbs/arrows?** (For wind maps?)
- [ ] **Labels?** (City names, state names, etc.?)
- [ ] **Legend style?** (Horizontal, vertical, embedded?)
- [ ] **Title/header info?** (What metadata to display: model, run time, forecast hour, valid time?)

## User Experience & Integration

### 8. Forum Integration
- [ ] **What platform is theweatherforums.com?** (WordPress, phpBB, vBulletin, custom, other?)
- [ ] **Integration method preference?** 
  - [ ] Direct image links in posts
  - [ ] Embedded gallery page
  - [ ] Widget/shortcode
  - [ ] Full custom page
- [ ] **User access?** (Public, members only, or specific user groups?)
- [ ] **Authentication needed?** (Use forum login, or separate API keys?)

### 9. Frontend Features
- [ ] **Map gallery needed?** (Grid view, list view, or both?)
- [ ] **Filtering options?** (By model, variable, forecast hour, date?)
- [ ] **Search functionality?** (Search by date, model run, etc.?)
- [ ] **Map comparison?** (Side-by-side comparison of different runs/variables?)
- [ ] **Animation/GIFs?** (Animated loops of forecast progression?)
- [ ] **Download options?** (Allow users to download full-resolution images?)

### 10. User Interface
- [ ] **Mobile responsive?** (Important for mobile users?)
- [ ] **Dark mode?** (Match forum theme, or light/dark toggle?)
- [ ] **Thumbnails?** (Show thumbnails in gallery, click for full size?)
- [ ] **Lazy loading?** (Load images as user scrolls?)

## Performance & Scale

### 11. Update Frequency
- [ ] **How often to update?** (Every 6 hours with GFS runs, or different schedule?)
- [ ] **Real-time vs scheduled?** (Generate on-demand or pre-generate all maps?)
- [ ] **How long to keep maps?** (Last 7 days, 30 days, or all time?)

### 12. Traffic Expectations
- [ ] **Expected users?** (How many forum members might use this?)
- [ ] **Expected page views?** (Rough estimate of daily/weekly views?)
- [ ] **Peak usage times?** (When do most users access the forum?)

### 13. Performance Requirements
- [ ] **API response time target?** (< 1 second, < 5 seconds acceptable?)
- [ ] **Image load time?** (Optimize for fast loading?)
- [ ] **Concurrent users?** (How many simultaneous users expected?)

## Features & Functionality

### 14. Advanced Features (Future)
- [ ] **Model comparison?** (Compare GFS vs Graphcast side-by-side?)
- [ ] **Ensemble data?** (GFS ensemble members if available?)
- [ ] **Historical data?** (Archive and display past forecasts?)
- [ ] **Alerts/notifications?** (Notify users of new maps or significant weather?)
- [ ] **Custom map requests?** (Allow users to request specific maps?)
- [ ] **API for developers?** (Public API for other developers to use?)

### 15. Analytics & Monitoring
- [ ] **Usage tracking?** (Track which maps are viewed most?)
- [ ] **Error monitoring?** (Email alerts, Slack notifications, or logging only?)
- [ ] **Performance monitoring?** (Track processing times, API response times?)

## Maintenance & Operations

### 16. Maintenance Preferences
- [ ] **Who will maintain?** (You, team member, or need automated as much as possible?)
- [ ] **Update frequency?** (How often can you update code/features?)
- [ ] **Backup strategy?** (Automated backups of images/config?)
- [ ] **Monitoring access?** (Dashboard, email reports, or just logs?)

### 17. Budget Constraints
- [ ] **Strict budget limit?** (Must stay under $X/month?)
- [ ] **Willing to scale up?** (Start small, scale if needed?)
- [ ] **One-time costs OK?** (Any budget for initial setup?)

## Timeline & Priorities

### 18. Timeline
- [ ] **Target launch date?** (Specific date, or "as soon as possible"?)
- [ ] **Phased rollout OK?** (MVP first, then add features?)
- [ ] **Testing period?** (Private beta with select users first?)

### 19. Feature Priorities
- [ ] **Must-have features?** (What's absolutely essential for launch?)
- [ ] **Nice-to-have features?** (What can wait for v2?)
- [ ] **Future enhancements?** (Ideas for later versions?)

## Specific Technical Questions

### 20. Your Environment
- [ ] **Your Python experience?** (Beginner, intermediate, advanced?)
- [ ] **Comfortable with Linux/server admin?** (Can you manage droplet, or need more automation?)
- [ ] **Git/GitHub experience?** (Comfortable with version control?)
- [ ] **Preferred development workflow?** (Local dev, then deploy, or direct on server?)

### 21. Existing Infrastructure
- [ ] **Existing server infrastructure?** (Do you have other servers/services running?)
- [ ] **Existing monitoring tools?** (Using any monitoring services already?)
- [ ] **Existing CDN?** (Already using Cloudflare or other CDN?)
- [ ] **Existing domain setup?** (How is theweatherforums.com currently hosted?)

## Questions About Your Vision

### 22. Overall Goals
- [ ] **Primary goal?** (Provide useful tool for forum users, showcase technical skills, learn weather data, other?)
- [ ] **Success metrics?** (What would make this project successful for you?)
- [ ] **Long-term vision?** (Expand to more models, add mobile app, commercialize, other?)

### 23. User Experience Vision
- [ ] **How should users discover maps?** (Browse gallery, search, direct links in posts?)
- [ ] **How should maps be shared?** (Direct links, embed codes, social sharing?)
- [ ] **What's the primary use case?** (Quick reference, detailed analysis, educational, other?)

---

## How to Use This Questionnaire

1. **Answer the questions** that are most relevant to your needs
2. **Skip questions** you're unsure about - we can decide together
3. **Prioritize** - mark which items are most important
4. **Share your answers** and I'll customize the project accordingly

## Quick Priority Questions (If Short on Time)

If you want to get started quickly, answer these 5 key questions:

1. **Which weather variables are most important to you?** (Top 3-5)
2. **What region should maps focus on?** (US, specific area, global?)
3. **What platform is theweatherforums.com?** (WordPress, phpBB, custom?)
4. **How do you want users to access maps?** (Gallery page, direct links, embedded?)
5. **What's your timeline?** (ASAP, specific date, flexible?)

These will help me prioritize the most important features first!
