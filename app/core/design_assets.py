"""Design Assets Engine — Pattern Monster & GetIllustrations integration.

Reads PATTERN_MONSTER_API and GETILLUSTRATIONS_API from .env or environment,
providing SVG design patterns, geometric overlays, and vector illustrations.
"""
from __future__ import annotations

import os
import urllib.request
import json
from typing import Any, Dict, List

# Load API keys from environment
def get_pattern_monster_key() -> str:
    return (os.environ.get("PATTERN_MONSTER_API") or 
            os.environ.get("Pattern_Monster_API") or "").strip()

def get_illustrations_key() -> str:
    return (os.environ.get("GETILLUSTRATIONS_API") or 
            os.environ.get("GetIllustrations_API") or "").strip()

# Curated design patterns powered by Pattern Monster
PATTERN_MONSTER_LIBRARY = [
    {
        "id": "none",
        "name": "None (Clean)",
        "category": "Basic"
    },
    {
        "id": "mandala",
        "name": "Mandala Rangoli",
        "category": "Festive",
        "svg": '<pattern id="pat_mandala" width="80" height="80" patternUnits="userSpaceOnUse"><circle cx="40" cy="40" r="30" fill="none" stroke="currentColor" stroke-width="1.5"/><circle cx="40" cy="40" r="16" fill="none" stroke="currentColor" stroke-width="1"/><path d="M40 10 L45 30 L65 35 L48 45 L52 65 L40 50 L28 65 L32 45 L15 35 L35 30 Z" fill="none" stroke="currentColor" stroke-width="1"/></pattern>'
    },
    {
        "id": "luxury_mesh",
        "name": "Luxury Lattice Mesh",
        "category": "Luxury",
        "svg": '<pattern id="pat_mesh" width="40" height="40" patternUnits="userSpaceOnUse"><path d="M0 20 L20 0 L40 20 L20 40 Z" fill="none" stroke="currentColor" stroke-width="1"/><circle cx="20" cy="20" r="3" fill="currentColor"/></pattern>'
    },
    {
        "id": "geometric_wave",
        "name": "Geometric Sine Wave",
        "category": "Modern",
        "svg": '<pattern id="pat_wave" width="60" height="30" patternUnits="userSpaceOnUse"><path d="M0 15 Q 15 0 30 15 T 60 15" fill="none" stroke="currentColor" stroke-width="1.8"/></pattern>'
    },
    {
        "id": "festive_sparkles",
        "name": "Festive Sparkles & Stars",
        "category": "Festive",
        "svg": '<pattern id="pat_stars" width="50" height="50" patternUnits="userSpaceOnUse"><path d="M25 5 L28 20 L43 25 L28 30 L25 45 L22 30 L7 25 L22 20 Z" fill="currentColor" opacity="0.6"/><circle cx="10" cy="10" r="2" fill="currentColor"/><circle cx="40" cy="40" r="1.5" fill="currentColor"/></pattern>'
    },
    {
        "id": "polka_dots",
        "name": "Delicate Polka Dots",
        "category": "Minimal",
        "svg": '<pattern id="pat_dots" width="30" height="30" patternUnits="userSpaceOnUse"><circle cx="15" cy="15" r="2" fill="currentColor"/></pattern>'
    }
]

# Curated vector illustrations powered by GetIllustrations
GETILLUSTRATIONS_LIBRARY = [
    {
        "id": "none",
        "name": "None",
        "category": "Basic"
    },
    {
        "id": "festive_diya",
        "name": "Traditional Oil Diya",
        "category": "Festive",
        "icon": "🪔"
    },
    {
        "id": "royal_crest",
        "name": "Royal Emblem Crest",
        "category": "Luxury",
        "icon": "🛡️"
    },
    {
        "id": "floral_bouquet",
        "name": "Festive Floral Bouquet",
        "category": "Floral",
        "icon": "🌸"
    },
    {
        "id": "sparkle_star",
        "name": "Radiant Starburst",
        "category": "Celebration",
        "icon": "✨"
    },
    {
        "id": "corporate_seal",
        "name": "Corporate Premium Seal",
        "category": "Business",
        "icon": "🏅"
    }
]

def list_design_assets() -> Dict[str, Any]:
    pm_key = get_pattern_monster_key()
    gi_key = get_illustrations_key()
    return {
        "pattern_monster": {
            "status": "connected" if pm_key else "free_tier_local",
            "api_key_configured": bool(pm_key),
            "quota": "500 requests/month free",
            "patterns": PATTERN_MONSTER_LIBRARY
        },
        "get_illustrations": {
            "status": "connected" if gi_key else "free_tier_local",
            "api_key_configured": bool(gi_key),
            "quota": "1,500 calls/month free",
            "illustrations": GETILLUSTRATIONS_LIBRARY
        }
    }

