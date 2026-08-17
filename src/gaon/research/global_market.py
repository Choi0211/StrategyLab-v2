"""Market-agnostic scope, universe, and public historical-data adapters.

Read-only architecture layer for KR/US and future overseas research. A whole-
market request first acquires a verified full symbol master, then applies a
bounded cross-exchange sample. candidate_count/coverage_mode are retained so a
sample can never be presented as an exhaustive backtest of every listed stock.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import io
import json
import os
import re
from typing import Callable, Mapping
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
import zipfile

from gaon.research.krx_real_pipeline import RealMarketDataUnavailable, YAHOO_CHART_ENDPOINT, _parse_yahoo_chart_payload, utc_now
from gaon.research.real_research import DataQualityEngine, DataQualityReport, MarketCalendar, MarketDataMetadata, MarketDataset, MarketSymbol

GLOBAL_MARKET_SCHEMA_VERSION = 1
DEFAULT_KIS_MASTER_BASE_URL = "https://new.real.download.dws.co.kr/common/master"
DEFAULT_RESEARCH_SAMPLE_SIZE = 5
MAX_RESEARCH_SAMPLE_SIZE = 20
ALLOWED_MASTER_HOSTS = frozenset({"new.real.download.dws.co.kr"})
ALLOWED_YAHOO_HOSTS = frozenset({"query1.finance.yahoo.com", "query2.finance.yahoo.com"})
US_RESERVED_TOKENS = frozenset({"US","USA","NYSE","NASDAQ","AMEX","ETF","ETN","ALL","THE","AND","STOCK","STOCKS","MARKET","RESEARCH","BACKTEST"})

@dataclass(frozen=True)
class MarketScope:
    market: str
    exchanges: tuple[str, ...]
    currencies: tuple[str, ...]
    timezones: tuple[str, ...]
    universe_requested: bool
    label: str
    coverage_note: str = ""
    @property
    def selector(self) -> str:
        return f"{self.market}:{','.join(self.exchanges) if self.exchanges else 'ALL'}"
    @property
    def primary_currency(self) -> str:
        return self.currencies[0] if len(self.currencies) == 1 else "MULTI"
    @property
    def primary_timezone(self) -> str:
        return self.timezones[0] if len(self.timezones) == 1 else "MULTI"
    def to_json(self) -> dict[str, object]:
        return {"schema_version":GLOBAL_MARKET_SCHEMA_VERSION,"market":self.market,"exchanges":list(self.exchanges),"currencies":list(self.currencies),"timezones":list(self.timezones),"universe_requested":self.universe_requested,"label":self.label,"coverage_note":self.coverage_note,"selector":self.selector}

@dataclass(frozen=True)
class MarketUniverseSelection:
    scope: MarketScope
    symbols: tuple[str, ...]
    candidate_count: int
    selected_count: int
    source: str
    coverage_mode: str
    seed: str
    def to_json(self) -> dict[str, object]:
        return {"schema_version":GLOBAL_MARKET_SCHEMA_VERSION,"scope":self.scope.to_json(),"symbols":list(self.symbols),"candidate_count":self.candidate_count,"selected_count":self.selected_count,"source":self.source,"coverage_mode":self.coverage_mode,"seed":self.seed,"exhaustive":self.selected_count==self.candidate_count}

def _norm(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", text.casefold(), flags=re.UNICODE)

def _has_any(value: str, tokens: tuple[str, ...]) -> bool:
    return any(token in value for token in tokens)

def resolve_market_scope(
    text: str,
    *,
    require_universe: bool = False,
) -> MarketScope | None:
    normalized = _norm(text)

    if not normalized:
        return None

    universe_terms = (
        "\uc804\uccb4",
        "\uc804\uc885\ubaa9",
        "\ubaa8\ub4e0\uc885\ubaa9",
        "\uc2dc\uc7a5\uc804\uccb4",
        "universe",
        "allstocks",
        "wholemarket",
        "entiremarket",
        "\uae30\uc900\uc73c\ub85c",
        "\ub300\uc0c1\uc73c\ub85c",
    )

    global_terms = (
        "\uc804\uc138\uacc4\uc8fc\uc2dd",
        "\uc804\uc138\uacc4\uc2dc\uc7a5",
        "\uae00\ub85c\ubc8c\uc8fc\uc2dd",
        "\uae00\ub85c\ubc8c\uc2dc\uc7a5",
        "globalstocks",
        "globalmarket",
        "worldwidestocks",
    )

    kr_terms = (
        "\ud55c\uad6d",
        "\uad6d\ub0b4",
        "\ud55c\uad6d\uc8fc\uc2dd",
        "\uad6d\ub0b4\uc8fc\uc2dd",
        "\ud55c\uad6d\uc2dc\uc7a5",
        "\uad6d\ub0b4\uc2dc\uc7a5",
        "\ucf54\uc2a4\ud53c",
        "\ucf54\uc2a4\ub2e5",
        "krx",
        "kospi",
        "kosdaq",
    )

    us_terms = (
        "\ubbf8\uad6d",
        "\ubbf8\uc7a5",
        "\ubbf8\uad6d\uc8fc\uc2dd",
        "\ubbf8\uad6d\uc2dc\uc7a5",
        "\ubbf8\uc7a5",
        "\ub098\uc2a4\ub2e5",
        "\ub274\uc695\uc99d\uad8c\uac70\ub798\uc18c",
        "\ub274\uc695\uac70\ub798\uc18c",
        "\uc544\uba55\uc2a4",
        "nasdaq",
        "nyse",
        "amex",
        "usstocks",
        "usmarket",
    )

    jp_terms = (
        "\uc77c\ubcf8\uc8fc\uc2dd",
        "\uc77c\ubcf8\uc2dc\uc7a5",
        "\ub3c4\ucfc4\uc99d\uad8c\uac70\ub798\uc18c",
        "\ub3c4\ucfc4\uac70\ub798\uc18c",
        "tse",
        "japanstocks",
        "japanmarket",
    )

    hk_terms = (
        "\ud64d\ucf69\uc8fc\uc2dd",
        "\ud64d\ucf69\uc2dc\uc7a5",
        "\ud64d\ucf69\uac70\ub798\uc18c",
        "hkex",
        "hongkongstocks",
    )

    cn_terms = (
        "\uc911\uad6d\uc8fc\uc2dd",
        "\uc911\uad6d\uc2dc\uc7a5",
        "\uc0c1\ud574\uc8fc\uc2dd",
        "\uc0c1\ud558\uc774\uc8fc\uc2dd",
        "\uc2ec\ucc9c\uc8fc\uc2dd",
        "\uc120\uc804\uc8fc\uc2dd",
        "sse",
        "szse",
        "chinastocks",
    )

    universe_requested = _has_any(
        normalized,
        universe_terms,
    )

    has_global = _has_any(
        normalized,
        global_terms,
    )

    has_kr = _has_any(
        normalized,
        kr_terms,
    )

    has_us = _has_any(
        normalized,
        us_terms,
    )

    # Explicit global wording wins first.
    if has_global:
        return MarketScope(
            "GLOBAL",
            (
                "KOSPI",
                "KOSDAQ",
                "NASDAQ",
                "NYSE",
                "AMEX",
            ),
            (
                "KRW",
                "USD",
            ),
            (
                "Asia/Seoul",
                "America/New_York",
            ),
            True,
            "GLOBAL_CONFIGURED",
            (
                "Configured global production scope "
                "currently includes KR+US by default."
            ),
        )

    # KR+US must win before either individual market.
    if has_kr and has_us:
        return MarketScope(
            "MULTI",
            (
                "KOSPI",
                "KOSDAQ",
                "NASDAQ",
                "NYSE",
                "AMEX",
            ),
            (
                "KRW",
                "USD",
            ),
            (
                "Asia/Seoul",
                "America/New_York",
            ),
            True,
            "KR+US",
            (
                "KR+US verified master universes with "
                "bounded cross-market sampling"
            ),
        )

    if has_kr:
        has_kospi = (
            "\ucf54\uc2a4\ud53c" in normalized
            or "kospi" in normalized
        )
        has_kosdaq = (
            "\ucf54\uc2a4\ub2e5" in normalized
            or "kosdaq" in normalized
        )

        if has_kospi and not has_kosdaq:
            exchanges = ("KOSPI",)
        elif has_kosdaq and not has_kospi:
            exchanges = ("KOSDAQ",)
        else:
            exchanges = (
                "KOSPI",
                "KOSDAQ",
            )

        return MarketScope(
            "KR",
            exchanges,
            ("KRW",),
            ("Asia/Seoul",),
            universe_requested,
            "KR",
        )

    if has_us:
        selected_exchanges = []

        if (
            "nasdaq" in normalized
            or "\ub098\uc2a4\ub2e5" in normalized
        ):
            selected_exchanges.append("NASDAQ")

        if (
            "nyse" in normalized
            or "\ub274\uc695\uc99d\uad8c\uac70\ub798\uc18c" in normalized
            or "\ub274\uc695\uac70\ub798\uc18c" in normalized
        ):
            selected_exchanges.append("NYSE")

        if (
            "amex" in normalized
            or "\uc544\uba55\uc2a4" in normalized
        ):
            selected_exchanges.append("AMEX")

        if selected_exchanges:
            exchanges = tuple(
                dict.fromkeys(selected_exchanges)
            )
            universe_requested = True
        else:
            exchanges = (
                "NASDAQ",
                "NYSE",
                "AMEX",
            )

        return MarketScope(
            "US",
            exchanges,
            ("USD",),
            ("America/New_York",),
            universe_requested,
            "US",
        )

    if _has_any(normalized, jp_terms):
        return MarketScope(
            "JP",
            ("TSE",),
            ("JPY",),
            ("Asia/Tokyo",),
            universe_requested,
            "JP",
        )

    if _has_any(normalized, hk_terms):
        return MarketScope(
            "HK",
            ("HKEX",),
            ("HKD",),
            ("Asia/Hong_Kong",),
            universe_requested,
            "HK",
        )

    if _has_any(normalized, cn_terms):
        if (
            "\uc0c1\ud574" in normalized
            or "\uc0c1\ud558\uc774" in normalized
            or "sse" in normalized
        ):
            exchanges = ("SSE",)

        elif (
            "\uc2ec\ucc9c" in normalized
            or "\uc120\uc804" in normalized
            or "szse" in normalized
        ):
            exchanges = ("SZSE",)

        else:
            exchanges = (
                "SSE",
                "SZSE",
            )

        return MarketScope(
            "CN",
            exchanges,
            ("CNY",),
            ("Asia/Shanghai",),
            universe_requested,
            "CN",
        )

    return None

def is_market_universe_request(text: str) -> bool:
    s=resolve_market_scope(text); return s is not None and s.universe_requested

def is_market_research_request(text: str) -> bool:
    if resolve_market_scope(text) is None:
        return False

    return _has_any(
        _norm(text),
        (
            "\uc5f0\uad6c",
            "\ubd84\uc11d",
            "\uac80\uc99d",
            "\ubc31\ud14c\uc2a4\ud2b8",
            "research",
            "analyze",
            "validate",
            "backtest",
        ),
    )


def extract_market_symbols(text: str, scope: MarketScope | None) -> tuple[str, ...]:
    if scope is None: return ()
    if scope.market=="KR": return tuple(dict.fromkeys(re.findall(r"(?<!\d)(\d{6})(?!\d)",text)))
    if scope.market=="US":
        tokens=re.findall(r"(?<![A-Za-z0-9])([A-Z]{1,5}(?:[.-][A-Z])?)(?![A-Za-z0-9])",text)
        return tuple(dict.fromkeys(x for x in tokens if x not in US_RESERVED_TOKENS))
    return ()

def research_sample_size(env: Mapping[str,str] | None=None) -> int:
    src=env or os.environ
    try: value=int(str(src.get("GAON_GLOBAL_RESEARCH_MAX_SYMBOLS",DEFAULT_RESEARCH_SAMPLE_SIZE)).strip())
    except ValueError: value=DEFAULT_RESEARCH_SAMPLE_SIZE
    return max(1,min(MAX_RESEARCH_SAMPLE_SIZE,value))

def select_bounded_universe(candidates: tuple[MarketSymbol,...], scope: MarketScope, *, requested_size: int, seed: str, source: str, avoid_symbols: frozenset[str] = frozenset()) -> MarketUniverseSelection:
    # Patch 8.4: ``avoid_symbols`` (bounded - callers pass an already-capped
    # set, e.g. a strategy candidate's tracked excluded_symbols) lets a
    # NEW research cycle skip symbols a PRIOR cycle already confirmed
    # unusable, instead of spending research budget re-discovering the
    # same exclusion. Falls back to the full candidate pool if excluding
    # them would leave nothing to sample from - never raises just because
    # every candidate happens to be on the avoid list.
    avoid={str(item).upper() for item in avoid_symbols}
    filtered=tuple(x for x in candidates if x.symbol.upper() not in avoid)
    if filtered:
        candidates=filtered
    unique={(x.exchange.upper(),x.symbol.upper()):x for x in candidates if not scope.exchanges or x.exchange.upper() in set(scope.exchanges)}
    rows=tuple(unique.values())
    if not rows: raise RealMarketDataUnavailable("real_data_unavailable: market universe contains no eligible stock symbols")
    size=max(1,min(requested_size,len(rows))); groups={}
    for x in rows: groups.setdefault(x.exchange.upper(),[]).append(x)
    def score(x): return (hashlib.sha256(f"{seed}|{scope.selector}|{x.exchange}|{x.symbol}".encode()).hexdigest(),x.symbol)
    selected=[]
    for ex in scope.exchanges:
        group=groups.get(ex,[])
        if group and len(selected)<size: selected.append(min(group,key=score))
    used={(x.exchange.upper(),x.symbol.upper()) for x in selected}
    selected.extend(sorted((x for x in rows if (x.exchange.upper(),x.symbol.upper()) not in used),key=score)[:max(0,size-len(selected))])
    symbols=tuple(x.symbol.upper() for x in selected[:size])
    return MarketUniverseSelection(scope,symbols,len(rows),len(symbols),source,"exhaustive" if len(symbols)==len(rows) else "bounded_cross_exchange_sample",seed)

MasterBytesFetcher=Callable[[str,float],bytes]
HttpOpener=Callable[[Request,float],object]

def _default_master_fetcher(url: str, timeout: float) -> bytes:
    with urlopen(Request(url,headers={"User-Agent":"StrategyLab-v2 Gaon market universe"}),timeout=timeout) as r: return r.read()

def _validate_https_host(url: str, allowed: frozenset[str]) -> None:
    p=urlparse(url)
    if p.scheme!="https" or p.hostname not in allowed: raise RealMarketDataUnavailable("real_data_unavailable: market provider URL failed HTTPS/host policy")

def _zip_payload(raw: bytes, suffix: str) -> bytes:
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            names=[n for n in z.namelist() if n.lower().endswith(suffix.lower())]
            if not names: raise RealMarketDataUnavailable("real_data_unavailable: master archive missing expected payload")
            return z.read(names[0])
    except RealMarketDataUnavailable: raise
    except Exception as exc: raise RealMarketDataUnavailable(f"real_data_unavailable: invalid master archive: {exc.__class__.__name__}") from exc

class KISMasterUniverseProvider:
    source="real:kis-master"; market_agnostic=True
    _domestic={"KOSPI":("kospi_code.mst.zip",".mst",228),"KOSDAQ":("kosdaq_code.mst.zip",".mst",222)}
    _overseas={"NASDAQ":"nas","NYSE":"nys","AMEX":"ams","TSE":"tse","HKEX":"hks","SSE":"shs","SZSE":"szs"}
    _markets={"KOSPI":"KR","KOSDAQ":"KR","NASDAQ":"US","NYSE":"US","AMEX":"US","TSE":"JP","HKEX":"HK","SSE":"CN","SZSE":"CN"}
    def __init__(self,*,base_url: str=DEFAULT_KIS_MASTER_BASE_URL,fetcher: MasterBytesFetcher|None=None,timeout_seconds: float=20.0): self._base=base_url.rstrip("/"); self._fetcher=fetcher or _default_master_fetcher; self._timeout=timeout_seconds
    @classmethod
    def from_env(cls,env: Mapping[str,str]|None=None):
        src=env or os.environ; return cls(base_url=str(src.get("GAON_KIS_MASTER_BASE_URL",DEFAULT_KIS_MASTER_BASE_URL)),timeout_seconds=float(src.get("GAON_MARKET_PROVIDER_TIMEOUT_SECONDS","20")))
    def fetch_universe(self,market: str|MarketScope) -> tuple[MarketSymbol,...]:
        scope=market if isinstance(market,MarketScope) else scope_from_selector(str(market)); rows=[]
        for ex in scope.exchanges:
            if ex in self._domestic: rows.extend(self._fetch_domestic(ex))
            elif ex in self._overseas: rows.extend(self._fetch_overseas(ex))
            else: raise RealMarketDataUnavailable(f"real_data_unavailable: unsupported exchange master {ex}")
        return tuple({(x.exchange,x.symbol):x for x in rows}.values())
    def _fetch_domestic(
        self,
        ex: str,
    ) -> tuple[MarketSymbol, ...]:
        archive_name, suffix, expected_tail_width = self._domestic[ex]

        url = f"{self._base}/{archive_name}"

        _validate_https_host(
            url,
            ALLOWED_MASTER_HOSTS,
        )

        # KIS domestic .mst files are byte-oriented fixed-width records.
        #
        # Verified production layout:
        #   bytes  0:9   = short symbol, padded
        #   bytes  9:21  = ISIN
        #   bytes 21:61  = Korean/ASCII display name in CP949
        #   bytes 61:63  = security group ("ST" for listed stock)
        #
        # KOSPI records are currently 288 bytes and KOSDAQ records
        # are currently 282 bytes. Do not slice after decoding CP949:
        # Korean characters are multi-byte and would shift offsets.
        payload = _zip_payload(
            self._fetcher(
                url,
                self._timeout,
            ),
            suffix,
        )

        rows: list[MarketSymbol] = []

        for raw_line in payload.splitlines():
            if len(raw_line) < 63:
                continue

            try:
                symbol = (
                    raw_line[0:9]
                    .decode(
                        "ascii",
                        errors="strict",
                    )
                    .strip()
                )

                name = (
                    raw_line[21:61]
                    .decode(
                        "cp949",
                        errors="strict",
                    )
                    .strip()
                )

                group = (
                    raw_line[61:63]
                    .decode(
                        "ascii",
                        errors="strict",
                    )
                    .strip()
                )

            except UnicodeDecodeError:
                continue

            if re.fullmatch(
                r"\d{6}",
                symbol,
            ) is None:
                continue

            if group != "ST":
                continue

            rows.append(
                MarketSymbol(
                    symbol,
                    name or symbol,
                    "KR",
                    ex,
                )
            )

        if not rows:
            raise RealMarketDataUnavailable(
                "real_data_unavailable: "
                f"KIS {ex} master parsed no stock symbols"
            )

        return tuple(rows)

    def _fetch_overseas(
        self,
        ex: str,
    ) -> tuple[MarketSymbol, ...]:
        code = self._overseas[ex]
        url = f"{self._base}/{code}mst.cod.zip"

        _validate_https_host(
            url,
            ALLOWED_MASTER_HOSTS,
        )

        payload = (
            _zip_payload(
                self._fetcher(
                    url,
                    self._timeout,
                ),
                ".cod",
            )
            .decode(
                "cp949",
                errors="strict",
            )
        )

        rows: list[MarketSymbol] = []

        for line in payload.splitlines():
            fields = [
                value.strip()
                for value in line.split("\t")
            ]

            if len(fields) < 10:
                continue

            symbol = fields[4]
            name = (
                fields[7]
                or fields[6]
                or fields[4]
            )
            security_type = fields[8]

            # KIS overseas master:
            # type "2" = listed stock.
            if security_type != "2":
                continue

            # Reject obviously unsupported ticker syntax before
            # constructing a MarketSymbol.
            if re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9.\-]{0,15}",
                symbol or "",
            ) is None:
                continue

            try:
                row = MarketSymbol(
                    symbol.upper(),
                    name,
                    self._markets[ex],
                    ex,
                )
            except ValueError:
                # KIS contains a small number of exchange-valid
                # special identifiers that are outside StrategyLab's
                # SAFE_ID contract. Fail closed for those records
                # instead of aborting the entire market universe.
                continue

            rows.append(row)

        if not rows:
            raise RealMarketDataUnavailable(
                "real_data_unavailable: "
                f"KIS {ex} master parsed no stock symbols"
            )

        return tuple(rows)

class _ObservedCalendar:
    def __init__(self,dates): self._dates=tuple(dates)
    def expected_open_dates(self,*,start_date,end_date): return tuple(x for x in self._dates if start_date<=x<=end_date)

class GlobalMarketDataProvider:
    source="real:kis-master+yahoo-chart"; market_agnostic=True
    def __init__(self,*,universe_provider: KISMasterUniverseProvider|None=None,opener: HttpOpener|None=None,timeout_seconds: float=20.0,yahoo_endpoint: str=YAHOO_CHART_ENDPOINT):
        self._universe=universe_provider or KISMasterUniverseProvider(timeout_seconds=timeout_seconds); self._opener=opener or _urlopen_adapter; self._timeout=timeout_seconds; self._endpoint=yahoo_endpoint; self._symbols={}
    @classmethod
    def from_env(cls,env: Mapping[str,str]|None=None):
        src=env or os.environ; timeout=float(src.get("GAON_MARKET_PROVIDER_TIMEOUT_SECONDS","20")); return cls(universe_provider=KISMasterUniverseProvider.from_env(src),timeout_seconds=timeout,yahoo_endpoint=str(src.get("GAON_YAHOO_CHART_ENDPOINT",YAHOO_CHART_ENDPOINT)))
    def fetch_universe(self,market):
        rows=self._universe.fetch_universe(market)
        for x in rows: self._symbols[x.symbol.upper()]=x
        return rows
    def fetch_bars(self,symbol: str,*,start_date: str,end_date: str,timeframe: str="daily") -> MarketDataset:
        if timeframe!="daily": raise RealMarketDataUnavailable("real_data_unavailable: only daily timeframe is supported")
        ref=self._symbols.get(symbol.upper()) or infer_market_symbol(symbol); ys=yahoo_symbol_for(ref); endpoint=self._endpoint.format(symbol=ys); _validate_https_host(endpoint,ALLOWED_YAHOO_HOSTS)
        p1=int(datetime.fromisoformat(start_date).replace(tzinfo=UTC).timestamp()); p2=int((datetime.fromisoformat(end_date)+timedelta(days=1)).replace(tzinfo=UTC).timestamp())
        q=urlencode({"period1":p1,"period2":p2,"interval":"1d","events":"history","includeAdjustedClose":"true"}); req=Request(f"{endpoint}?{q}",headers={"User-Agent":"StrategyLab-v2 Gaon global research"})
        try: payload=json.loads(self._opener(req,self._timeout).read().decode("utf-8"))
        except Exception as exc: raise RealMarketDataUnavailable(f"real_data_unavailable: Yahoo global provider {exc.__class__.__name__}") from exc
        bars=tuple(x for x in _parse_yahoo_chart_payload(payload,ref.symbol.upper()) if start_date<=x.timestamp<=end_date)
        if not bars: raise RealMarketDataUnavailable("real_data_unavailable: Yahoo returned no bars in requested period")
        meta=MarketDataMetadata(self.source,ref.exchange,timeframe,bars[0].timestamp,bars[-1].timestamp,True,utc_now(),False)
        return MarketDataset(f"dataset:global:{ref.market}:{ref.exchange}:{ref.symbol.upper()}:{timeframe}:{bars[0].timestamp}:{bars[-1].timestamp}",(ref,),bars,meta)
    def validate_dataset(self,dataset: MarketDataset) -> DataQualityReport:
        dates=tuple(dict.fromkeys(x.timestamp for x in dataset.bars)); return DataQualityEngine().validate(dataset,min_bars=60,calendar=_ObservedCalendar(dates))
    def fetch_trading_calendar(self,market: str,*,start_date: str,end_date: str) -> MarketCalendar: return MarketCalendar(market,(),())

def _urlopen_adapter(req: Request,timeout: float): return urlopen(req,timeout=timeout)
def infer_market_symbol(symbol: str) -> MarketSymbol:
    u=symbol.upper(); return MarketSymbol(u,u,"KR","KOSPI") if re.fullmatch(r"\d{6}",u) else MarketSymbol(u,u,"US","NASDAQ")
def yahoo_symbol_for(symbol: MarketSymbol) -> str:
    u,e=symbol.symbol.upper(),symbol.exchange.upper()
    if e=="KOSPI": return f"{u}.KS"
    if e=="KOSDAQ": return f"{u}.KQ"
    if e in {"NASDAQ","NYSE","AMEX"}: return u.replace(".","-")
    if e=="TSE": return f"{u}.T"
    if e=="HKEX": return f"{(u.lstrip('0') or '0').zfill(4)}.HK"
    if e=="SSE": return f"{u}.SS"
    if e=="SZSE": return f"{u}.SZ"
    raise RealMarketDataUnavailable(f"real_data_unavailable: Yahoo symbol mapping unsupported for exchange {e}")
def scope_from_selector(selector: str) -> MarketScope:
    raw=selector.upper().strip(); market,extext=(raw.split(":",1)+[""])[:2] if ":" in raw else (raw,""); ex=tuple(x for x in extext.split(",") if x and x!="ALL")
    defaults={"KR":(("KOSPI","KOSDAQ"),("KRW",),("Asia/Seoul",)),"US":(("NASDAQ","NYSE","AMEX"),("USD",),("America/New_York",)),"JP":(("TSE",),("JPY",),("Asia/Tokyo",)),"HK":(("HKEX",),("HKD",),("Asia/Hong_Kong",)),"CN":(("SSE","SZSE"),("CNY",),("Asia/Shanghai",)),"MULTI":(("KOSPI","KOSDAQ","NASDAQ","NYSE","AMEX"),("KRW","USD"),("Asia/Seoul","America/New_York")),"GLOBAL":(("KOSPI","KOSDAQ","NASDAQ","NYSE","AMEX"),("KRW","USD"),("Asia/Seoul","America/New_York"))}
    if market in {"KOSPI","KOSDAQ","ALL"}: return MarketScope("KR",("KOSPI","KOSDAQ") if market=="ALL" else (market,),("KRW",),("Asia/Seoul",),True,"KR")
    if market not in defaults: raise RealMarketDataUnavailable(f"real_data_unavailable: unsupported market selector {selector}")
    dex,c,tz=defaults[market]; return MarketScope(market,ex or dex,c,tz,True,market)
def global_market_architecture_release_check() -> dict[str, object]:
    scopes = {
        "kr": resolve_market_scope(
            "\ud55c\uad6d \uc8fc\uc2dd "
            "\uc804\uccb4\ub97c \uc5f0\uad6c\ud574\uc918"
        ),
        "us": resolve_market_scope(
            "\ubbf8\uad6d \uc8fc\uc2dd "
            "\uc804\uccb4\ub97c \uc5f0\uad6c\ud574\uc918"
        ),
        "nasdaq": resolve_market_scope(
            "\ub098\uc2a4\ub2e5 \uc804\uccb4\ub97c "
            "\uc5f0\uad6c\ud574\uc918"
        ),
        "multi": resolve_market_scope(
            "\ud55c\uad6d\uacfc \ubbf8\uad6d \uc8fc\uc2dd "
            "\uc804\uccb4\ub97c \ube44\uad50 "
            "\uc5f0\uad6c\ud574\uc918"
        ),
    }

    if any(scope is None for scope in scopes.values()):
        raise RealMarketDataUnavailable(
            "real_data_unavailable: "
            "market scope release check failed"
        )

    us = scopes["us"]
    assert us is not None

    fixture = (
        MarketSymbol("AAPL", "Apple", "US", "NASDAQ"),
        MarketSymbol("MSFT", "Microsoft", "US", "NASDAQ"),
        MarketSymbol("IBM", "IBM", "US", "NYSE"),
        MarketSymbol("BMY", "BMY", "US", "NYSE"),
        MarketSymbol("ABC", "ABC", "US", "AMEX"),
    )

    sample = select_bounded_universe(
        fixture,
        us,
        requested_size=3,
        seed="release-check",
        source="release-check",
    )

    return {
        "schema_version": GLOBAL_MARKET_SCHEMA_VERSION,
        "status": "pass",
        "markets": {
            key: value.to_json() if value else None
            for key, value in scopes.items()
        },
        "sample": sample.to_json(),
        "automatic_order": False,
        "automatic_champion_promotion": False,
        "automatic_config_apply": False,
    }
