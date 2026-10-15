# 🗺️ Halal NYC Finder — Roadmap

## Positioning

**"Google tells you what's near. We tell you what's safe to eat."**

We don't compete with Google Maps / Uber Eats on "halal near me" — they win
that today. We own the **trust layer** nobody else has: halal verification +
official NYC hygiene data, in one place.

## Differentiators (why someone uses us instead of Google)

1. **Hygiene grade + halal, together** — "Grade A halal near me" has no good
   answer anywhere else on the internet.
2. **Violation transparency** — not just the grade, but *why* points were
   lost (mice? roaches? handwash sink?). Google/Uber Eats never show this.
3. **Halal confidence tiers** — 🟢 confirmed / 🟡 likely (verify) — addresses
   the real anxiety of observant diners.
4. **AI concierge** — multi-constraint plain-English queries
   ("grade A halal Indian in Queens open late").

## Phases

### Phase 1 — Mobile-ready (share with friends)
- [ ] Single-column mobile layout (filters in collapsible section, full-width map)
- [ ] Touch-friendly tap targets (~44px)
- [ ] 📤 WhatsApp share button per restaurant (the viral loop)
- [ ] "Near me" — distance sort from a ZIP the user enters
- [x] Color-coded map pins (green = confirmed, amber = likely)
- [x] Data freshness indicator + refresh button

### Phase 2 — Trust & depth (the moat)
- [ ] **Violation details on each card** ("Eat clean mode": grade A + no
      critical violations) — priority #1, ahead of everything else below
- [ ] "Open now" indicator, photos, ratings via Google Places API (free tier,
      needs API key)
- [ ] Polish HalalRank-style confidence display

### Phase 3 — Community (the Zabihah moat)
- [ ] "Verify halal" button — community confirmation
- [ ] Reviews / ratings from users
- [ ] Needs a small database (Supabase free tier); Streamlit Cloud storage is
      ephemeral

### Phase 4 — AI+
- [ ] Full LLM mode for the concierge (architecture ready; needs API key)
- [ ] "Where should we eat tonight?" group-decision helper
- [ ] Prayer-space finder (mosques/musallahs near the restaurant)

## Done
- [x] Data pipeline: NYC Open Data DOHMH inspections → 1,274 restaurants
      (169 confirmed + 1,105 likely halal)
- [x] Null Island (0,0) + out-of-NYC coordinate scrubbing
- [x] Latest-graded-inspection dedupe per restaurant
- [x] AI concierge (text-to-structured-query, keyword fallback)
- [x] GitHub repo + Streamlit Cloud deploy
