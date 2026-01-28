# Development Roadmap

**Last Updated:** January 27, 2026

**Current Status:** Backend deployed & stable; Radar, MSLP & Precip, and 850mb Temp/Wind/MSLP maps implemented. Next: further map expansion, frontend polish, extended hours.

---

## Current Status: Phase 5A - Backend Deployed & Stable ✅

### ✅ Phase 1 Complete - Technical Proof of Concept
- [x] Project structure
- [x] Basic API framework (FastAPI)
- [x] GFS data fetcher (AWS S3, GRIB parsing)
- [x] Regional subsetting (PNW: WA, OR, ID)
- [x] Map generation (4 variables: temp, precip, wind, precip type)
- [x] Forecast hours (0, 24, 48, 72 tested successfully)
- [x] US units (°F, inches, mph)
- [x] Basic API endpoints

### ✅ Phase 5A Complete - Backend Deployment
- [x] Digital Ocean droplet deployed (174.138.84.70)
- [x] API running on https://api.sodakweather.com
- [x] Systemd services configured (API + Scheduler)
- [x] Automated map generation every 6 hours
- [x] Real-time progressive monitoring (checks S3 every minute)
- [x] Multi-run retention (keeps last 4 runs/24 hours)
- [x] SSL certificate via Certbot
- [x] Basic frontend viewer deployed on sodakweather.com/models

### ✅ Enhanced Features Implemented
- [x] **0.25° GFS resolution** (4x higher detail than original 0.5°)
- [x] **GRIB file caching** (75% bandwidth reduction, 70% speed improvement)
- [x] **Station overlays** (shows forecast values at major PNW cities)
- [x] **Professional temperature colormap** (38-color gradient, fixed levels)
- [x] **Progressive generation** (generates f000 first, then f024, f048, f072)
- [x] **Multi-run API** (`/api/runs` endpoint for model comparison)
- [x] **Longitude fix** (handles 0-360° vs -180/180° coordinate systems)

**Current Capabilities:**
- 0.25° GFS resolution (46×78 grid points, ~15 mile spacing)
- 4 map types: temp, precip, wind speed, precip type
- 4 forecast hours: 0, 24, 48, 72
- Station overlays on maps (Seattle, Portland, Spokane, etc.)
- Professional-grade temperature gradient matching TropicalTidbits
- Real-time map generation as GFS data becomes available
- Multi-run comparison backend (frontend pending)

**What's Still Needed for Production:**
- 10-15 additional map types (winter weather focus)
- Extended forecast hours (every 3h to 48h, every 6h to 120h)
- Interactive slider/animation interface
- Run time selection dropdown (backend complete, frontend pending)
- GIF generation
- Mobile responsive design

---

## Phase 2: Map Quality & Resolution (Weeks 2-4)

**Goal**: Create production-quality maps comparable to TropicalTidbits

### Higher Resolution Data
- [x] ✅ Switch from 0.5° to 0.25° GFS files (finer detail)
  - ✅ Achieved: 46×78 points (~15 mile spacing)
  - ✅ Impact: 4x more data points, better terrain detail
  - ✅ Set as default resolution in production
- [x] ✅ Station overlays (shows forecast values at major cities)
- [x] ✅ Professional color scales (38-color temperature gradient)
- [x] ✅ Fixed color levels (consistent colors across all maps)
- [ ] Add terrain/elevation overlays
- [ ] Higher quality basemap features (topography, terrain shading)

### Additional Map Types (Priority Order)
Based on TropicalTidbits GFS products:

**High Priority (Winter Weather Focus):**
- [x] MSLP & Precipitation (rain/frozen)
- [x] 850mb Temperature, Wind, MSLP
- [ ] 500mb Height & Vorticity
- [ ] Simulated Radar Reflectivity
- [ ] Accumulated Snowfall (10:1 SLR)
- [ ] 24-hour Accumulated Precip
- [ ] 700mb Temperature Advection & Frontogenesis

**Medium Priority:**
- [ ] PWAT (Precipitable Water)
- [ ] 2m Dewpoint
- [ ] Surface Wind & Gusts
- [ ] 850mb Relative Humidity
- [ ] CAPE and Shear

**Lower Priority:**
- [ ] Upper level winds (250mb, 300mb)
- [ ] Potential Vorticity
- [ ] Various isentropic levels

### Extended Forecast Hours
- [ ] Generate every 3 hours: 0-48h (17 maps)
- [ ] Generate every 6 hours: 48-120h (12 maps)
- [ ] Optional: Every 12 hours: 120-240h (10 maps)
- [ ] Total per run: ~30-40 forecast hours per variable

---

## Phase 3: Interactive Frontend (Weeks 5-8)

**Goal**: Build TropicalTidbits-style interactive viewer

### Core Viewer Features
- [ ] **Slider/Animation Controls** (CRITICAL)
  - Play/pause button
  - Speed controls (FPS)
  - Step forward/backward through forecast hours
  - Click to jump to specific hour
  - Keyboard shortcuts (space, arrows)
  - Auto-loop animation

- [ ] **Run Time Selection**
  - Dropdown for available GFS runs
  - Show data availability status
  - "Latest" option
  - Historical runs (keep 7-10 days)

- [ ] **Run Time Selection** (Backend ✅ Complete)
  - Dropdown showing last 4 GFS runs (24 hours)
  - Display format: "00Z Jan 24 (Latest)"
  - Show relative age (e.g., "6h ago")
  - API: `/api/runs` returns available runs
  - API: `/api/maps?run_time=...` filters maps by run
  - Auto-cleanup keeps last 4 runs only
  - Enable forecast comparison between runs

- [ ] **Region Selection**
  - PNW (default)
  - Pacific Northwest + BC
  - West Coast (CA, OR, WA)
  - Western US
  - CONUS (future)

- [ ] **Variable/Package Selection**
  - Organized categories (precip, dynamics, thermodynamics)
  - Quick-switch between variables
  - Thumbnail previews
  - Favorite/pinned variables

### Advanced Features (TropicalTidbits-style)
- [ ] **GIF Generation**
  - Create animated GIFs from forecast sequence
  - Custom start/end hours
  - Custom speed
  - Download option

- [ ] **Comparison Mode**
  - Side-by-side different variables
  - Side-by-side different run times
  - Difference maps

- [ ] **Mobile Responsive**
  - Touch controls for slider
  - Pinch to zoom
  - Optimized for phone/tablet

- [ ] **Lat/Lon Readout**
  - Show coordinates on hover
  - Click for point forecast

### UI/UX Polish
- [ ] Loading indicators
- [ ] Smooth transitions
- [ ] Clean, minimal interface
- [ ] Match forum theme
- [ ] Fast image loading (preload next/previous)

### Progressive Loading System
- [ ] **manifest.json Generation** (Backend)
  - Generate manifest.json alongside each map
  - Include progress tracking (e.g., "8/16 maps complete")
  - Update after each map is saved
  - Include timestamps, run time, available forecast hours
  
- [ ] **Generation Status Endpoint** (Backend)
  - `/api/generation/status` endpoint
  - Returns real-time progress of current run
  - Shows which forecast hours are complete
  - Estimated time remaining
  
- [ ] **Progressive Polling** (Frontend)
  - Fetch manifest.json every 60 seconds during generation
  - Auto-update slider when new maps appear
  - Loading bar showing generation progress (e.g., "12/16 complete - 75%")
  - Smooth transitions as new forecast hours become available
  - No page refresh required - maps appear dynamically
  
- [ ] **User Experience Benefits**
  - Users see f000 (current) maps first (~1 minute)
  - Progressive appearance of f024, f048, f072 maps
  - Don't wait for full 4-5 minute generation
  - Clear visual feedback on what's loading
  - Can start viewing while rest generates

---

## Phase 4: Backend Optimization (Weeks 6-10)

### Performance Critical
- [x] ✅ **GRIB File Caching**
  - ✅ Cache downloaded files locally for 2-4 hours
  - ✅ Reuse for multiple variables/regions
  - ✅ Achievement: 75% bandwidth reduction, 70% speed improvement

- [ ] **Parallel Map Generation**
  - Generate multiple forecast hours simultaneously
  - Use multiprocessing pool
  - Reduce total time from 5-10 minutes to 1-2 minutes

- [x] ✅ **Progressive Generation**
  - ✅ Generate key hours first (f000, then f024, f048, f072)
  - ✅ Real-time monitoring checks S3 every minute
  - ✅ Maps appear as data becomes available (no waiting for full run)

- [ ] **Image Optimization**
  - Optimize PNG compression
  - WebP format option (smaller files)
  - Responsive image sizes

### Data Management
- [ ] **Efficient Storage**
  - Keep last 3-5 GFS runs (~1000-2000 images)
  - Automatic cleanup of old runs
  - Monitor disk space

- [ ] **Smart Scheduling**
  - Align with GFS availability (4-5 hours after run time)
  - Generate high-priority maps first
  - Retry failed maps
  - Alert on repeated failures

### API Enhancements
- [ ] **Fast Endpoints**
  - Image listing with metadata
  - Run time availability
  - Variable/package info
  - Latest map URLs

- [ ] **Caching Headers**
  - Proper cache-control
  - ETags
  - CDN-ready

---

## Phase 5: Production Deployment (3-Phase Approach)

**DEPLOYMENT STRATEGY**:
1. **Phase 5A (Current)**: Deploy basic backend infrastructure to Digital Ocean droplet
2. **Phase 5B (Next)**: Complete ALL features and enhancements, test comprehensively on sodakweather.com
3. **Phase 5C (Final)**: Launch fully polished, production-ready system on theweatherforums.com

**IMPORTANT**: theweatherforums.com deployment is the FINAL production launch, not an iterative deployment. All enhancements (higher resolution, 15+ map types, extended forecast hours, interactive slider UI) must be completed and tested on sodakweather.com BEFORE launching on theweatherforums.com.

---

### 🎯 PHASE 5A: Backend Deployment to DO Droplet ✅ COMPLETE

**Status**: ✅ DEPLOYED & STABLE  
**Timeline**: Completed January 2026  
**Domain**: https://api.sodakweather.com

#### Infrastructure Setup
- [x] ✅ Digital Ocean Droplet deployed (174.138.84.70)
- [x] ✅ System dependencies installed (Python 3.10, nginx, certbot)
- [x] ✅ Code transferred to droplet via Git
- [x] ✅ Python environment configured with virtual environment
- [x] ✅ Systemd services setup (API + Scheduler)
- [x] ✅ Firewall configured (UFW)
- [x] ✅ SSL certificate via Certbot
- [x] ✅ Automated map generation running every 6 hours (03:30, 09:30, 15:30, 21:30 UTC)
- [x] ✅ Real-time progressive monitoring (checks S3 every minute for 90 minutes)

#### Testing & Monitoring
- [x] ✅ API endpoints accessible at https://api.sodakweather.com
- [x] ✅ Maps generating successfully (0.25° resolution)
- [x] ✅ Scheduler running reliably with progressive monitoring
- [x] ✅ Station overlays displaying correctly
- [x] ✅ Professional temperature colormap implemented
- [x] ✅ Multi-run retention (keeps last 4 runs)
- [x] ✅ Frontend deployed at sodakweather.com/models

**Success Criteria Met**:
- ✅ API responds to health checks
- ✅ Maps generated automatically 4x daily
- ✅ System stable and producing accurate forecasts
- ✅ Fixed longitude coordinate bug (station overlays)
- ✅ Professional-grade map quality

**Deliverable**: Backend API running on droplet, generating high-quality maps automatically with progressive real-time monitoring

---

### 🎯 PHASE 5B: Complete Development & Testing on sodakweather.com (NEXT)

**Status**: 🚀 READY TO START (Backend stable)  
**Timeline**: 6-8 weeks development + comprehensive testing  
**Domain**: sodakweather.com/models (development & testing environment)

**CRITICAL**: ALL enhancements and features must be completed and tested on sodakweather.com BEFORE deploying to theweatherforums.com. This is NOT a minimal viable product - this is the production-ready system being tested.

#### Prerequisites
- Backend API stable for 1-2 weeks on droplet
- Maps generating reliably
- Ready to implement all Phases 2-4 enhancements

#### Backend Enhancements (Complete on sodakweather.com)
- [ ] Upgrade to 0.25° GFS resolution (4x more detail)
- [ ] Add 10-15 additional map types (winter weather focused)
- [ ] Extend forecast hours (every 3h to 48h, every 6h to 120h)
- [ ] Parallel map generation (performance optimization)
- [ ] Smart scheduling and caching
- [ ] Additional models (HRRR, NAM) if feasible

#### Frontend Development (Complete on sodakweather.com)
- [ ] Interactive slider/animation interface
- [ ] Run time selection dropdown
- [ ] Variable/map type selector
- [ ] GIF animation generation
- [ ] Play/pause controls with speed adjustment
- [ ] Mobile responsive design
- [ ] TropicalTidbits-style UX
- [ ] Nginx configured with SSL
- [ ] API proxy configured
- [ ] CORS properly set up

#### Comprehensive Testing (on sodakweather.com)
- [ ] All map types generating correctly
- [ ] Slider/animation working smoothly
- [ ] Performance testing (load times, responsiveness)
- [ ] Cross-browser testing (Chrome, Firefox, Safari, Edge)
- [ ] Mobile testing (iOS, Android)
- [ ] Beta user feedback from moderators/selected users
- [ ] Iterate and polish based on feedback
- [ ] Monitor system stability for 2-4 weeks

**Success Criteria**:
- ALL planned map types and features working
- Frontend loads quickly (< 2 seconds)
- Smooth animation with 40+ forecast hours per variable
- Maps display correctly on all devices and browsers
- System stable under test usage
- Positive feedback from beta testers
- NO major known bugs or issues

**Deliverable**: Fully production-ready system tested and refined on sodakweather.com

---

### 🎯 PHASE 5C: Production Launch on theweatherforums.com (Week 18-20)

**Status**: ⏳ WAITING (After complete system tested on sodakweather.com)  
**Timeline**: 1 week migration + final verification  
**Domain**: theweatherforums.com/models (FINAL PRODUCTION)

**NOTE**: This is the FINAL production launch of a complete, polished, production-ready system. All features, enhancements, and testing must be complete on sodakweather.com before this phase.

#### Prerequisites (ALL Must Be Met)
- ✅ All backend enhancements complete (0.25° resolution, 15+ map types, extended hours)
- ✅ Full frontend with slider/animation working perfectly
- ✅ Thoroughly tested on sodakweather.com for 2-4 weeks
- ✅ All beta user feedback incorporated
- ✅ System proven stable under test usage
- ✅ No known major bugs or issues
- ✅ Forum administrators ready for public launch

#### Migration Steps (Simple - Just Moving Tested Code)
- [ ] Copy tested frontend from sodakweather.com to theweatherforums.com
- [ ] Update nginx configuration on forum droplet
- [ ] Configure API proxy to models droplet
- [ ] Update DNS/configuration as needed
- [ ] Final smoke testing on production domain
- [ ] Add /models link to forum navigation
- [ ] Remove "Coming Soon" page

#### Public Launch
- [ ] Announce to forum users (forum post, newsletter)
- [ ] Monitor for any deployment-specific issues
- [ ] Gather user feedback
- [ ] Minor tweaks as needed (NOT major features)

#### Post-Launch Enhancements (Optional, Incremental)
- [ ] Additional map types based on user requests
- [ ] Minor UI/UX improvements
- [ ] New models if requested
- [ ] Performance optimizations if needed

**Success Criteria**:
- Polished, feature-complete maps accessible at theweatherforums.com/models
- Navigation link working
- Users can view 15+ map types with 40+ forecast hours each
- Smooth slider/animation interface
- No performance impact on forum
- System stable under real user load
- Positive user reception

**Deliverable**: Public production launch of complete, TropicalTidbits-style model viewer

---

### 📊 Deployment Architecture

**Option A: Current Plan (Recommended)**
```
┌─────────────────────────────────┐
│  Models Droplet (Separate)      │
│  - Backend API (port 8000)      │
│  - Map generation & storage     │
│  - Automated scheduler          │
└─────────────────────────────────┘
                 │
                 │ API calls
                 ↓
┌─────────────────────────────────┐
│  SoDak Weather (Testing)        │
│  - Frontend files               │
│  - Nginx proxy to API          │
│  - SSL/HTTPS                    │
└─────────────────────────────────┘
                 │
                 │ Migration when ready
                 ↓
┌─────────────────────────────────┐
│  The Weather Forums (Production)│
│  - Frontend files               │
│  - Nginx proxy to API          │
│  - Forum integration            │
└─────────────────────────────────┘
```

### Reliability & Monitoring (Ongoing)
- [ ] Comprehensive error handling
- [ ] Health check endpoint (/api/health)
- [ ] Logging system
- [ ] Disk space monitoring
- [ ] CPU/Memory monitoring
- [ ] Email alerts for failures
- [ ] Backup strategy for images

### Resource Planning
- **Models Droplet**: $12-24/month (1-2GB RAM, 25GB disk)
- **Bandwidth**: ~600 MB per GFS run (4 runs/day = 2.4 GB/day)
- **Storage**: ~100-200 MB per run × last 5 runs = 1GB images max
- **CPU**: Moderate during map generation (every 6 hours for ~5 min)

---

## Phase 6: Integration & Launch (Weeks 12-16)

### Invision Community Integration
- [ ] Custom page development
- [ ] Forum navigation link
- [ ] Theming to match forum
- [ ] Mobile-optimized
- [ ] Beta testing with moderators

### User Experience
- [ ] Tutorial/help system
- [ ] Map interpretation guide
- [ ] FAQ
- [ ] Feedback mechanism

### Soft Launch
- [ ] Beta release to forum moderators
- [ ] Gather feedback
- [ ] Fix issues
- [ ] Announce to select users
- [ ] Monitor usage and performance

### Public Release
- [ ] Announcement post
- [ ] User documentation
- [ ] Support plan
- [ ] Monitoring alerts

---

## Future Enhancements (Post-Launch)

### Additional Models
- [ ] HRRR (hourly, high-res, short-range)
- [ ] NAM (mesoscale)
- [ ] Ensemble models (GEFS)
- [ ] Graphcast (ML-based)
- [ ] Model comparison view

### Advanced Features
- [ ] Point soundings (click for vertical profile)
- [ ] Meteograms (time series for location)
- [ ] Ensemble probability maps
- [ ] Model verification/skill scores
- [ ] User accounts & preferences
- [ ] Email/SMS alerts for significant weather

---

## Key Milestones & Reality Check

### Milestone 1: Technical Foundation ✅ (CURRENT)
**Status**: Complete  
**Time**: 2 weeks  
**Deliverable**: Working GFS fetching + basic map generation

### Milestone 2: TropicalTidbits-Quality Maps
**Status**: Not Started  
**Estimated Time**: 4-6 weeks  
**Complexity**: High
- Higher resolution data
- 20+ map types
- Extended forecast hours (every 3-6h to 120h+)
- Professional cartography

### Milestone 3: Interactive Viewer
**Status**: Not Started  
**Estimated Time**: 6-8 weeks  
**Complexity**: High
- Slider/animation interface
- Run time selection
- Variable switching
- GIF generation
- Mobile responsive

### Milestone 4: Production Deployment
**Status**: Not Started  
**Estimated Time**: 2-3 weeks  
**Complexity**: Medium
- Droplet setup
- Optimization
- Monitoring
- Testing

### Milestone 5: Forum Integration & Launch
**Status**: Not Started  
**Estimated Time**: 3-4 weeks  
**Complexity**: Medium
- Invision integration
- Beta testing
- Polish
- Launch

---

## Realistic Timeline

### Conservative Estimate
- **Technical Foundation**: ✅ 2 weeks (DONE)
- **Map Quality**: 4-6 weeks
- **Interactive Frontend**: 6-8 weeks
- **Optimization & Deployment**: 2-3 weeks
- **Integration & Testing**: 3-4 weeks
- **Total**: 17-23 weeks (~4-6 months)

### Aggressive Estimate
- **Map Quality**: 3-4 weeks
- **Interactive Frontend**: 4-6 weeks
- **Deployment**: 1-2 weeks
- **Integration**: 2-3 weeks
- **Total**: 12-17 weeks (~3-4 months)

**Your Deadline**: Fall 2026 (9-10 months away)  
**Status**: ✅ Achievable but requires consistent effort

---

## Priority Order (Updated)

### Phase A: Map Quality (Do This First)
1. Higher resolution (0.25° GFS data)
2. More map types (10-15 most useful for winter weather)
3. Extended forecast hours (every 3h to 48h, every 6h to 120h)
4. Better cartography (contours, labels, legends)

### Phase B: Frontend Viewer (Core Feature)
1. Slider/animation interface
2. Run time selection
3. Variable selection
4. Basic responsive design

### Phase C: Optimization
1. Parallel generation
2. GRIB caching
3. Fast API responses

### Phase D: Deployment
1. Production server setup
2. Monitoring
3. Testing

### Phase E: Integration
1. Forum integration
2. Beta testing
3. Launch

---

## Success Criteria (Updated)

**MVP (Minimum Viable Product):**
- ✅ 10+ map types for PNW region
- ✅ Forecast hours every 3-6h out to 120h
- ✅ Slider/animation interface
- ✅ Run time selection (last 2-3 days)
- ✅ Mobile responsive
- ✅ Automatic updates every 6 hours
- ✅ Fast loading (< 3 seconds per map)

**Nice to Have (Post-MVP):**
- Multiple regions
- Multiple models
- GIF generation
- Advanced features (soundings, etc.)
- Model comparison

---

## Next Immediate Steps

1. Wait for comprehensive test results
2. Implement automated scheduling (basic)
3. **Start Phase 2: Map Quality**
   - Research 0.25° GFS data access
   - Identify 10-15 most useful map types for winter weather
   - Plan extended forecast hours
4. **Start Phase 3: Frontend Design**
   - Design slider interface
   - Plan API endpoints for frontend
   - Prototype animation controls

## Phase 2: Automation (Week 3)

### Scheduled Processing
- [ ] Scheduler implementation
- [ ] Automatic data fetching
- [ ] Automatic map generation
- [ ] Job queue (optional)
- [ ] Error recovery

### Storage Management
- [ ] Image cleanup (old maps)
- [ ] Storage monitoring
- [ ] Compression options
- [ ] S3/Spaces integration (optional)

## Phase 3: Production Setup (Week 4)

### Deployment
- [ ] Digital Ocean droplet setup
- [ ] Systemd service configuration
- [ ] Nginx reverse proxy
- [ ] SSL certificate
- [ ] Monitoring setup

### Performance
- [ ] Caching strategy
- [ ] Image optimization
- [ ] API response optimization
- [ ] Load testing

## Phase 4: Integration (Week 5)

### Frontend
- [ ] Map gallery page
- [ ] Filtering interface
- [ ] Map viewer
- [ ] Responsive design
- [ ] Integration with theweatherforums.com

### Features
- [ ] User preferences
- [ ] Favorite maps
- [ ] Map comparison
- [ ] Historical maps

## Phase 5: Enhancement (Ongoing)

### Advanced Features
- [ ] Multiple model comparison
- [ ] Animation/GIF generation
- [ ] Custom map overlays
- [ ] Export options
- [ ] API rate limiting
- [ ] Authentication

### Optimization
- [ ] Parallel processing
- [ ] Incremental updates
- [ ] Smart caching
- [ ] CDN integration

## Priority Features

### High Priority
1. ✅ Basic GFS data fetching
2. ✅ Core map generation
3. ✅ API endpoints
4. 🔄 Scheduled processing
5. 🔄 Production deployment

### Medium Priority
1. Graphcast support
2. More variables
3. Frontend integration
4. Error handling improvements

### Low Priority
1. Advanced visualizations
2. Animations
3. User accounts
4. Analytics

## Success Metrics

- [ ] Successfully fetch GFS data
- [ ] Generate accurate maps
- [ ] Serve maps via API
- [ ] Automatic updates every 6 hours
- [ ] < 5 second API response time
- [ ] < 1% error rate
- [ ] Integration with theweatherforums.com
