"""CC Analytics dashboard routes"""

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from finbot.core.analytics.queries import (
    get_auth_funnel,
    get_browser_breakdown,
    get_daily_latency,
    get_daily_pageviews,
    get_device_breakdown,
    get_page_browser_breakdown,
    get_page_daily,
    get_page_device_breakdown,
    get_page_referer_breakdown,
    get_page_stats,
    get_page_status_breakdown,
    get_pageviews_count,
    get_referer_breakdown,
    get_response_time_percentiles,
    get_session_type_breakdown,
    get_top_pages,
    get_total_pageviews,
    get_unique_visitors,
)
from finbot.core.data.database import SessionLocal
from finbot.core.templates import TemplateResponse

template_response = TemplateResponse("finbot/apps/cc/templates")

router = APIRouter(prefix="/analytics")

ALLOWED_DAILY_RANGES = {0, 7, 14, 30}


def _sanitize_days(days: int) -> int:
    return days if days in ALLOWED_DAILY_RANGES else 30


@router.get("/", response_class=HTMLResponse)
async def analytics_dashboard(request: Request):
    """Analytics overview dashboard"""
    db = SessionLocal()
    try:
        latency = get_response_time_percentiles(db, days=7)
        data = {
            "pageviews_7d": get_pageviews_count(db, days=7),
            "pageviews_30d": get_pageviews_count(db, days=30),
            "visitors_7d": get_unique_visitors(db, days=7),
            "visitors_30d": get_unique_visitors(db, days=30),
            "total_pageviews": get_total_pageviews(db),
            "top_pages": get_top_pages(db, days=7, limit=10),
            "browsers": get_browser_breakdown(db, days=7),
            "devices": get_device_breakdown(db, days=7),
            "referers": get_referer_breakdown(db, days=7, limit=8),
            "daily": get_daily_pageviews(db, days=30),
            "daily_latency": get_daily_latency(db, days=30),
            "funnel": get_auth_funnel(db, days=7),
            "latency": latency,
            "sessions": get_session_type_breakdown(db, days=7),
        }
    finally:
        db.close()

    return template_response(request, "pages/analytics.html", data)


@router.get("/pages", response_class=HTMLResponse)
async def page_drilldown(request: Request, path: str = Query(...)):
    """Per-page drill-down analytics"""
    db = SessionLocal()
    try:
        data = {
            "path": path,
            "stats": get_page_stats(db, path, days=7),
            "daily": get_page_daily(db, path, days=30),
            "daily_latency": get_daily_latency(db, days=30, path=path),
            "status_codes": get_page_status_breakdown(db, path, days=7),
            "browsers": get_page_browser_breakdown(db, path, days=7),
            "devices": get_page_device_breakdown(db, path, days=7),
            "referers": get_page_referer_breakdown(db, path, days=7),
        }
    finally:
        db.close()

    return template_response(request, "pages/analytics_page.html", data)


@router.get("/api/daily")
async def daily_traffic_api(days: int = Query(default=30)):
    """JSON endpoint for daily traffic, used by the time-range picker."""
    days = _sanitize_days(days)
    db = SessionLocal()
    try:
        return get_daily_pageviews(db, days=days or None)
    finally:
        db.close()


@router.get("/api/daily-latency")
async def daily_latency_api(days: int = Query(default=30)):
    """JSON endpoint for daily latency, used by the time-range picker."""
    days = _sanitize_days(days)
    db = SessionLocal()
    try:
        return get_daily_latency(db, days=days or None)
    finally:
        db.close()
