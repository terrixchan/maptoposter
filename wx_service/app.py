"""WeChat Mini Program compatible HTTP API for map poster generation."""

from __future__ import annotations

import base64
import json
import os
import threading
from functools import lru_cache
from pathlib import Path
from tempfile import NamedTemporaryFile

import matplotlib
from matplotlib import font_manager as fm
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from geopy.geocoders import Nominatim, Photon
from lat_lon_parser import parse
from pydantic import BaseModel, Field

# Force non-GUI backend for server-side rendering.
os.environ["MPLBACKEND"] = "Agg"
matplotlib.use("Agg", force=True)

import create_map_poster as cmp

app = FastAPI(title="MapToPoster API", version="1.0.0")
_generation_lock = threading.Lock()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class PosterBase64Request(BaseModel):
    city: str = Field(min_length=1)
    country: str = Field(min_length=1)
    theme: str = "terracotta"
    distance: int = Field(default=12000, ge=1000, le=50000)
    width: float = Field(default=4.0, gt=0.0, le=20.0)
    height: float = Field(default=6.0, gt=0.0, le=20.0)
    display_city: str | None = None
    display_country: str | None = None
    latitude: str | None = None
    longitude: str | None = None


def _needs_cjk_font(*parts: str | None) -> bool:
    text = "".join(part or "" for part in parts)
    return any(ord(ch) > 0x024F for ch in text if ch.isalpha())


@lru_cache(maxsize=1)
def _find_cjk_font_path() -> str | None:
    candidate_keywords = [
        "pingfang",
        "hiragino sans gb",
        "stheiti",
        "songti",
        "heiti",
        "notosanscjk",
        "notoserifcjk",
        "sourcehansans",
        "sourcehanserif",
        "arial unicode",
    ]
    for font_path in fm.findSystemFonts(fontext="ttf") + fm.findSystemFonts(fontext="ttc"):
        basename = os.path.basename(font_path).lower()
        if any(keyword in basename for keyword in candidate_keywords):
            return font_path
    return None


def _choose_fonts(city_label: str, country_label: str) -> dict[str, str] | None:
    if not _needs_cjk_font(city_label, country_label):
        return None

    cjk_font_path = _find_cjk_font_path()
    if cjk_font_path:
        return {
            "bold": cjk_font_path,
            "regular": cjk_font_path,
            "light": cjk_font_path,
        }

    # Last fallback: try downloading a CJK web font if system CJK fonts are unavailable.
    downloaded = cmp.load_fonts("Noto Sans SC")
    return downloaded


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/themes")
def themes() -> dict[str, list[str]]:
    return {"themes": cmp.get_available_themes()}


@app.get("/api/themes/details")
def theme_details() -> dict[str, list[dict[str, str]]]:
    details: list[dict[str, str]] = []
    for theme_name in cmp.get_available_themes():
        theme_path = Path(cmp.THEMES_DIR) / f"{theme_name}.json"
        try:
            with open(theme_path, "r", encoding=cmp.FILE_ENCODING) as f:
                data = json.load(f)
        except Exception:  # noqa: BLE001
            continue

        details.append(
            {
                "id": theme_name,
                "name": data.get("name", theme_name),
                "description": data.get("description", ""),
                "bg": data.get("bg", "#ffffff"),
                "text": data.get("text", "#111111"),
                "water": data.get("water", "#9ec5fe"),
                "parks": data.get("parks", "#9fd7a6"),
                "road_primary": data.get("road_primary", "#5f6b7a"),
                "road_secondary": data.get("road_secondary", "#8a95a3"),
            }
        )

    return {"themes": details}


@app.get("/api/location/reverse")
def reverse_location(
    latitude: float = Query(..., ge=-90.0, le=90.0),
    longitude: float = Query(..., ge=-180.0, le=180.0),
) -> dict[str, str | float]:
    def _extract_city_country(address: dict[str, str]) -> tuple[str, str]:
        city = (
            address.get("city")
            or address.get("town")
            or address.get("municipality")
            or address.get("county")
            or address.get("state_district")
            or "Current Location"
        )
        country = address.get("country") or "Unknown"
        return city, country

    try:
        nominatim = Nominatim(user_agent="city_map_poster_api", timeout=10)
        location = nominatim.reverse((latitude, longitude), language="en")
        if location and isinstance(location.raw, dict):
            address = location.raw.get("address", {})
            if isinstance(address, dict):
                city, country = _extract_city_country(address)
                return {
                    "city": city,
                    "country": country,
                    "latitude": latitude,
                    "longitude": longitude,
                }
    except Exception:  # noqa: BLE001
        pass

    try:
        photon = Photon(user_agent="city_map_poster_api", timeout=10)
        location = photon.reverse((latitude, longitude))
        if location and isinstance(location.raw, dict):
            props = location.raw.get("properties", {})
            city = (
                props.get("city")
                or props.get("name")
                or props.get("county")
                or "Current Location"
            )
            country = props.get("country") or "Unknown"
            return {
                "city": str(city),
                "country": str(country),
                "latitude": latitude,
                "longitude": longitude,
            }
    except Exception:  # noqa: BLE001
        pass

    return {
        "city": "Current Location",
        "country": "Unknown",
        "latitude": latitude,
        "longitude": longitude,
    }


def _resolve_point(city: str, country: str, latitude: str | None, longitude: str | None) -> tuple[float, float]:
    if latitude and longitude:
        return (parse(latitude), parse(longitude))

    # Prefer downtown-like queries to avoid selecting sparse administrative centroids.
    center_queries = [
        f"{city} city center, {country}",
        f"{city} downtown, {country}",
        f"{city} center, {country}",
        f"{city} 市中心, {country}",
        f"{city} 中心, {country}",
    ]

    nominatim = Nominatim(user_agent="city_map_poster_api", timeout=10)
    for query in center_queries:
        try:
            location = nominatim.geocode(query)
            if location:
                return (float(location.latitude), float(location.longitude))
        except Exception:  # noqa: BLE001
            continue

    try:
        return cmp.get_coordinates(city, country)
    except Exception as nominatim_exc:  # noqa: BLE001
        # Fallback provider when Nominatim is rate-limited/unavailable.
        try:
            geolocator = Photon(user_agent="city_map_poster", timeout=10)
            for query in center_queries + [f"{city}, {country}"]:
                location = geolocator.geocode(query)
                if location:
                    return (float(location.latitude), float(location.longitude))
        except Exception:  # noqa: BLE001
            pass

        raise HTTPException(
            status_code=400,
            detail=(
                "Failed to resolve coordinates from geocoding providers. "
                f"Last error: {nominatim_exc}. "
                "Please input latitude/longitude manually."
            ),
        ) from nominatim_exc


@app.get("/api/posters/generate")
def generate_poster(
    background_tasks: BackgroundTasks,
    city: str = Query(..., min_length=1),
    country: str = Query(..., min_length=1),
    theme: str = Query("terracotta"),
    distance: int = Query(18000, ge=1000, le=50000),
    width: float = Query(12.0, gt=0.0, le=20.0),
    height: float = Query(16.0, gt=0.0, le=20.0),
    display_city: str | None = Query(default=None),
    display_country: str | None = Query(default=None),
    latitude: str | None = Query(default=None),
    longitude: str | None = Query(default=None),
    fmt: str = Query("png", pattern="^(png|svg|pdf)$"),
):
    available_themes = cmp.get_available_themes()
    if theme not in available_themes:
        raise HTTPException(
            status_code=400,
            detail={
                "message": f"Theme '{theme}' not found",
                "available_themes": available_themes,
            },
        )

    point = _resolve_point(city, country, latitude, longitude)

    theme_data = cmp.load_theme(theme)
    city_label = display_city or city
    country_label = display_country or country
    chosen_fonts = _choose_fonts(city_label, country_label)
    media_type = {
        "png": "image/png",
        "svg": "image/svg+xml",
        "pdf": "application/pdf",
    }[fmt]

    temp_file = NamedTemporaryFile(prefix="poster_", suffix=f".{fmt}", delete=False)
    output_path = Path(temp_file.name)
    temp_file.close()

    try:
        with _generation_lock:
            cmp.THEME = theme_data
            cmp.create_poster(
                city=city,
                country=country,
                point=point,
                dist=distance,
                output_file=str(output_path),
                output_format=fmt,
                width=width,
                height=height,
                display_city=display_city,
                display_country=display_country,
                fonts=chosen_fonts,
            )
    except Exception as exc:  # noqa: BLE001
        output_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Poster generation failed: {exc}") from exc

    background_tasks.add_task(os.remove, str(output_path))
    safe_name = city.strip().replace(" ", "_").lower()
    return FileResponse(
        path=str(output_path),
        media_type=media_type,
        filename=f"{safe_name}_{theme}.{fmt}",
        background=background_tasks,
    )


@app.post("/api/posters/generate-base64")
def generate_poster_base64(payload: PosterBase64Request) -> dict[str, str]:
    available_themes = cmp.get_available_themes()
    if payload.theme not in available_themes:
        raise HTTPException(
            status_code=400,
            detail={
                "message": f"Theme '{payload.theme}' not found",
                "available_themes": available_themes,
            },
        )

    point = _resolve_point(payload.city, payload.country, payload.latitude, payload.longitude)
    theme_data = cmp.load_theme(payload.theme)
    city_label = payload.display_city or payload.city
    country_label = payload.display_country or payload.country
    chosen_fonts = _choose_fonts(city_label, country_label)

    temp_file = NamedTemporaryFile(prefix="poster_", suffix=".png", delete=False)
    output_path = Path(temp_file.name)
    temp_file.close()

    try:
        with _generation_lock:
            cmp.THEME = theme_data
            cmp.create_poster(
                city=payload.city,
                country=payload.country,
                point=point,
                dist=payload.distance,
                output_file=str(output_path),
                output_format="png",
                width=payload.width,
                height=payload.height,
                display_city=payload.display_city,
                display_country=payload.display_country,
                fonts=chosen_fonts,
            )

        image_bytes = output_path.read_bytes()
        image_base64 = base64.b64encode(image_bytes).decode("ascii")
        return {
            "mime_type": "image/png",
            "image_base64": image_base64,
        }
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Poster generation failed: {exc}") from exc
    finally:
        output_path.unlink(missing_ok=True)
