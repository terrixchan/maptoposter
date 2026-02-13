"""WeChat Mini Program compatible HTTP API for map poster generation."""

from __future__ import annotations

import base64
import os
import threading
from pathlib import Path
from tempfile import NamedTemporaryFile

import matplotlib
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from geopy.geocoders import Photon
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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/themes")
def themes() -> dict[str, list[str]]:
    return {"themes": cmp.get_available_themes()}


def _resolve_point(city: str, country: str, latitude: str | None, longitude: str | None) -> tuple[float, float]:
    if latitude and longitude:
        return (parse(latitude), parse(longitude))

    try:
        return cmp.get_coordinates(city, country)
    except Exception as nominatim_exc:  # noqa: BLE001
        # Fallback provider when Nominatim is rate-limited/unavailable.
        try:
            geolocator = Photon(user_agent="city_map_poster", timeout=10)
            location = geolocator.geocode(f"{city}, {country}")
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
