"""
NEPSE Smart — Backend Server
=============================
FastAPI server that fetches live data from nepalstock.com.np
and exposes a clean REST API for your GitHub Pages frontend.

Deploy on: Render.com (free) / Railway / any VPS
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import asyncio
import json
import time
import logging
from contextlib import asynccontextmanager

# ── Logging ──────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("nepse-api")

# ── Cache (simple in-memory) ─────────────────────────────────
cache = {
    "stocks":    {"data": [], "ts": 0},
    "indices":   {"data": {}, "ts": 0},
    "summary":   {"data": {}, "ts": 0},
    "floorsheet":{"data": [], "ts": 0},
}
CACHE_TTL = 5 * 60  # 5 minutes

# ── Nepse client (lazy import) ───────────────────────────────
nepse_client = None

def get_nepse():
    global nepse_client
    if nepse_client is None:
        try:
            from nepse import Nepse
            nepse_client = Nepse()
            nepse_client.setTLSVerification(False)
            log.info("✅ Nepse client initialized")
        except Exception as e:
            log.error(f"❌ Nepse client failed: {e}")
            nepse_client = None
    return nepse_client

# ── App ──────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("🚀 NEPSE Smart API starting…")
    get_nepse()
    yield
    log.info("👋 NEPSE Smart API shutting down")

app = FastAPI(
    title="NEPSE Smart API",
    description="Live data API for nepse.amitacharya.com.np",
    version="1.0.0",
    lifespan=lifespan,
)

# ── CORS — allow your GitHub Pages domain ───────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://nepse.amitacharya.com.np",
        "https://amitacharya.com.np",
        "http://localhost:3000",
        "http://127.0.0.1:5500",
        "*",  # Remove this in production, keep only your domain
    ],
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)

# ── Helpers ──────────────────────────────────────────────────
def is_stale(key):
    return time.time() - cache[key]["ts"] > CACHE_TTL

def cached(key, data):
    cache[key]["data"] = data
    cache[key]["ts"]   = time.time()
    return data

# ── ROUTES ───────────────────────────────────────────────────

@app.get("/")
def root():
    return {
        "status": "ok",
        "service": "NEPSE Smart API",
        "endpoints": [
            "/api/stocks",
            "/api/indices",
            "/api/summary",
            "/api/floorsheet",
            "/api/stock/{symbol}",
            "/api/health",
        ]
    }

@app.get("/api/health")
def health():
    n = get_nepse()
    return {
        "status":        "ok",
        "nepse_client":  n is not None,
        "cache_stocks":  len(cache["stocks"]["data"]),
        "last_update":   cache["stocks"]["ts"],
        "uptime_secs":   time.time(),
    }

# ── TODAY'S STOCK PRICES ─────────────────────────────────────
@app.get("/api/stocks")
async def get_stocks():
    if not is_stale("stocks") and cache["stocks"]["data"]:
        return JSONResponse({"source": "cache", "data": cache["stocks"]["data"]})

    n = get_nepse()
    if not n:
        # Return cached even if stale, better than nothing
        if cache["stocks"]["data"]:
            return JSONResponse({"source": "stale_cache", "data": cache["stocks"]["data"]})
        return JSONResponse({"error": "NEPSE client unavailable"}, status_code=503)

    try:
        raw = await asyncio.to_thread(n.getTodayPrice)
        stocks = []
        for r in (raw or []):
            try:
                prev  = float(r.get("previousClosing") or r.get("prevClose") or 0)
                ltp   = float(r.get("closingPrice")    or r.get("ltp")       or 0)
                chg   = round(ltp - prev, 2)
                chgPct= round((chg / prev * 100) if prev else 0, 2)
                stocks.append({
                    "symbol":  r.get("stockSymbol")    or r.get("symbol", ""),
                    "name":    r.get("securityName")   or r.get("stockName", ""),
                    "sector":  r.get("businessType")   or r.get("sectorName", "Other"),
                    "ltp":     ltp,
                    "open":    float(r.get("openPrice")         or 0),
                    "high":    float(r.get("highPrice")         or 0),
                    "low":     float(r.get("lowPrice")          or 0),
                    "prev":    prev,
                    "vol":     int(r.get("totalTradeQuantity")  or 0),
                    "to":      float(r.get("totalTradeValue")   or 0),
                    "chg":     chg,
                    "chgPct":  chgPct,
                    "eps":     float(r.get("eps")               or 0),
                    "pe":      float(r.get("peRatio")           or 0),
                    "bv":      float(r.get("bookValue")         or 0),
                })
            except Exception:
                continue
        cached("stocks", stocks)
        log.info(f"✅ Fetched {len(stocks)} stocks")
        return JSONResponse({"source": "live", "data": stocks})
    except Exception as e:
        log.error(f"❌ get_stocks error: {e}")
        if cache["stocks"]["data"]:
            return JSONResponse({"source": "stale_cache", "data": cache["stocks"]["data"]})
        return JSONResponse({"error": str(e)}, status_code=500)

# ── INDICES ──────────────────────────────────────────────────
@app.get("/api/indices")
async def get_indices():
    if not is_stale("indices") and cache["indices"]["data"]:
        return JSONResponse({"source": "cache", "data": cache["indices"]["data"]})

    n = get_nepse()
    if not n:
        return JSONResponse({"source": "stale", "data": cache["indices"]["data"]})

    try:
        raw = await asyncio.to_thread(n.getNepseIndex)
        indices = {}
        for r in (raw or []):
            name = (r.get("indexName") or r.get("name") or "").lower()
            val  = {
                "value":  float(r.get("currentValue")       or r.get("indexValue") or 0),
                "change": float(r.get("change")             or 0),
                "pct":    float(r.get("percentageChange")   or 0),
                "open":   float(r.get("openValue")          or 0),
                "high":   float(r.get("highValue")          or 0),
                "low":    float(r.get("lowValue")           or 0),
            }
            if "sensitive" in name and "float" in name:
                indices["sensFloat"] = val
            elif "sensitive" in name:
                indices["sensitive"] = val
            elif "float" in name:
                indices["float"] = val
            elif "nepse" in name:
                indices["nepse"] = val
        cached("indices", indices)
        return JSONResponse({"source": "live", "data": indices})
    except Exception as e:
        log.error(f"❌ get_indices error: {e}")
        return JSONResponse({"source": "stale", "data": cache["indices"]["data"]})

# ── MARKET SUMMARY ───────────────────────────────────────────
@app.get("/api/summary")
async def get_summary():
    if not is_stale("summary") and cache["summary"]["data"]:
        return JSONResponse({"source": "cache", "data": cache["summary"]["data"]})

    n = get_nepse()
    if not n:
        return JSONResponse({"source": "stale", "data": cache["summary"]["data"]})

    try:
        raw = await asyncio.to_thread(n.getMarketSummary)
        summary = {
            "turnover":     float(raw.get("totalTurnover")     or raw.get("turnover")     or 0),
            "transactions": int(raw.get("totalTransactions")   or raw.get("transactions") or 0),
            "advances":     int(raw.get("advances")            or 0),
            "declines":     int(raw.get("declines")            or 0),
            "unchanged":    int(raw.get("unchanged")           or 0),
            "tradedScrips": int(raw.get("totalScripsTraded")   or 0),
        }
        cached("summary", summary)
        return JSONResponse({"source": "live", "data": summary})
    except Exception as e:
        log.error(f"❌ get_summary error: {e}")
        # Build from stocks cache as fallback
        stocks = cache["stocks"]["data"]
        if stocks:
            adv  = sum(1 for s in stocks if s["chg"] > 0)
            dec  = sum(1 for s in stocks if s["chg"] < 0)
            unch = sum(1 for s in stocks if s["chg"] == 0)
            fallback = {
                "turnover":     sum(s["to"] for s in stocks),
                "transactions": len(stocks),
                "advances":     adv, "declines": dec, "unchanged": unch,
                "tradedScrips": len(stocks),
            }
            return JSONResponse({"source": "computed", "data": fallback})
        return JSONResponse({"error": str(e)}, status_code=500)

# ── FLOORSHEET (Broker accumulation data) ────────────────────
@app.get("/api/floorsheet")
async def get_floorsheet():
    """
    Returns aggregated floorsheet data grouped by (symbol, broker).
    This is the foundation of the broker accumulation tracker.
    Heavy endpoint — cached for longer (30 min).
    """
    FS_TTL = 30 * 60
    if time.time() - cache["floorsheet"]["ts"] < FS_TTL and cache["floorsheet"]["data"]:
        return JSONResponse({"source": "cache", "data": cache["floorsheet"]["data"]})

    n = get_nepse()
    if not n:
        return JSONResponse({"source": "stale", "data": cache["floorsheet"]["data"]})

    try:
        log.info("📊 Fetching floorsheet (this may take 10–30s)…")
        # Get today's floorsheet — NepseUnofficialApi handles pagination
        raw = await asyncio.to_thread(n.getFloorSheet)

        # Aggregate by (symbol, broker) — net units = bought - sold
        from collections import defaultdict
        agg = defaultdict(lambda: {"bought": 0, "sold": 0, "value": 0})

        for row in (raw or []):
            try:
                sym    = row.get("stockSymbol") or row.get("symbol", "")
                buyer  = int(row.get("buyerMemberId")  or row.get("buyerId")  or 0)
                seller = int(row.get("sellerMemberId") or row.get("sellerId") or 0)
                qty    = int(row.get("contractQuantity") or row.get("quantity") or 0)
                val    = float(row.get("contractAmount") or row.get("amount") or 0)

                if sym and buyer:
                    agg[(sym, buyer)]["bought"] += qty
                    agg[(sym, buyer)]["value"]  += val
                if sym and seller:
                    agg[(sym, seller)]["sold"]  += qty
            except Exception:
                continue

        # Build broker activity list
        result = []
        for (sym, broker_id), d in agg.items():
            net = d["bought"] - d["sold"]
            result.append({
                "symbol":    sym,
                "brokerId":  broker_id,
                "bought":    d["bought"],
                "sold":      d["sold"],
                "netUnits":  net,
                "value":     round(d["value"], 2),
            })

        cache["floorsheet"]["data"] = result
        cache["floorsheet"]["ts"]   = time.time()
        log.info(f"✅ Floorsheet: {len(result)} broker-stock pairs")
        return JSONResponse({"source": "live", "count": len(result), "data": result})

    except Exception as e:
        log.error(f"❌ get_floorsheet error: {e}")
        return JSONResponse({"source": "stale", "data": cache["floorsheet"]["data"]})

# ── INDIVIDUAL STOCK ─────────────────────────────────────────
@app.get("/api/stock/{symbol}")
async def get_stock(symbol: str):
    symbol = symbol.upper()
    stocks = cache["stocks"]["data"]
    stock  = next((s for s in stocks if s["symbol"] == symbol), None)
    if not stock:
        return JSONResponse({"error": f"{symbol} not found"}, status_code=404)

    # Attach broker data
    fs = cache["floorsheet"]["data"]
    brokers = [b for b in fs if b["symbol"] == symbol]
    top_buyers  = sorted(brokers, key=lambda b: b["bought"], reverse=True)[:5]
    top_sellers = sorted(brokers, key=lambda b: b["sold"],   reverse=True)[:5]

    return JSONResponse({
        "stock":      stock,
        "topBuyers":  top_buyers,
        "topSellers": top_sellers,
        "netFlow":    sum(b["netUnits"] for b in brokers),
    })
