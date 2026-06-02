# AutoPoster — Complete User Workflow
> Every screen, every action, every decision point from start to finish.

---

## 1. LANDING PAGE

User arrives at the homepage.

**Sees:**
- Headline: "Manage your Facebook Page posts without touching the API"
- Subheadline: "AI writes, schedules, and publishes your posts automatically"
- Two buttons: **Get Started Free** and **Login**
- Brief feature list: AI post generation, image generation, auto scheduling, analytics

**Actions:**
- Click **Get Started Free** → goes to Registration
- Click **Login** → goes to Login

---

## 2. REGISTRATION

**Sees:** Form with email, password, confirm password fields.

**Flow:**
1. User fills form and submits
2. System validates — email not already registered, passwords match, minimum 8 chars
3. On error → red message below the failing field
4. On success → system sends verification email, shows message: "Check your email to verify your account"

**No social login. Email only.**

---

## 3. EMAIL VERIFICATION

User opens email, clicks verification link.

**Flow:**
1. Link contains a token, hits `/auth/verify-email?token=xxx`
2. Backend validates token
3. On valid → marks user as verified, redirects to Login with message: "Email verified. Please log in."
4. On expired/invalid → shows: "Verification link expired. Request a new one." with resend button

---

## 4. LOGIN

**Sees:** Email and password fields, Login button, "Forgot password" link.

**Flow:**
1. User submits credentials
2. On wrong credentials → "Invalid email or password"
3. On unverified email → "Please verify your email first" with resend link
4. On success → backend returns JWT token, frontend stores it, redirects to Dashboard

---

## 5. DASHBOARD — FIRST TIME (Empty State)

User lands here after first login. No pages connected yet.

**Sees:**
- Welcome message: "Welcome to AutoPoster. Let's get you set up."
- Step tracker showing 7 steps, Step 1 highlighted:
  ```
  Step 1 → Connect your Facebook Page        [Do this now]
  Step 2 → Build your first AI Persona       [Locked]
  Step 3 → Build your custom prompt          [Locked]
  Step 4 → Generate and publish first post   [Locked]
  Step 5 → Set up auto posting schedule      [Locked]
  Step 6 → Let system learn for 7 days       [Not started]
  Step 7 → Review your first performance report [Not started]
  ```
- Large **Connect Facebook Page** button (Facebook blue, Facebook logo icon)

**Actions:**
- Click Connect Facebook Page → starts OAuth popup flow (Section 6)

---

## 6. FACEBOOK PAGE CONNECTION

### 6a — Popup Opens
- Frontend opens 600×700px centered popup
- Button changes to "Connecting..." and disables
- Popup navigates to `/auth/facebook/start` on backend
- Backend generates random state, stores in session, redirects popup to Facebook

### 6b — Inside the Popup (Facebook's UI)
- User sees Facebook login screen if not already logged in
- User logs into Facebook
- Facebook shows permission approval screen listing:
  - Manage your Pages
  - Read Page engagement data
  - Show list of Pages you manage
- User clicks **Continue**

### 6c — Page Selection (if user manages multiple pages)
- Popup shows list of user's Facebook Pages as selectable cards
- Each card shows page profile picture and page name
- User clicks the page they want to connect
- User clicks **Confirm**

### 6d — Backend Saves Connection
- Backend checks if this page is already connected by this user
  - Yes, same user → updates token, restores history, increments reconnect_count
  - Yes, different user (active) → popup shows error: "This page is already connected to another account"
  - No → creates new row in page_connections
- Popup sends success message to parent window
- Popup closes itself automatically

### 6e — Dashboard Refreshes
- Connect button re-enables
- Success toast: "Facebook Page connected successfully"
- Dashboard now shows the connected page card
- Step 1 in step tracker marked Done ✓
- Step 2 unlocks

---

## 7. DASHBOARD — AFTER CONNECTION

**Left Sidebar (always visible):**
```
[Logo]
─────────────
Dashboard
Create Post
Scheduled Posts
Published Posts
AI Personas
Prompt Studio
AI Models
Analytics
Style Analyzer
Page Tracker
Media Library
Settings
─────────────
[Page profile pic] Page Name
Connected ●
```

**Main Area — Three Zones:**

**Zone 1 — Status Bar:**
- Next scheduled post: "[Post preview] publishes in 23 minutes"
- Last published post: "[Preview] — 14 likes, 3 comments"
- Connection health: green dot if healthy, amber/red if token issue
- Scheduler health: green dot if cron-job.org pinged in last 10 min

**Zone 2 — What System Has Learned (shows after 7+ days of data):**
- Best performing post this week
- Best performing time slot
- Best performing persona

**Zone 3 — What You Should Do Next:**
- Prioritized action list from AI analysis
- Example: "Your prompt has not been set up yet → [Set Up Prompt]"
- Example: "No posts scheduled this week → [Create Post]"
- Example: "Educational persona gets 3x more comments → [Add More Slots]"

**Step tracker updates dynamically based on what user has completed.**

---

## 8. AI MODELS SETTINGS
*(Do this before creating personas — sets which AI to use)*

Sidebar → **AI Models**

**Sees:** One section per task category:

| Task | Default Provider | Default Model |
|---|---|---|
| Post Generation | Mistral | mistral-large-latest |
| Post Analysis | Mistral | mistral-large-latest |
| Image Generation | Fal.ai | FLUX.1-schnell |
| Style Analysis | Mistral | mistral-large-latest |
| Image Prompt Generation | Mistral | mistral-small-latest |
| Recommendations | Mistral | mistral-large-latest |

**For each section:**
- Provider dropdown: Mistral / OpenAI / Anthropic / Google Gemini / Fal.ai / Stability AI / DALL-E
- Model dropdown: updates based on provider
- API Key field (encrypted on save)
- Test button → makes minimal test call, shows "✓ Working" or error
- Cost estimate label

**API Key section below:**
- Mistral → "Included free (platform pays)"
- All others → "Uses your API key"
- Provider grayed out if no key entered

**Save button** → saves all selections.

---

## 9. AI PERSONAS
*(Define who posts, when, and in what style)*

Sidebar → **AI Personas**

### 9a — Personas List Page

**Sees:**
- Weekly calendar grid at top — 7 columns (days), persona colors fill assigned days
- Gray days = no persona assigned = no auto posts that day
- Persona cards below (max 5 per page)
- Each card shows: persona name, assigned days, tone tags, status badge, Edit/Pause/Delete buttons
- **Add New Persona** button

### 9b — Create/Edit Persona Form

**Section 1 — Identity:**
- Persona Name (e.g. "Motivational Mondays")
- Which page this persona posts to (dropdown if multiple pages)

**Section 2 — Assigned Days:**
- 7 toggle buttons: Mon Tue Wed Thu Fri Sat Sun
- Warning if day already taken by another persona

**Section 3 — Posting Times:**
- Up to 4 time slots (time pickers)
- User's timezone shown next to each picker

**Section 4 — Content Settings:**
- Niche text input
- Tone tags (multi-select): Professional/Casual/Funny/Inspirational/Educational/Promotional/Bold/Friendly
- Language dropdown
- Hashtag toggle + count (max 5 recommended, warning shown above 5)

**Section 5 — Auto Posting:**
- Toggle: Enable automatic AI posting
- When on:
  - Max posts per day (default 2, max 24)
  - Active hours (start time → end time)

**Section 6 — Image Settings:**
- Toggle: Include image with auto posts
- Image frequency: Every post / Every other / 1 in 3 / 1 in 5 / Weekends only
- Image prompt source: Persona prompt / Generate from post / Use library image
- Fallback policy if image fails: Publish text only / Skip post / Use library image
- Max wait for image (slider: 10 seconds to 180 seconds)

**Section 7 — Learning Controls:**
- Learning Mode toggle (on = system adapts behavior based on performance)
- Reset Learning button (resets performance score to 0.5)
- Minimum engagement threshold input

**Save Persona** button.

### 9c — Persona Performance Card (after 20+ posts)
Each persona card shows:
- Performance score bar (0 to 1)
- Trend arrow (improving/declining)
- Best time slot for this persona
- Posting frequency status (all slots / reduced / 50% / paused)

---

## 10. PROMPT STUDIO
*(Build the exact instructions the AI uses to write posts)*

Sidebar → **Prompt Studio** → two tabs: **Text Prompt** | **Image Prompt**

### 10a — Text Prompt Tab

**Left side — Gap Fill Questions (animate in one at a time):**

**Section A — Identity:**
1. "What is this page about?" → text input
2. "Who is your audience?" → text input
3. "What is the main goal?" → multiple choice + custom
4. "What is your brand personality?" → multi-select tags (max 4)

**Section B — Content Rules:**
5. "Topics to always write about" → tag chips input
6. "Topics to NEVER write about" → tag chips input
7. "What every post must include" → checklist + custom additions
8. "What posts must never do" → checklist + custom additions
9. "Post length" → slider (Short/Medium/Long) + "Vary automatically" toggle

**Section C — Format:**
10. "Post structure" → dropdown (No fixed / Hook-Value-CTA / Story-Lesson / List / Statement)
11. "Example posts you love" → paste up to 5 examples, AI studies style
12. "Language" → dropdown or "Auto-detect from examples"

**Section D — Advanced:**
13. "Any additional instructions" → free text area (write anything)
14. "Creative vs Safe" → slider 1-10

**Template picker at top:**
Dropdown: E-commerce / Personal Brand / Restaurant / Real Estate / Fitness Coach / Educational / News / Motivational / Tech / Custom

**Right side — Live Prompt Preview (scrolls independently):**
- Two tabs: Simple View (readable paragraph) | Raw View (editable prompt string)
- Updates in real time with typing animation as user fills questions
- **Test This Prompt** button → calls Mistral, shows generated post in popup modal
- **Regenerate** button in modal for fresh sample
- **Save Prompt** button → saves assembled prompt to prompt_templates table

### 10b — Image Prompt Tab

**Questions:**
1. "What should the image show?" → large text area
2. "Visual style" → style tag chips (Photorealistic/Digital Art/Minimalist/Cinematic/Vintage/etc)
3. "Mood/emotion" → mood tag chips
4. "Dominant colors" → preset palette cards + custom color input
5. "What should NOT appear" → text input (negative prompt)
6. "Aspect ratio" → three clickable cards: Square 1:1 / Landscape 16:9 / Portrait 4:5
7. "Include text overlay?" → toggle, if yes: text input + font style + position + color
8. "Reference images for style" → upload up to 3 images
   - System sends each to vision LLM, extracts style descriptors automatically
   - Shows extracted descriptors as chips user can remove

**Right side — Live assembled image prompt preview**
- **Test — Generate Sample** button → generates image, shows in preview (does not publish)
- **Save Image Prompt** button

---

## 11. CREATE POST (Manual)

Sidebar → **Create Post**

**Sees top to bottom:**

**1 — Page selector**
- Dropdown if multiple pages
- Hidden if only one page (just shows page name + picture as label)

**2 — Persona selector**
- Optional — user can associate this manual post with a persona for analytics tracking

**3 — Generate with AI section**
- Shows only if persona has prompt configured
- Optional topic hint input: "Optional: give a topic hint..."
- **Generate with AI** button (purple/gradient color)
- After generation: text fades into text area, "Generated by AI — feel free to edit" label appears
- **Regenerate** button appears for fresh version
- Last 3 generated versions shown as small thumbnails to switch between

**4 — Text area**
- Large, resizable
- Character counter below: "[n] / 63,206"
- Counter turns yellow < 500 remaining, red < 100 remaining
- Publish button disabled if count < 0

**5 — Link preview**
- If URL pasted in text area, auto-fetches Open Graph metadata
- Shows preview card (image, title, description)
- X button to remove preview

**6 — Media attachment**
- Image/video upload button
- Max 10 images OR 1 video (not both)
- Image constraints: JPG/PNG, max 4MB each
- Thumbnails show after upload with remove X on each

**7 — Add Generated Image section**
- **Generate Image** button → opens image generation flow (Section 12)
- Or **Choose from Library** → opens media library picker

**8 — Schedule toggle**
- "Post Now" (default) or "Schedule for Later"
- If Schedule: date-time picker appears
- Timezone label shown: "Asia/Dhaka (UTC+6)"
- System converts to UTC before storing

**9 — Action buttons**
- **Save as Draft** | **Publish Now** or **Schedule** | **Cancel**

**On Publish Now click:**
- Button → "Publishing..." (disabled)
- Backend calls Facebook Graph API
- Success → green toast "Published to Facebook successfully", text area clears
- Failure → red toast "Publishing failed. Please try again." text preserved

**On Schedule click:**
- Button → "Scheduling..."
- Success → green toast "Scheduled for [date time in user's timezone]"

---

## 12. IMAGE GENERATION FLOW

Triggered from Create Post or Persona auto-post.

**12a — Generation starts:**
- User clicks **Generate Image**
- If from Create Post: shows image prompt settings used (from persona or default)
- User can override any field before generating
- User sets max wait time (10-180 seconds, default 120)
- Clicks **Generate**

**12b — While generating (polling every 3 seconds):**
- Progress animation with rotating messages:
  - "Preparing your image..."
  - "AI is painting..."
  - "Adding details..."
  - "Almost ready..."
- Estimated time shown based on provider
- Cancel button available

**12c — On completion:**
- Image appears in preview panel
- Generation time shown: "Generated in 6 seconds (Fal.ai FLUX.1-schnell)"

**12d — User options:**
- **Regenerate** → new image same prompt
- **Variations** → 3 more variations, shows all 4 as grid
- **Edit Prompt and Regenerate** → editable prompt field appears
- **Download** → full resolution
- **Add to Post** → attaches to composer, user then writes/generates caption
- **Save to Library** → saves without posting

**12e — On failure/timeout:**
- "Image generation failed: [reason]" with Retry button
- Or "Exceeded [n] second limit. Check your Media Library in a few minutes."

---

## 13. SCHEDULED POSTS

Sidebar → **Scheduled Posts**

**Sees:** List sorted by scheduled time, earliest first.

**Each post card shows:**
- Page name + profile picture
- Post text preview (truncated at 120 chars, "see more" expands)
- Image thumbnail if attached
- Scheduled time in user's timezone
- Status badge: Scheduled (blue) / Paused (amber)
- Three buttons: **Edit** | **Reschedule** | **Delete**

**Paused posts** (from disconnected page) show amber badge and message: "Paused — reconnect page to resume"

**Edit** → opens full composer pre-filled
**Reschedule** → opens small modal with only date-time picker
**Delete** → confirmation modal: "Are you sure? This cannot be undone." red Delete + Cancel

---

## 14. PUBLISHED POSTS

Sidebar → **Published Posts**

**Filter bar at top:**
- Show All | Manual Only | AI Generated Only | Auto Generated Only
- Date range picker

**Each post card shows:**
- Page name + profile picture
- Post text preview
- Image thumbnail if post had image
- Published time
- Status badge: Published (green) / Failed (red) / Missed (gray) / Permanently Failed (dark red)
- If AI generated: small sparkle icon + "AI Generated" label (purple)
- If auto generated: "Auto" badge
- Engagement metrics: Likes / Comments / Shares / Reach
- Refresh icon next to metrics (fetches fresh data from Facebook)
- **Delete from Facebook** button → confirmation modal → calls Graph API delete + removes from list

---

## 15. ANALYTICS

Sidebar → **Analytics**

**Date range selector:** Last 7 Days / Last 30 Days / Last 3 Months / Custom

**Top row — 4 stat cards:**
- Total Posts Published
- Total Likes
- Total Comments
- Total Shares + Reach

**Charts:**

**Posts per day line chart:**
- X axis: dates in range
- Y axis: post count (zero days shown as 0, not skipped)
- Y max = highest day count + 2

**Engagement heatmap:**
- 7 columns (days) × 24 rows (hours)
- Cells colored white → deep green by average engagement score
- Darker = better performance at that day/time

**Persona comparison bar chart:**
- One bar per persona, color-coded
- Shows performance score side by side

**Top 3 Posts this period:**
- Cards showing post preview + full metrics + persona name

**AI Recommendations panel:**
- 3-5 plain-language insights generated weekly by Mistral
- Example: "Posts published Tuesday 7PM get 3x more comments than any other slot"
- Example: "Your Motivational persona outperforms Educational by 40%"
- Dismiss button on each recommendation
- Refreshes every Sunday midnight automatically

---

## 16. STYLE ANALYZER

Sidebar → **Style Analyzer**

**Two modes (tabs):**

### Mode 1 — Analyze My Page (automatic)
- Dropdown to select which connected page to analyze
- **Run Analysis** button
- Progress messages: "Fetching recent posts..." → "Analyzing patterns..." → "Generating summary..."
- Shows full report (see below)

### Mode 2 — Analyze Any Page (manual)
- Instruction: "Visit any Facebook Page, copy their recent posts, paste them below"
- Up to 10 text boxes, each for one post
- Add Post box / Remove buttons
- **Analyze These Posts** button
- Same report output

**Analysis Report contains:**
- **Writing Style Profile:** avg word count, sentence structure, reading level, most used words (word cloud), % posts ending with question, % using emojis, avg emoji count, % using hashtags
- **Content Topics:** topic cluster visual (tag cloud, bigger = more frequent)
- **Posting Behavior:** best days bar chart, best times shown on 24hr grid, avg posts/week
- **Top 5 Posts:** highest engagement posts with full text and metrics
- **AI Style Summary:** one paragraph in plain English describing the writing style

**Bottom of report:**
- **Apply This Style to My Persona** button → modal to select which persona → updates that persona's prompt in Prompt Studio

---

## 17. PAGE TRACKER

Sidebar → **Page Tracker**

**Sees:**
- Add Page button
- List of tracked pages (max 10) as cards
- Each card shows: nickname, Facebook URL, tracking since date, last updated, badge: "Auto-sync active" or "Manual updates only", post count tracked

**Add Page modal:**
- Page URL or ID input
- Nickname input (e.g. "Competitor A", "Industry Leader")
- System attempts RSS feed at `https://www.facebook.com/feeds/page.php?id={id}&format=rss20`
- If RSS works → badge shows "Auto-sync active" (updates daily)
- If RSS fails → badge shows "Manual updates only"

**Each tracked page card — Add Posts button:**
- Opens modal with multiple text boxes for pasting posts manually
- Save button → posts saved to tracked_page_posts table with today's date

**Main feed view:**
- All posts from all tracked pages, last 7 days
- Sorted by engagement score (highest first)
- Each post card: page nickname, post text, estimated engagement, date
- **Use as Style Inspiration** button → adds this post to Prompt Studio style examples

**Comparison table:**
- All tracked pages side by side
- Columns: Posts/week, Avg likes, Avg comments, Avg shares, Most active day, Top topics

**Trending topic alert banner (when detected):**
- "Trending in your niche this week: [topic]"
- "3 pages you track posted about this with high engagement"
- **Generate Post on This Topic** button → pre-fills topic hint in Create Post

**Weekly reminder notification** per tracked page:
- "You haven't added new posts for [Page Name] in 7 days. Visit their page and update your tracking."

---

## 18. MEDIA LIBRARY

Sidebar → **Media Library**

**Filter bar:** All / Used / Unused | Date range

**Grid of image cards, each showing:**
- Thumbnail
- Generation date
- Persona it was generated for
- Provider + model used
- Status: Used (gray overlay, "Used in post [date]") or Unused (full color)
- **Use in Post** button (for unused images)
- **Download** button
- **Delete** button (only for unused images — used images cannot be deleted)

**Unused images older than 30 days show banner:**
- "This image hasn't been used. Generate a post for it?"
- **Generate Caption** button → opens Create Post with this image pre-attached, AI generates caption

---

## 19. SETTINGS

Sidebar → **Settings** → three sections

### Section 1 — Account
- Display name input
- Change email flow (requires password confirmation + re-verification)
- Change password (requires current password)
- Timezone dropdown (updates all time displays across app)
- **Delete Account** button → confirmation modal warning all data will be deleted

### Section 2 — Connected Pages
List of all page_connections (all statuses):

**Connected page row:**
- Profile pic, name, "Connected" green badge
- Connected date, reconnect_count if > 0
- **Sync History** button → calls `/api/pages/{id}/recover-history`, fetches last 100 posts from Facebook
- **Disconnect** button → confirmation modal: "Your post history will be saved. Scheduled posts will be paused."

**Disconnected page row:**
- Profile pic, name, "Disconnected" red badge, disconnected date, post history count
- Message: "Your [n] posts are saved"
- **Reconnect** button → starts OAuth popup again

**Needs Reconnection row:**
- Amber badge, "Token Expired"
- **Reconnect Now** button with urgent styling

### Section 3 — Notifications
- Toggle: Email when auto post fails
- Toggle: Weekly performance report email
- Toggle: Low engagement alerts
- Toggle: Trending topic alerts

---

## 20. AUTO POSTING — WHAT HAPPENS WITHOUT USER ACTION

Once a persona is set up with auto posting enabled, this runs invisibly every minute:

```
cron-job.org sends GET /api/internal/run-scheduler
  with header X-Cron-Secret

Backend validates secret → runs scheduler

FOR EACH active persona:
  Is today in this persona's active_days? → No: skip
  Is current time within active_hours? → No: skip
  Has today's post count reached max_posts_per_day? → Yes: skip
  Has enough time passed since last_auto_post_at? → No: skip

  All checks passed:
    Generate post text via configured LLM
    
    If include_image AND image_frequency check passes:
      Generate image via configured image provider
      Wait up to image_max_wait_seconds
      
      If image fails:
        Apply fallback policy:
          text_only → continue without image
          skip_post → abort, try again next interval
          use_library → pick oldest unused library image
    
    Publish to Facebook via Graph API
    
    On success:
      Update post_logs status = published
      Update last_auto_post_at = now
      Store facebook_post_id
    
    On failure:
      Increment retry_count
      If retry_count < 3 → retry in 5 minutes
      If retry_count = 3 → mark permanently_failed, email user

FOR EACH scheduled manual post where scheduled_at <= NOW():
  If scheduled_at < NOW() - 12 hours → mark missed, skip
  Otherwise → publish to Facebook
  Same retry logic as above
```

---

## 21. WEEKLY LEARNING JOB
*(Runs every Sunday midnight, no user action needed)*

```
For each persona with 20+ posts:
  1. Fetch all engagement snapshots from last 30 days
  2. Recalculate performance score (weighted rolling average)
  3. Extract top 5 vs bottom 5 post patterns
  4. Update PersonaLearningPattern table
  5. Send performance summary to Mistral:
     "Analyze this data. Return JSON with:
      best_post_length, best_posting_times,
      best_content_formats, topics_to_increase,
      topics_to_decrease, prompt_improvements,
      confidence_score"
  6. Store result in learned_strategy table
  7. Generate prompt improvement suggestions
     (user sees these in Prompt Studio, approves/rejects)
  8. Generate 3-5 plain-language recommendations
     (stored in ai_recommendations, shown in Analytics)
  9. Send user weekly email:
     "Your weekly AutoPoster report:
      - Top post this week: [preview]
      - Best persona: [name] (score: [n])
      - Best time slot: [day] [time]
      - 3 recommendations: [list]"
```

---

## 22. ENGAGEMENT TRACKING JOB
*(Runs every 6 hours, no user action needed)*

```
Find all posts published in last 48 hours
For each post, check which snapshots are missing:
  - 1hr snapshot: if post is 1+ hours old and no 1hr snapshot
  - 6hr snapshot: if post is 6+ hours old and no 6hr snapshot
  - 24hr snapshot: if post is 24+ hours old and no 24hr snapshot

For each missing snapshot:
  Call Facebook Graph API:
  /{post_id}/insights?metric=post_impressions,post_reach,
  post_clicks,post_negative_feedback,post_reactions_like_total

  Get likes, comments, shares from /{post_id}?fields=likes.summary(true),
  comments.summary(true),shares

  Calculate engagement score:
  score = (likes×1) + (comments×3) + (shares×5) + (reach÷100)

  Save to post_engagement_snapshots

After saving, recalculate persona performance_score:
  Weighted average of last 20 posts for this persona
  Most recent weight=20, oldest weight=1
  Normalize against page average
  Clamp between 0.1 and 1.0
  Save to ai_personas.performance_score

If score drops below 0.25:
  Set persona status to paused
  Email user: "[Persona Name] paused due to low engagement.
  Review and update your prompt to reactivate."
```

---

## 23. DISCONNECT → RECONNECT FULL CYCLE

```
User clicks Disconnect in Settings
↓
Confirmation modal: "Your post history will be saved.
Scheduled posts will be paused until you reconnect."
↓
User confirms
↓
Backend:
  page_connections: status='disconnected', access_token=NULL,
  disconnected_at=NOW()
  post_logs: all 'scheduled' → 'paused' for this page
↓
Dashboard shows page card with:
  Red "Disconnected" badge
  "[n] posts saved in history"
  Reconnect button

═══════════════════════════════════

User clicks Reconnect
↓
Same OAuth popup flow as Section 6
↓
OAuth completes, backend receives new token
↓
Backend finds existing page_connections row
(same user_id + same facebook_page_id)
↓
Updates: status='connected', access_token=new_encrypted_token,
disconnected_at=NULL, reconnect_count+1,
last_token_refresh=NOW()
↓
Resumes paused posts:
  post_logs where status='paused' AND scheduled_at > NOW()
  → status='scheduled'
  (posts whose time already passed → status='missed')
↓
Dashboard shows full history as if nothing happened
Toast: "Page reconnected. [n] scheduled posts resumed."
```

---

## 24. ERROR STATES AND WHAT USER SEES

| Situation | What User Sees |
|---|---|
| Token expired (discovered on publish attempt) | Amber banner: "Connection expired. Reconnect your page." + Reconnect button |
| Post failed (first attempt) | Red badge on post, retry scheduled automatically |
| Post permanently failed (3 retries) | Dark red badge, email sent, "See error" expandable |
| Scheduler not triggering (cron-job.org issue) | Red warning on dashboard: "Auto posting may be disrupted" |
| Image generation timeout | Post published text-only (or skipped per policy), library checked |
| Facebook API rate limit | Post queued, retried after 10 minutes |
| Supabase storage unreachable | Image generation fails, fallback policy applied |
| AI provider API key invalid | Toast: "AI generation failed. Check your API key in AI Models settings." |
| User closes OAuth popup early | "Connection cancelled." info toast, Connect button re-enables |
| Page not found on Facebook | "No Facebook Pages found on this account. You must be a Page admin." |

---

## 25. WHAT USER NEVER SEES OR DOES

These happen entirely in the background — user is never involved:

- Facebook App ID or App Secret
- Raw OAuth tokens or page access tokens
- Token encryption or decryption
- Cron-job.org ping requests
- Scheduler tick logs
- Engagement snapshot fetching
- Performance score calculations
- Weighted average math
- Supabase Storage upload paths
- Graph API request construction
- State parameter generation and validation
- Token exchange (short-lived → long-lived)
- Weekly learning synthesis
- RSS feed polling for tracked pages
- Retry scheduling for failed posts
- Missed post detection

---

*End of workflow document. Every user-facing interaction and every background process is covered above.*
