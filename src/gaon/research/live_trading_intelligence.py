from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
import json, os
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Iterable, Mapping, Sequence
from gaon.research.real_research import MarketSymbol

SCHEMA_VERSION = 1
DEFAULT_ROOT = "/root/MyMoneyGuard"
ALLOWLIST = frozenset({
    "order_ledger.json","trade_state.json","trade_state_daytrade.json",
    "us_trade_state.json","us_trade_state_daytrade.json",
})
DENYLIST = frozenset({".env","kis_token.json"})
CONFIRMED = "FILLED_CONFIRMED"

@dataclass(frozen=True)
class LiveOrder:
    evidence_id: str
    observed_at: str
    market: str
    strategy: str
    side: str
    symbol: str
    qty: float
    price: float
    status: str
    detail: str
    source_path: str
    reconciled_at: str | None
    completeness: str

    @property
    def confirmed(self) -> bool:
        return self.status == CONFIRMED

    def to_json(self):
        return {
            "evidence_id":self.evidence_id,"observed_at":self.observed_at,
            "market":self.market,"strategy":self.strategy,"side":self.side,
            "symbol":self.symbol,"qty":self.qty,"price":self.price,
            "status":self.status,"detail":self.detail,"source_path":self.source_path,
            "reconciled_at":self.reconciled_at,"completeness":self.completeness,
            "live_performance_evidence":self.confirmed,
        }

@dataclass(frozen=True)
class LiveRoundTrip:
    market: str
    strategy: str
    symbol: str
    qty: float
    entry_price: float
    exit_price: float
    entry_at: str
    exit_at: str
    realized_pnl: float
    realized_return: float
    entry_evidence_id: str
    exit_evidence_id: str

@dataclass(frozen=True)
class LiveSnapshot:
    root: str
    orders: tuple[LiveOrder,...]
    round_trips: tuple[LiveRoundTrip,...]
    unmatched_sells: tuple[LiveOrder,...]
    open_positions: tuple[dict[str,object],...]
    warnings: tuple[str,...]

    def metrics(self):
        return {
            "confirmed_fill_count":sum(x.confirmed for x in self.orders),
            "reconstructed_round_trip_count":len(self.round_trips),
            "open_position_count":len(self.open_positions),
            "unmatched_sell_count":len(self.unmatched_sells),
            "failed_order_count":sum(x.status=="ORDER_FAILED" for x in self.orders),
            "unconfirmed_order_count":sum(x.status=="ORDER_SENT_NOT_CONFIRMED" for x in self.orders),
            "expired_order_count":sum(x.status=="EXPIRED_NOT_FILLED" for x in self.orders),
            "dry_run_count":sum(x.status=="DRY_RUN" for x in self.orders),
            "live_performance_available":bool(self.round_trips),
        }

@dataclass(frozen=True)
class LiveFeedback:
    market: str
    completed_trade_count: int
    win_rate: float | None
    failed_order_count: int
    unconfirmed_order_count: int
    unmatched_sell_count: int
    open_position_count: int
    classifications: tuple[str,...]
    hypotheses: tuple[dict[str,object],...]

    def to_json(self):
        return {
            "market":self.market,"completed_trade_count":self.completed_trade_count,
            "win_rate":self.win_rate,"failed_order_count":self.failed_order_count,
            "unconfirmed_order_count":self.unconfirmed_order_count,
            "unmatched_sell_count":self.unmatched_sell_count,
            "open_position_count":self.open_position_count,
            "classifications":list(self.classifications),
            "hypotheses":[dict(x) for x in self.hypotheses],
            "strategy_mutated":False,"order_executed":False,
            "champion_promoted":False,"approval_required":True,
        }

class LiveTradingEvidenceAdapter:
    def __init__(self, root: str|Path|None=None, max_bytes: int=2_000_000):
        configured=root or os.environ.get("GAON_MYMONEYGUARD_ROOT") or DEFAULT_ROOT
        self.root=Path(configured).expanduser().resolve(strict=False)
        self.max_bytes=max_bytes

    def available(self):
        return self.root.is_dir() and (self.root/"order_ledger.json").is_file()

    def _read_json(self, name: str, missing_ok: bool=False):
        if name in DENYLIST: raise PermissionError("secret file denied")
        if name not in ALLOWLIST: raise PermissionError("file not allowlisted")
        if "/" in name or "\\" in name or ".." in name: raise PermissionError("unsafe path")
        path=(self.root/name).resolve(strict=False)
        try: path.relative_to(self.root)
        except ValueError as exc: raise PermissionError("path traversal") from exc
        if not path.exists():
            if missing_ok: return None
            raise FileNotFoundError(path)
        if path.stat().st_size > self.max_bytes: raise ValueError("file too large")
        with path.open("r",encoding="utf-8") as f: return json.load(f)

    def load(self):
        if not self.available():
            return LiveSnapshot(str(self.root),(),(),(),(),("live_evidence_unavailable",))
        ledger=self._read_json("order_ledger.json")
        raw=ledger.get("orders",[]) if isinstance(ledger,dict) else []
        if not isinstance(raw,list): raise ValueError("orders must be list")
        orders=[]; warnings=[]
        for i,item in enumerate(raw):
            if not isinstance(item,dict):
                warnings.append(f"order_{i}:malformed"); continue
            try: orders.append(self._normalize(item,i))
            except Exception as exc: warnings.append(f"order_{i}:{exc.__class__.__name__}")
        trips,unmatched=reconstruct_round_trips(tuple(orders))
        positions=[]
        for filename,market,strategy in (
            ("trade_state_daytrade.json","KR","daytrade"),
            ("us_trade_state.json","US","turtle"),
            ("us_trade_state_daytrade.json","US","daytrade"),
        ):
            state=self._read_json(filename,missing_ok=True)
            if not isinstance(state,dict): continue
            ps=state.get("positions",{})
            if not isinstance(ps,dict): continue
            for symbol,p in ps.items():
                if not isinstance(p,dict): continue
                qty=_num(p.get("qty",p.get("remaining_qty",0)))
                if qty<=0: continue
                positions.append({
                    "market":market,"strategy":strategy,"symbol":str(symbol).upper(),
                    "qty":qty,"entry_price":p.get("entry_price"),
                    "source_path":str((self.root/filename).resolve(strict=False)),
                    "observed_at":state.get("date") or state.get("reconciled_at"),
                })
        return LiveSnapshot(str(self.root),tuple(orders),trips,unmatched,tuple(positions),tuple(warnings))

    def _normalize(self, x: Mapping[str,object], i: int):
        market=str(x.get("market","")).upper().strip()
        strategy=str(x.get("strategy","")).lower().strip()
        side=str(x.get("side","")).upper().strip()
        symbol=str(x.get("symbol","")).upper().strip()
        status=str(x.get("status","")).upper().strip()
        at=str(x.get("datetime","")).strip()
        qty=_num(x.get("qty")); price=_num(x.get("price"))
        if not market or not strategy or side not in {"BUY","SELL"} or not symbol or not status or not at:
            raise ValueError("missing identity")
        if qty<=0 or price<0: raise ValueError("invalid numeric evidence")
        completeness="confirmed" if status==CONFIRMED else ("non_live" if status in {"DRY_RUN","EXPIRED_NOT_FILLED"} else "unresolved")
        raw=f"{i}|{at}|{market}|{strategy}|{side}|{symbol}|{qty}|{price}|{status}"
        eid="live-order:"+sha256(raw.encode()).hexdigest()[:20]
        return LiveOrder(eid,at,market,strategy,side,symbol,qty,price,status,
            str(x.get("detail","") or ""),str((self.root/"order_ledger.json").resolve(strict=False)),
            str(x.get("reconciled_at")) if x.get("reconciled_at") else None,completeness)

def reconstruct_round_trips(orders: Sequence[LiveOrder]):
    inventory={}; trips=[]; unmatched=[]
    for order in sorted((x for x in orders if x.confirmed),key=lambda x:(x.observed_at,x.evidence_id)):
        key=(order.market,order.strategy,order.symbol)
        if order.side=="BUY":
            inventory.setdefault(key,[]).append([order.qty,order]); continue
        remaining=order.qty; lots=inventory.setdefault(key,[])
        while remaining>1e-12 and lots:
            lot_qty,buy=lots[0]; paired=min(remaining,float(lot_qty))
            pnl=(order.price-buy.price)*paired
            ret=(order.price/buy.price)-1 if buy.price>0 else 0.0
            trips.append(LiveRoundTrip(order.market,order.strategy,order.symbol,paired,
                buy.price,order.price,buy.observed_at,order.observed_at,pnl,ret,
                buy.evidence_id,order.evidence_id))
            remaining-=paired; lot_qty=float(lot_qty)-paired
            if lot_qty<=1e-12: lots.pop(0)
            else: lots[0][0]=lot_qty
        if remaining>1e-12: unmatched.append(order)
    return tuple(trips),tuple(unmatched)

def build_feedback(snapshot: LiveSnapshot, market: str|None=None):
    wanted=None if market in {None,"","MULTI","GLOBAL"} else str(market).upper()
    trips=tuple(x for x in snapshot.round_trips if wanted is None or x.market==wanted)
    orders=tuple(x for x in snapshot.orders if wanted is None or x.market==wanted)
    unmatched=tuple(x for x in snapshot.unmatched_sells if wanted is None or x.market==wanted)
    positions=tuple(x for x in snapshot.open_positions if wanted is None or x["market"]==wanted)
    failed=sum(x.status=="ORDER_FAILED" for x in orders)
    unconfirmed=sum(x.status=="ORDER_SENT_NOT_CONFIRMED" for x in orders)
    returns=[x.realized_return for x in trips]
    cls=[]; hypotheses=[]
    if failed:
        cls.append("execution_failure")
        hypotheses.append(_hyp("execution-reliability","반복된 주문 실패는 전략 손실과 별개의 실행 리스크일 수 있다.",
            tuple(x.evidence_id for x in orders if x.status=="ORDER_FAILED")))
    if unconfirmed: cls.append("execution_uncertainty")
    if unmatched: cls.append("incomplete_history")
    if len(trips)<5:
        cls.append("insufficient_live_sample")
        hypotheses.append(_hyp("insufficient-live-history","확정된 실거래 왕복 표본이 적어 성과 일반화가 어렵다.",
            tuple(x.exit_evidence_id for x in trips)))
    win_rate=(sum(r>0 for r in returns)/len(returns)) if returns else None
    return LiveFeedback(wanted or "MULTI",len(trips),round(win_rate,6) if win_rate is not None else None,
        failed,unconfirmed,len(unmatched),len(positions),tuple(dict.fromkeys(cls)),_dedupe(hypotheses))

def production_feedback(market: str|None=None):
    adapter=LiveTradingEvidenceAdapter()
    if not adapter.available(): return None
    try: return build_feedback(adapter.load(),market)
    except Exception: return None

def adaptive_budget(env: Mapping[str,str]|None, initial_size: int, candidate_count: int):
    src=env or os.environ
    explicit=src.get("GAON_GLOBAL_RESEARCH_MAX_SYMBOLS")
    raw=explicit if explicit not in {None,""} else src.get("GAON_ADAPTIVE_RESEARCH_BUDGET_SYMBOLS","15")
    try: n=int(str(raw))
    except ValueError: n=15
    return min(max(initial_size,n),candidate_count,50)

def adaptive_batches(candidates: Sequence[MarketSymbol], exchanges: Sequence[str], used_symbols: Iterable[str],
                     limit: int, batch_size: int, seed: str):
    used={str(x).upper() for x in used_symbols}
    if len(used)>=limit: return ()
    exs=tuple(dict.fromkeys(str(x).upper() for x in exchanges))
    groups={x:[] for x in exs}
    for item in candidates:
        s=item.symbol.upper(); e=item.exchange.upper()
        if s in used or e not in groups: continue
        groups[e].append(item)
    score=lambda x:sha256(f"{seed}|{x.exchange}|{x.symbol}".encode()).hexdigest()
    for rows in groups.values(): rows.sort(key=score)
    ordered=[]
    while len(used)+len(ordered)<limit:
        progress=False
        for ex in exs:
            if groups[ex]:
                s=groups[ex].pop(0).symbol.upper()
                if s not in used and s not in ordered: ordered.append(s); progress=True
                if len(used)+len(ordered)>=limit: break
        if not progress: break
    return tuple(tuple(ordered[i:i+batch_size]) for i in range(0,len(ordered),batch_size))

def live_report_lines(feedback: LiveFeedback|None):
    if feedback is None: return ()
    lines=["","[실거래에서 발견한 점]"]
    if feedback.failed_order_count:
        lines.append(f"- 실행 문제: 확정 주문 실패 {feedback.failed_order_count}건이 있습니다. 전략 손실과 구분합니다.")
    if feedback.unconfirmed_order_count:
        lines.append(f"- 체결 불확실 기록 {feedback.unconfirmed_order_count}건이 있습니다.")
    if feedback.unmatched_sell_count:
        lines.append(f"- 진입 체결을 확인할 수 없는 매도 {feedback.unmatched_sell_count}건은 손익을 계산하지 않았습니다.")
    if feedback.completed_trade_count:
        w=f"{feedback.win_rate*100:.1f}%" if feedback.win_rate is not None else "계산 불가"
        lines.append(f"- 확인 가능한 완료 거래 {feedback.completed_trade_count}건 / 승률 {w}")
    else: lines.append("- 확인 가능한 완료 거래 표본이 아직 부족합니다.")
    if feedback.open_position_count: lines.append(f"- 열린 포지션 {feedback.open_position_count}건을 상태 파일에서 확인했습니다.")
    return tuple(lines)

def _hyp(label,statement,refs):
    fp=sha256(json.dumps({"label":label,"statement":statement,"refs":sorted(refs)},ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    return {"hypothesis_id":"live-hypothesis:"+fp[:20],"fingerprint":fp,"label":label,
        "statement":statement,"evidence_refs":list(refs),"status":"proposed",
        "strategy_mutated":False,"order_executed":False,"promotion_performed":False}

def _dedupe(items):
    seen=set(); out=[]
    for x in items:
        fp=x["fingerprint"]
        if fp in seen: continue
        seen.add(fp); out.append(dict(x))
    return tuple(out)

def _num(v):
    if isinstance(v,bool): raise ValueError("boolean numeric evidence")
    return float(v)

def release_check():
    with TemporaryDirectory() as tmp:
        root=Path(tmp)
        orders={"orders":[
            {"datetime":"2026-06-16 06:20:12","market":"US","strategy":"turtle","side":"BUY","symbol":"HBAN","qty":1,"price":17.5278,"status":"FILLED_CONFIRMED","detail":"","reconciled_at":None},
            {"datetime":"2026-07-29 06:20:07","market":"US","strategy":"turtle","side":"SELL","symbol":"HBAN","qty":1,"price":17.16,"status":"FILLED_CONFIRMED","detail":"","reconciled_at":None},
            {"datetime":"2026-08-07 06:20:05","market":"US","strategy":"turtle","side":"SELL","symbol":"BXP","qty":1,"price":68.92,"status":"ORDER_FAILED","detail":"","reconciled_at":None},
            {"datetime":"2026-08-13 06:20:08","market":"US","strategy":"turtle","side":"SELL","symbol":"BXP","qty":1,"price":67.49,"status":"FILLED_CONFIRMED","detail":"","reconciled_at":None},
            {"datetime":"2026-07-11 06:20:14","market":"US","strategy":"turtle","side":"BUY","symbol":"AES","qty":1,"price":14.74,"status":"DRY_RUN","detail":"","reconciled_at":None},
        ]}
        (root/"order_ledger.json").write_text(json.dumps(orders),encoding="utf-8")
        for name in ("trade_state.json","trade_state_daytrade.json","us_trade_state_daytrade.json"):
            (root/name).write_text(json.dumps({"positions":{}}),encoding="utf-8")
        (root/"us_trade_state.json").write_text(json.dumps({"date":"2026-08-15","positions":{"HPE":{"entry_price":59.94,"qty":1}}}),encoding="utf-8")
        snap=LiveTradingEvidenceAdapter(root).load(); fb=build_feedback(snap,"US")
        if len(snap.round_trips)!=1 or len(snap.unmatched_sells)!=1: raise AssertionError("round-trip integrity")
        if "execution_failure" not in fb.classifications: raise AssertionError("execution classification")
        return {"schema_version":1,"round_trips":1,"unmatched_sells":1,"failed_orders":fb.failed_order_count,
            "hypotheses":len(fb.hypotheses),"read_only":True,"strategy_mutated":False,
            "order_executed":False,"champion_promoted":False,"approval_bypassed":False,"safety":"pass"}
