#!/usr/bin/env python3
"""Regenerate demo-epg.xml for the GiVo screenshot rig.

Fictional channels/shows only — never real networks. Reuses the same show
titles as the original 2026-06-11 EPG so screenshots stay consistent.
Coverage: yesterday 00:00 -> +4 days, local time (-0400).
Usage: python3 gen_epg.py [start-date YYYY-MM-DD]
"""
import sys, hashlib
from datetime import datetime, timedelta

TZ = "-0400"
OUT = "/tmp/demosite/demo-epg.xml"

# id, display-name, category, [shows], slot minutes choices
CHANNELS = [
    ("orbitnews.demo", "Orbit News 24", "News",
     ["Orbit Morning Report", "Market Pulse", "Midday Briefing", "The World Desk",
      "Global Hour", "Weather Watch", "Orbit Tonight", "Late Edition"], [30, 60]),
    ("peaksports.demo", "Peak Sports", "Sports",
     ["Matchday Countdown", "The Big Match", "Overtime", "Locker Room Live",
      "Peak Performance", "Championship Recap", "Trail &amp; Track", "Fight Night Classics"], [60, 90]),
    ("galaxymv.demo", "Galaxy Movies", "Movies",
     ["Feature Presentation", "Tears of Steel", "Galaxy Premiere", "Double Feature",
      "Director&#x27;s Cut", "The Short List", "Midnight Matinee", "Classics After Dark"], [90, 120]),
    ("hearthhome.demo", "Hearth &amp; Home", "Lifestyle",
     ["Open House", "The Renovation Files", "Cozy Kitchens", "Garden Stories",
      "Weekend Projects", "Market Finds", "Fixer Friday", "Home Again"], [30, 60]),
    ("cartooncove.demo", "Cartoon Cove", "Kids",
     ["The Acorn Gang", "Robo Pals", "Pirate Pond", "Cloud Castle",
      "Snail Mail", "Doodle Time", "Big Buck Bunny", "Bedtime Tales"], [30]),
    ("docuplus.demo", "Docu+", "Documentary",
     ["Megastructures", "Deep Ocean", "Lost Cities", "Edge of the Map",
      "The Wild North", "Inside the Machine", "Night Skies", "Frontier Medicine"], [60]),
    ("cooktable.demo", "The Cooking Table", "Food",
     ["Five Ingredients", "Street Eats", "Kitchen Battles", "Top Plates",
      "The Pastry Hour", "Spice Routes", "Sunday Roast", "Late Bites"], [30, 60]),
    ("retrotv.demo", "Retro TV Classics", "Entertainment",
     ["Sitcom Gold", "Detective Reruns", "Golden Age Theater", "The Variety Hour",
      "Vintage Westerns", "Classic Game Night", "Saturday Serials", "The Archive"], [30, 60]),
    ("musicnow.demo", "Music Now", "Music",
     ["Morning Mix", "Top 20 Countdown", "Acoustic Sessions", "Live &amp; Loud",
      "The Vinyl Vault", "Festival Replay", "Night Grooves", "After Hours"], [30, 60]),
    ("local7.demo", "Local 7", "Local",
     ["The Morning Show", "Local 7 News at Noon", "Community Spotlight",
      "Neighborhood Eats", "High School Sports Week", "Local 7 Evening News",
      "City Council Live", "Nightcast"], [30, 60]),
    ("comedydist.demo", "Comedy District", "Entertainment",
     ["Laugh Track", "Sketch City", "The Improv Hour", "Punchline",
      "Stand-Up Spotlight", "Open Mic Live", "Roast Night", "The Sunday Special"], [30, 60]),
    ("scisphere.demo", "Science Sphere", "Documentary",
     ["Space Weekly", "Planet Lab", "How It&#x27;s Built", "The Body Electric",
      "Field Notes", "Future Tense", "Math in Motion", "The Quantum Files"], [60]),
    ("dramaone.demo", "Drama One", "Series",
     ["Harbor Lights", "The Verdict", "Crossing Lines", "Paper Empire",
      "Cold Case Unit", "The Long Road", "The Inheritance", "Night Shift"], [60]),
    ("traveltrl.demo", "Travel Trails", "Travel",
     ["48 Hours In…", "Coastal Escapes", "Rail Journeys", "Hidden Islands",
      "The Food Traveler", "Desert Roads", "Mountain Passes", "City Limits"], [30, 60]),
]

DESCS = {
    "News": ["The stories shaping the day, with analysis from the desk and correspondents around the globe.",
             "Breaking coverage and in-depth reporting on the day's biggest headlines.",
             "A complete look at today's news, markets, and weather — everything you need before you head out."],
    "Sports": ["Highlights, analysis, and the moments everyone will be talking about tomorrow.",
               "Full coverage from the day's action, with expert breakdowns and post-game reaction.",
               "The matchups that matter, previewed and replayed with the analysts who know them best."],
    "Movies": ["A handpicked feature presented in its original aspect ratio.",
               "An acclaimed feature film, presented uncut.",
               "Tonight's feature: a fan-favorite selection from the vault."],
    "Lifestyle": ["Fresh ideas for every room, garden, and weekend project.",
                  "Real homes, real budgets, and transformations you can actually pull off.",
                  "Inspiration and how-to for making your space feel brand new."],
    "Kids": ["Friendly adventures and big laughs for the whole family.",
             "A new adventure with old friends — fun for every age.",
             "Stories, songs, and silliness to brighten the afternoon."],
    "Documentary": ["A closer look at the people, places, and machines that shape our world.",
                    "Stunning photography and expert voices reveal a world you've never seen this way.",
                    "An in-depth journey behind the scenes of an extraordinary story."],
    "Food": ["Recipes, techniques, and kitchen wisdom you'll actually use.",
             "From street food to fine dining — the dishes worth traveling for.",
             "Chefs face off and flavors fly in the kitchen's friendliest competition."],
    "Entertainment": ["The classics that defined an era, restored and back-to-back.",
                      "Comedy, variety, and timeless moments from the golden archive.",
                      "An evening of favorites you'll want to watch all over again."],
    "Music": ["Wall-to-wall music: sessions, countdowns, and live performances.",
              "The tracks everyone's playing, plus deep cuts from the vault.",
              "Live sets and studio sessions from artists on the rise."],
    "Local": ["News, weather, and stories from right here in the neighborhood.",
              "Your community, covered — from city hall to Friday night lights.",
              "The people and places that make this city home."],
    "Series": ["A gripping new chapter — secrets surface and loyalties are tested.",
               "The acclaimed drama continues with an episode you won't see coming.",
               "Tensions rise as the season builds toward its turning point."],
    "Travel": ["Pack your bags: hidden gems, local flavors, and routes less traveled.",
               "A whirlwind tour of the sights, tastes, and sounds worth the trip.",
               "Off the beaten path and into the places locals love."],
}

def desc_for(title, cat):
    pool = DESCS[cat]
    return pool[int(hashlib.md5(title.encode()).hexdigest(), 16) % len(pool)]

start_day = sys.argv[1] if len(sys.argv) > 1 else None
if start_day:
    t0 = datetime.strptime(start_day, "%Y-%m-%d")
else:
    t0 = (datetime.now() - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
t_end = t0 + timedelta(days=5)

def ts(dt): return dt.strftime("%Y%m%d%H%M%S") + " " + TZ

lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<tv>"]
for cid, name, _, _, _ in CHANNELS:
    lines.append(f'  <channel id="{cid}"><display-name>{name}</display-name></channel>')

count = 0
for cid, name, cat, shows, slots in CHANNELS:
    t = t0
    i = int(hashlib.md5(cid.encode()).hexdigest(), 16)  # per-channel phase
    while t < t_end:
        title = shows[i % len(shows)]
        dur = slots[i % len(slots)]
        stop = t + timedelta(minutes=dur)
        lines.append(f'  <programme start="{ts(t)}" stop="{ts(stop)}" channel="{cid}">')
        lines.append(f"    <title>{title}</title>")
        lines.append(f"    <desc>{desc_for(title, cat)}</desc>")
        lines.append(f"    <category>{cat}</category>")
        lines.append("  </programme>")
        t = stop
        i += 1
        count += 1
lines.append("</tv>")
open(OUT, "w").write("\n".join(lines) + "\n")
print(f"wrote {OUT}: {count} programmes, {t0:%Y-%m-%d} -> {t_end:%Y-%m-%d}")
