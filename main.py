"""
NEPSE Smart — Backend Server (Fixed)
Correct method names for NepseUnofficialApi v0.6.x
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import asyncio
import time
import logging
from contextlib import asynccontextmanager

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("nepse-api")

cache = {
    "stocks":     {"data": [], "ts": 0},
    "indices":    {"data": {}, "ts": 0},
    "summary":    {"data": {}, "ts": 0},
    "floorsheet": {"data": [], "ts": 0},
}
CACHE_TTL    = 5  * 60
CACHE_TTL_FS = 30 * 60
nepse_client = None

def get_nepse():
    global nepse_client
    if nepse_client is None:
        try:
            from nepse import Nepse
            nepse_client = Nepse()
            nepse_client.setTLSVerification(False)
            log.info("Nepse client ready")
        except Exception as e:
            log.error(f"Nepse client error: {e}")
    return nepse_client

@asynccontextmanager
async def lifespan(app: FastAPI):
    get_nepse()
    yield

app = FastAPI(title="NEPSE Smart API", version="2.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["GET"], allow_headers=["*"])

def is_stale(key, ttl=None):
    return time.time() - cache[key]["ts"] > (ttl or CACHE_TTL)

async def call_nepse(n, *methods):
    for method in methods:
        fn = getattr(n, method, None)
        if fn:
            try:
                result = await asyncio.to_thread(fn)
                if result is not None:
                    log.info(f"{method}() succeeded")
                    return result
            except Exception as e:
                log.warning(f"{method}() failed: {e}")
    return None

def to_dict(r):
    return r.__dict__ if hasattr(r, '__dict__') else r

@app.get("/")
def root():
    return {"status": "ok", "service": "NEPSE Smart API",
            "endpoints": ["/api/stocks", "/api/indices", "/api/summary", "/api/floorsheet", "/api/stock/{symbol}", "/api/health"]}

@app.get("/api/health")
def health():
    n = get_nepse()
    return {"status": "ok", "nepse_client": n is not None, "stocks_cached": len(cache["stocks"]["data"]), "last_update": cache["stocks"]["ts"]}

@app.get("/api/stocks")
async def get_stocks():
    if not is_stale("stocks") and cache["stocks"]["data"]:
        return JSONResponse({"source": "cache", "data": cache["stocks"]["data"]})
    n = get_nepse()
    if not n:
        return JSONResponse({"error": "client unavailable"}, status_code=503)
    try:
        raw = await call_nepse(n, "getLiveMarket", "getTodayPrice", "getPriceVolume", "getTopTenTurnoverScrips")
        if not raw:
            return JSONResponse({"error": "No data — market may be closed"}, status_code=503)
        stocks = []
        for r in raw:
            r = to_dict(r)
            try:
                prev = float(r.get("previousClosing") or r.get("prevClose") or r.get("lastClosingPrice") or 0)
                ltp  = float(r.get("closingPrice") or r.get("ltp") or r.get("lastTradedPrice") or r.get("currentPrice") or 0)
                if ltp == 0: continue
                chg    = round(ltp - prev, 2)
                chgPct = round((chg / prev * 100) if prev else 0, 2)
                stocks.append({
                    "symbol": str(r.get("stockSymbol") or r.get("symbol") or r.get("securitySymbol") or ""),
                    "name":   str(r.get("securityName") or r.get("stockName") or r.get("companyName") or ""),
                    "sector": str(r.get("businessType") or r.get("sectorName") or r.get("sector") or "Other"),
                    "ltp":    ltp,
                    "open":   float(r.get("openPrice") or r.get("open") or 0),
                    "high":   float(r.get("highPrice") or r.get("high") or ltp),
                    "low":    float(r.get("lowPrice")  or r.get("low")  or ltp),
                    "prev":   prev,
                    "vol":    int(r.get("totalTradeQuantity") or r.get("shareTraded") or r.get("volume") or 0),
                    "to":     float(r.get("totalTradeValue") or r.get("turnover") or r.get("amount") or 0),
                    "chg":    chg, "chgPct": chgPct,
                    "eps":    float(r.get("eps") or 0),
                    "pe":     float(r.get("peRatio") or 0),
                    "bv":     float(r.get("bookValue") or 0),
                })
            except: continue
        cache["stocks"]["data"] = stocks
        cache["stocks"]["ts"]   = time.time()
        log.info(f"{len(stocks)} stocks loaded")
        return JSONResponse({"source": "live", "count": len(stocks), "data": stocks})
    except Exception as e:
        log.error(f"get_stocks error: {e}")
        if cache["stocks"]["data"]:
            return JSONResponse({"source": "stale_cache", "data": cache["stocks"]["data"]})
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/api/indices")
async def get_indices():
    if not is_stale("indices") and cache["indices"]["data"]:
        return JSONResponse({"source": "cache", "data": cache["indices"]["data"]})
    n = get_nepse()
    if not n:
        return JSONResponse({"source": "stale", "data": cache["indices"]["data"]})
    try:
        raw = await call_nepse(n, "getNepseIndex", "getIndexData", "getNepseIndices")
        indices = {}
        for r in (raw or []):
            r = to_dict(r)
            name = str(r.get("indexName") or r.get("name") or "").lower()
            val  = {"value": float(r.get("currentValue") or r.get("indexValue") or 0),
                    "change": float(r.get("change") or 0),
                    "pct":    float(r.get("percentageChange") or r.get("changePercent") or 0),
                    "open":   float(r.get("openValue") or 0),
                    "high":   float(r.get("highValue") or 0),
                    "low":    float(r.get("lowValue")  or 0)}
            if "sensitive" in name and "float" in name: indices["sensFloat"] = val
            elif "sensitive" in name: indices["sensitive"] = val
            elif "float" in name:    indices["float"]     = val
            elif "nepse" in name:    indices["nepse"]     = val
        cache["indices"]["data"] = indices
        cache["indices"]["ts"]   = time.time()
        return JSONResponse({"source": "live", "data": indices})
    except Exception as e:
        log.error(f"get_indices: {e}")
        return JSONResponse({"source": "stale", "data": cache["indices"]["data"]})

@app.get("/api/summary")
async def get_summary():
    if not is_stale("summary") and cache["summary"]["data"]:
        return JSONResponse({"source": "cache", "data": cache["summary"]["data"]})
    n = get_nepse()
    stocks = cache["stocks"]["data"]
    try:
        raw = None
        if n:
            raw = await call_nepse(n, "getMarketSummary", "getSummary")
        if raw:
            r = to_dict(raw[0] if isinstance(raw, list) and raw else raw)
            summary = {"turnover": float(r.get("totalTurnover") or r.get("turnover") or 0),
                       "transactions": int(r.get("totalTransactions") or r.get("transactions") or 0),
                       "advances": int(r.get("advances") or 0),
                       "declines": int(r.get("declines") or 0),
                       "unchanged": int(r.get("unchanged") or 0),
                       "tradedScrips": int(r.get("totalScripsTraded") or 0)}
        else:
            summary = {"turnover": sum(s["to"] for s in stocks),
                       "transactions": len(stocks),
                       "advances":  sum(1 for s in stocks if s["chg"] > 0),
                       "declines":  sum(1 for s in stocks if s["chg"] < 0),
                       "unchanged": sum(1 for s in stocks if s["chg"] == 0),
                       "tradedScrips": len(stocks)}
        cache["summary"]["data"] = summary
        cache["summary"]["ts"]   = time.time()
        return JSONResponse({"source": "live", "data": summary})
    except Exception as e:
        log.error(f"get_summary: {e}")
        fallback = {"turnover": sum(s["to"] for s in stocks), "transactions": len(stocks),
                    "advances": sum(1 for s in stocks if s["chg"] > 0),
                    "declines": sum(1 for s in stocks if s["chg"] < 0),
                    "unchanged": sum(1 for s in stocks if s["chg"] == 0), "tradedScrips": len(stocks)}
        return JSONResponse({"source": "computed", "data": fallback})

@app.get("/api/floorsheet")
async def get_floorsheet():
    if not is_stale("floorsheet", CACHE_TTL_FS) and cache["floorsheet"]["data"]:
        return JSONResponse({"source": "cache", "data": cache["floorsheet"]["data"]})
    n = get_nepse()
    if not n:
        return JSONResponse({"source": "stale", "data": cache["floorsheet"]["data"]})
    try:
        raw = await call_nepse(n, "getFloorSheet", "getFloorsheet")
        from collections import defaultdict
        agg = defaultdict(lambda: {"bought": 0, "sold": 0, "value": 0})
        for row in (raw or []):
            row = to_dict(row)
            try:
                sym    = str(row.get("stockSymbol") or row.get("symbol") or "")
                buyer  = int(row.get("buyerMemberId")  or row.get("buyerId")  or 0)
                seller = int(row.get("sellerMemberId") or row.get("sellerId") or 0)
                qty    = int(row.get("contractQuantity") or row.get("quantity") or 0)
                val    = float(row.get("contractAmount") or row.get("amount") or 0)
                if sym and buyer:  agg[(sym,buyer)]["bought"]  += qty; agg[(sym,buyer)]["value"] += val
                if sym and seller: agg[(sym,seller)]["sold"]   += qty
            except: continue
        result = [{"symbol": sym, "brokerId": bid, "bought": d["bought"], "sold": d["sold"],
                   "netUnits": d["bought"]-d["sold"], "value": round(d["value"],2)}
                  for (sym,bid),d in agg.items()]
        cache["floorsheet"]["data"] = result
        cache["floorsheet"]["ts"]   = time.time()
        log.info(f"Floorsheet: {len(result)} pairs")
        return JSONResponse({"source": "live", "count": len(result), "data": result})
    except Exception as e:
        log.error(f"get_floorsheet: {e}")
        return JSONResponse({"source": "stale", "data": cache["floorsheet"]["data"]})

@app.get("/api/stock/{symbol}")
async def get_stock(symbol: str):
    symbol = symbol.upper()
    stock  = next((s for s in cache["stocks"]["data"] if s["symbol"] == symbol), None)
    if not stock:
        return JSONResponse({"error": f"{symbol} not found"}, status_code=404)
    fs      = cache["floorsheet"]["data"]
    brokers = [b for b in fs if b["symbol"] == symbol]
    return JSONResponse({"stock": stock,
                         "topBuyers":  sorted(brokers, key=lambda b: b["bought"], reverse=True)[:5],
                         "topSellers": sorted(brokers, key=lambda b: b["sold"],   reverse=True)[:5],
                         "netFlow":    sum(b["netUnits"] for b in brokers)})
